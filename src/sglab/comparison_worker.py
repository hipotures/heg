from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from time import monotonic
from typing import Any, Callable
import asyncio
import json
import os
import re
import shutil
import socket
import uuid

from .comparisons import ComparisonStore, canonical_bytes, canonical_sha256
from .research.app_server_client import (
    AppServerClient,
    AppServerConfig,
    AppServerError,
    AppServerSession,
    AppServerTurnEvent,
    AppServerTurnResult,
    AppServerTurnTimeout,
)
from .research.context import DirectorContextMode, evidence_registry_ids
from .research.store import ResearchStore, new_id
from .research.validation import DecisionContext, validate_decision
from .state import atomic_write_json, utc_now


LEASE_SECONDS = 15
HEARTBEAT_SECONDS = 2.0
MAX_CONCURRENT_SUITES = 1
TERMINAL_STATES = {
    "completed",
    "schema_invalid",
    "semantic_invalid",
    "timed_out",
    "aborted",
    "failed",
    "blocked",
    "stopped",
}
INTERMEDIATE_ARM_COLUMN_STATES = {
    "planned": "planned",
    "preflight": "preflight",
    "auth_prepared": "preflight",
    "server_started": "preflight",
    "thread_ready": "preflight",
    "inference_reserved": "preflight",
    "inference_started": "inference_started",
}


class ComparisonWorkerError(RuntimeError):
    pass


class WorkerStopped(ComparisonWorkerError):
    pass


@dataclass(frozen=True, slots=True)
class WorkerResult:
    ok: bool
    suite_id: str
    attempt_id: str | None
    terminal_status: str
    terminal_reason: str | None
    inference_starts: int


@dataclass(frozen=True, slots=True)
class FixtureContract:
    state: dict[str, Any]
    prompt: str
    output_schema: dict[str, Any]
    applicable_action_space: dict[str, Any]
    evidence_registry: dict[str, Any]
    advisory_registry: dict[str, Any]
    executable_registry: dict[str, Any]
    base_instructions: str
    developer_instructions: str
    campaign_budget: dict[str, Any]


@dataclass(slots=True)
class RuntimeGroup:
    client: AppServerClient
    session: AppServerSession
    session_record_id: str
    application_data: Path


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _future_time(seconds: int) -> str:
    return (
        datetime.now(UTC) + timedelta(seconds=seconds)
    ).isoformat(timespec="seconds").replace("+00:00", "Z")


def _identifier(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def process_is_live(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ComparisonWorkerError("artifact path is not a safe relative path")
    return path


def _write_private_json(path: Path, value: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    atomic_write_json(path, value)
    path.chmod(0o600)
    return sha256(path.read_bytes()).hexdigest()


def _write_private_bytes(path: Path, value: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, path)
    return sha256(value).hexdigest()


def _copy_auth_only(source: Path, application_data: Path) -> None:
    resolved = source.expanduser().resolve()
    if resolved.name != "auth.json" or resolved.is_symlink() or not resolved.is_file():
        raise ComparisonWorkerError(
            "server-configured auth source must be a regular auth.json"
        )
    home = application_data / "director" / "codex-home"
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    home.chmod(0o700)
    destination = home / "auth.json"
    temporary = home / "auth.json.importing"
    with resolved.open("rb") as reader, temporary.open("wb") as writer:
        shutil.copyfileobj(reader, writer, length=1024 * 1024)
        writer.flush()
        os.fsync(writer.fileno())
    temporary.chmod(0o600)
    os.replace(temporary, destination)
    destination.chmod(0o600)


def _registry_ids(registry: dict[str, Any], *kinds: str) -> frozenset[str]:
    return evidence_registry_ids(
        registry,
        kinds=frozenset(kinds) if kinds else None,
    )


def _decision_context(contract: FixtureContract) -> DecisionContext:
    action_space = contract.applicable_action_space
    references = action_space.get("reference_objects", [])
    lanes = [
        value
        for value in references
        if isinstance(value, dict)
        and value.get("object_kind") == "lane"
        and value.get("executable_allowed") is True
        and value.get("status") in {"active", "running"}
    ]
    lane_versions = {
        str(value["id"]): int(value.get("version", 0))
        for value in lanes
        if isinstance(value.get("id"), str)
    }
    lane_algorithms = {
        str(value["id"]): str(value.get("algorithm", ""))
        for value in lanes
        if isinstance(value.get("id"), str)
    }
    snapshot_id = str(
        contract.state.get("source_snapshot_id")
        or contract.state.get("snapshot_id")
        or ""
    )
    return DecisionContext(
        snapshot_id=snapshot_id,
        evidence_ids=_registry_ids(contract.evidence_registry),
        lane_versions=lane_versions,
        lane_algorithms=lane_algorithms,
        checkpoint_ids=_registry_ids(contract.evidence_registry, "checkpoint"),
        candidate_ids=_registry_ids(
            contract.evidence_registry, "candidate", "best_candidate"
        ),
        hypothesis_ids=_registry_ids(contract.evidence_registry, "hypothesis"),
        advisory_target_ids=_registry_ids(contract.advisory_registry),
        executable_target_ids=_registry_ids(contract.executable_registry),
        applicable_action_types=frozenset(
            str(value) for value in action_space.get("actions", [])
        ),
    )


def _schema_shape_valid(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {
        "schema_version",
        "snapshot_id",
        "campaign_assessment",
        "hypothesis_updates",
        "actions",
        "next_review",
    }


def _decision_text(value: Any) -> str:
    values: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            values.append(item)
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return "\n".join(values).lower()


def _automatic_validity(
    decision: dict[str, Any],
    context: DecisionContext,
) -> tuple[bool, dict[str, bool], list[str], dict[str, Any]]:
    validation = validate_decision(decision, context)
    normalized = validation.normalized or decision
    text = _decision_text(normalized)
    no_tool = not any(value in text for value in ("tool call", "use a tool"))
    no_code = not any(
        value in text for value in ("generate code", "write code", "create script")
    )
    no_shell = not any(
        value in text for value in ("shell command", "run command", "execute command")
    )
    no_counterexample = "certified counterexample" not in text
    no_execution = not any(
        value in text
        for value in (
            "execute this decision",
            "dispatch this action",
            "run this batch",
        )
    )
    checks = {
        "evidence_references_valid": validation.accepted,
        "action_inside_applicable_space": validation.accepted,
        "executable_targets_valid": validation.accepted,
        "implemented_parameters_only": validation.accepted,
        "budgets_respected": validation.accepted,
        "no_false_counterexample_claim": no_counterexample,
        "no_tool_request": no_tool,
        "no_code_request": no_code,
        "no_shell_request": no_shell,
        "no_measurement_execution_request": no_execution,
    }
    issues = [
        f"{issue.path}: {issue.message}" for issue in validation.issues
    ]
    for name, passed in checks.items():
        if not passed and name not in {
            "evidence_references_valid",
            "action_inside_applicable_space",
            "executable_targets_valid",
            "implemented_parameters_only",
            "budgets_respected",
        }:
            issues.append(f"$: automatic validity failed: {name}")
    return all(checks.values()), checks, issues, normalized


def _usage_payload(result: AppServerTurnResult) -> dict[str, Any] | None:
    usage = result.usage
    if usage is None:
        return None
    return {
        "input_tokens": usage.input_tokens,
        "cached_input_tokens": usage.cached_input_tokens,
        "cache_write_input_tokens": usage.cache_write_input_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_output_tokens": usage.reasoning_output_tokens,
        "total_tokens": usage.total_tokens,
        "raw": usage.raw,
    }


class ComparisonWorker:
    def __init__(
        self,
        *,
        workspace: Path,
        suite_id: str,
        auth_source: Path | None,
        launcher: tuple[str, ...] = ("codex",),
        pid: int | None = None,
        process_group_id: int | None = None,
        host_identifier: str | None = None,
        lease_seconds: int = LEASE_SECONDS,
        maximum_concurrent_suites: int = MAX_CONCURRENT_SUITES,
        process_is_live: Callable[[int], bool] = process_is_live,
    ):
        self.workspace = workspace.resolve()
        self.database = self.workspace / "results.sqlite3"
        if re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", suite_id
        ) is None:
            raise ValueError("invalid comparison suite ID")
        self.suite_id = suite_id
        self.auth_source = auth_source
        self.launcher = launcher
        self.pid = pid if pid is not None else os.getpid()
        self.process_group_id = (
            process_group_id
            if process_group_id is not None
            else os.getpgrp()
        )
        self.host_identifier = host_identifier or socket.gethostname()
        self.lease_seconds = lease_seconds
        if not 1 <= maximum_concurrent_suites <= 8:
            raise ValueError("maximum concurrent suites must be between 1 and 8")
        self.maximum_concurrent_suites = maximum_concurrent_suites
        self.process_is_live = process_is_live
        self.worker_instance_id = _identifier("comparison-worker")
        self.attempt_id: str | None = None
        self.lease_id: str | None = None
        self.inference_starts = 0
        self.started = monotonic()
        self._groups: dict[str, RuntimeGroup] = {}
        self._research_store: ResearchStore | None = None
        self._runtime_campaign_id: str | None = None

    def run(self) -> WorkerResult:
        terminal = "failed"
        reason: str | None = None
        try:
            result = asyncio.run(self._run())
            terminal = result.terminal_status
            reason = result.terminal_reason
            return result
        except BaseException as error:
            reason = f"{type(error).__name__}: {error}"
            self._finish_runtime_campaign(reason)
            if self.attempt_id is not None:
                terminal = (
                    "authorization_exhausted"
                    if "inference cap exhausted" in str(error)
                    else "failed"
                )
                self._finish_attempt(terminal, reason)
                self._fail_suite(reason)
            return WorkerResult(
                False,
                self.suite_id,
                self.attempt_id,
                terminal,
                reason,
                self.inference_starts,
            )
        finally:
            if self.lease_id is not None:
                self._release_lease(reason or terminal)
            if self._research_store is not None:
                self._research_store.close()

    async def _run(self) -> WorkerResult:
        plan, authorization = self._verify_exact_plan()
        self._create_attempt(plan, authorization)
        self._acquire_lease()
        self._mark_suite_running()
        self._ensure_runtime_campaign()
        arms = list(plan["arms"])
        nonfatal_failures: list[str] = []
        try:
            for actual_order, arm in enumerate(arms):
                with ComparisonStore(
                    self.database
                ) as store, store.connection:
                    store.connection.execute(
                        """
                        UPDATE comparison_arms SET actual_order=?
                        WHERE arm_id=? AND actual_order IS NULL
                        """,
                        (actual_order, arm["arm_id"]),
                    )
                self._heartbeat()
                self._check_worker_wall(plan)
                if self._stop_requested():
                    self._block_remaining(arms, arm["arm_id"], "stopped")
                    raise WorkerStopped("operator stop requested before next arm")
                if self._token_cap_reached(plan):
                    self._block_remaining(
                        arms, arm["arm_id"], "authoritative token cap reached"
                    )
                    raise ComparisonWorkerError("authoritative token cap reached")
                dependency = arm.get("depends_on_arm_id")
                if dependency and arm.get("requires_prior_success"):
                    if self._latest_transition(str(dependency)) != "completed":
                        self._transition(
                            str(arm["arm_id"]),
                            "blocked",
                            "required prior arm did not complete",
                        )
                        if plan["fail_closed"]:
                            self._block_remaining(
                                arms,
                                str(arm["arm_id"]),
                                "dependency blocked fail-closed sequence",
                                include_current=False,
                            )
                            raise ComparisonWorkerError(
                                "persistent dependency did not complete"
                            )
                        nonfatal_failures.append(
                            f"{arm['arm_id']}: dependency blocked"
                        )
                        continue
                outcome = await self._execute_arm(plan, authorization, arm)
                if outcome != "completed":
                    if outcome == "stopped":
                        self._block_remaining(
                            arms,
                            str(arm["arm_id"]),
                            "operator stop",
                            include_current=False,
                        )
                        raise WorkerStopped("operator stop requested")
                    if plan["fail_closed"]:
                        self._block_remaining(
                            arms,
                            str(arm["arm_id"]),
                            f"fail-closed after {outcome}",
                            include_current=False,
                        )
                        raise ComparisonWorkerError(f"arm ended as {outcome}")
                    nonfatal_failures.append(f"{arm['arm_id']}: {outcome}")
        except WorkerStopped as error:
            await self._close_groups()
            self._finish_runtime_campaign(str(error))
            if self._stop_requested():
                self._observe_stop("stopped")
            self._finish_attempt("stopped", str(error))
            with ComparisonStore(self.database) as store, store.connection:
                store.connection.execute(
                    """
                    UPDATE comparison_suites
                    SET status='stopped', completed_at=?, failure_reason=?
                    WHERE suite_id=?
                    """,
                    (utc_now(), str(error), self.suite_id),
                )
            return WorkerResult(
                True,
                self.suite_id,
                self.attempt_id,
                "stopped",
                str(error),
                self.inference_starts,
            )
        except BaseException:
            await self._close_groups()
            raise
        await self._close_groups()
        if nonfatal_failures:
            reason = "; ".join(nonfatal_failures)
            self._finish_attempt("failed", reason)
            self._finish_runtime_campaign(reason)
            with ComparisonStore(self.database) as store, store.connection:
                store.connection.execute(
                    """
                    UPDATE comparison_suites
                    SET status='failed', completed_at=?, failure_reason=?
                    WHERE suite_id=?
                    """,
                    (utc_now(), reason, self.suite_id),
                )
            return WorkerResult(
                False,
                self.suite_id,
                self.attempt_id,
                "failed",
                reason,
                self.inference_starts,
            )
        self._finish_attempt("completed", None)
        self._finish_runtime_campaign("comparison measurement completed")
        self._complete_authorization()
        with ComparisonStore(self.database) as store, store.connection:
            store.connection.execute(
                """
                UPDATE comparison_suites
                SET status='completed', completed_at=?, failure_reason=NULL,
                    stop_state=NULL
                WHERE suite_id=?
                """,
                (utc_now(), self.suite_id),
            )
        return WorkerResult(
            True,
            self.suite_id,
            self.attempt_id,
            "completed",
            None,
            self.inference_starts,
        )

    def _verify_exact_plan(self) -> tuple[dict[str, Any], dict[str, Any]]:
        with ComparisonStore(self.database) as store:
            suite = store._suite_row(self.suite_id)
            if suite["read_only"]:
                raise ComparisonWorkerError("historical comparison suite is read-only")
            if suite["status"] != "authorized":
                raise ComparisonWorkerError("suite is not authorized")
            if not suite["measurement_only"] or suite["execute_decisions"]:
                raise ComparisonWorkerError(
                    "worker permits measurement-only non-executing suites"
                )
            plan = store.plan_payload(self.suite_id)
            fingerprint = canonical_sha256(plan)
            if fingerprint != str(suite["plan_fingerprint"]):
                raise ComparisonWorkerError("plan fingerprint changed after authorization")
            authorization_row = store.connection.execute(
                """
                SELECT * FROM comparison_authorizations
                WHERE suite_id=? AND plan_fingerprint=?
                  AND revoked_at IS NULL AND completed_at IS NULL
                ORDER BY authorized_at DESC LIMIT 1
                """,
                (self.suite_id, fingerprint),
            ).fetchone()
            if authorization_row is None:
                raise ComparisonWorkerError("exact authorization is unavailable")
            authorization = dict(authorization_row)
            models = set(json.loads(str(authorization["authorized_models"])))
            efforts = set(json.loads(str(authorization["authorized_efforts"])))
            modes = set(json.loads(str(authorization["authorized_context_modes"])))
            if len(plan["arms"]) != int(plan["planned_inference_count"]):
                raise ComparisonWorkerError("authorized arm count is inconsistent")
            if len(plan["arms"]) > int(authorization["maximum_inference_starts"]):
                raise ComparisonWorkerError("authorized inference cap is below arm count")
            for arm in plan["arms"]:
                if (
                    arm["model"] not in models
                    or arm["reasoning_effort"] not in efforts
                    or arm["context_mode"] not in modes
                ):
                    raise ComparisonWorkerError(
                        f"authorization does not permit arm {arm['arm_id']}"
                    )
            self._load_fixture_contract(store, verify_only=True)
        return plan, authorization

    def _load_fixture_contract(
        self, store: ComparisonStore, *, verify_only: bool = False
    ) -> FixtureContract:
        suite = store._suite_row(self.suite_id)
        row = store.connection.execute(
            "SELECT * FROM comparison_fixtures WHERE fixture_id=?",
            (suite["fixture_reference"],),
        ).fetchone()
        if row is None:
            raise ComparisonWorkerError("comparison fixture is missing")
        required = {
            "prompt_text": row["prompt_text"],
            "output_schema_json": row["output_schema_json"],
            "applicable_action_space_json": row["applicable_action_space_json"],
            "evidence_registry_json": row["evidence_registry_json"],
            "advisory_registry_json": row["advisory_registry_json"],
            "executable_registry_json": row["executable_registry_json"],
            "base_instructions_text": row["base_instructions_text"],
            "developer_instructions_text": row["developer_instructions_text"],
            "campaign_budget_json": row["campaign_budget_json"],
        }
        missing = sorted(name for name, value in required.items() if value is None)
        if missing:
            raise ComparisonWorkerError(
                "fixture lacks executable immutable material: " + ", ".join(missing)
            )
        state = json.loads(str(row["director_state_json"]))
        contract = FixtureContract(
            state=state,
            prompt=str(row["prompt_text"]),
            output_schema=json.loads(str(row["output_schema_json"])),
            applicable_action_space=json.loads(
                str(row["applicable_action_space_json"])
            ),
            evidence_registry=json.loads(str(row["evidence_registry_json"])),
            advisory_registry=json.loads(str(row["advisory_registry_json"])),
            executable_registry=json.loads(str(row["executable_registry_json"])),
            base_instructions=str(row["base_instructions_text"]),
            developer_instructions=str(row["developer_instructions_text"]),
            campaign_budget=json.loads(str(row["campaign_budget_json"])),
        )
        if not contract.base_instructions.strip():
            raise ComparisonWorkerError("fixture requires non-empty base instructions")
        if contract.developer_instructions != "":
            raise ComparisonWorkerError(
                "comparison worker requires empty developer instructions"
            )
        state_bytes = len(canonical_bytes(contract.state))
        if state_bytes > 32 * 1024:
            raise ComparisonWorkerError("DirectorStateV2 exceeds 32 KiB")
        estimated_tokens = (
            state_bytes
            + len(contract.prompt.encode("utf-8"))
            + len(canonical_bytes(contract.output_schema))
            + len(contract.base_instructions.encode("utf-8"))
            + 3
        ) // 4
        if estimated_tokens > int(
            suite["maximum_client_owned_tokens_per_turn"]
        ):
            raise ComparisonWorkerError(
                "fixture exceeds client-owned input token limit"
            )
        checks = {
            "fixture_sha256": sha256(canonical_bytes(contract.state)).hexdigest(),
            "prompt_sha256": sha256(contract.prompt.encode("utf-8")).hexdigest(),
            "output_schema_sha256": canonical_sha256(contract.output_schema),
            "applicable_action_space_sha256": canonical_sha256(
                contract.applicable_action_space
            ),
            "evidence_registry_sha256": canonical_sha256(
                contract.evidence_registry
            ),
            "advisory_registry_sha256": canonical_sha256(
                contract.advisory_registry
            ),
            "executable_registry_sha256": canonical_sha256(
                contract.executable_registry
            ),
            "base_instructions_sha256": sha256(
                contract.base_instructions.encode("utf-8")
            ).hexdigest(),
            "developer_instructions_sha256": sha256(
                contract.developer_instructions.encode("utf-8")
            ).hexdigest(),
            "campaign_budget_sha256": canonical_sha256(contract.campaign_budget),
        }
        for column, actual in checks.items():
            expected = str(row[column])
            if expected != actual:
                raise ComparisonWorkerError(
                    f"fixture material hash mismatch: {column}"
                )
        if verify_only:
            _decision_context(contract)
        return contract

    def _create_attempt(
        self, plan: dict[str, Any], authorization: dict[str, Any]
    ) -> None:
        attempt_id = _identifier("comparison-attempt")
        root = self._execution_root() / "attempts" / attempt_id
        artifact = root / "plan-verification.json"
        payload = {
            "schema_version": "1.0",
            "suite_id": self.suite_id,
            "authorization_id": authorization["authorization_id"],
            "plan_fingerprint": authorization["plan_fingerprint"],
            "recomputed_plan_fingerprint": canonical_sha256(plan),
            "arm_ids": [arm["arm_id"] for arm in plan["arms"]],
            "measurement_only": plan["measurement_only"],
            "execute_decisions": plan["execute_decisions"],
            "verified_at": utc_now(),
            "ok": True,
        }
        digest = _write_private_json(artifact, payload)
        relative = artifact.relative_to(self.workspace)
        with ComparisonStore(self.database) as store, store.connection:
            store.connection.execute(
                """
                INSERT INTO comparison_execution_attempts
                (attempt_id, suite_id, authorization_id, worker_instance_id,
                 plan_fingerprint, plan_verification_artifact,
                 plan_verification_sha256, status, pid, process_group_id,
                 host_identifier, started_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'launching', ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    self.suite_id,
                    authorization["authorization_id"],
                    self.worker_instance_id,
                    authorization["plan_fingerprint"],
                    str(relative),
                    digest,
                    self.pid,
                    self.process_group_id,
                    self.host_identifier,
                    utc_now(),
                ),
            )
        self.attempt_id = attempt_id

    def _acquire_lease(self) -> None:
        assert self.attempt_id is not None
        now = utc_now()
        lease_id = _identifier("comparison-lease")
        with ComparisonStore(self.database) as store:
            connection = store.connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                active = connection.execute(
                    """
                    SELECT * FROM comparison_worker_leases
                    WHERE suite_id=? AND released_at IS NULL
                    ORDER BY acquired_at DESC LIMIT 1
                    """,
                    (self.suite_id,),
                ).fetchone()
                if active is not None:
                    unexpired = _parse_time(str(active["lease_expires_at"])) > datetime.now(UTC)
                    live = self.process_is_live(int(active["pid"]))
                    if unexpired or live:
                        raise ComparisonWorkerError(
                            "a valid worker lease already exists"
                        )
                active_leases = list(connection.execute(
                    """
                    SELECT pid, lease_expires_at FROM comparison_worker_leases
                    WHERE released_at IS NULL AND suite_id<>?
                    """,
                    (self.suite_id,),
                ))
                running = sum(
                    _parse_time(str(row["lease_expires_at"])) > datetime.now(UTC)
                    or self.process_is_live(int(row["pid"]))
                    for row in active_leases
                )
                if running >= self.maximum_concurrent_suites:
                    raise ComparisonWorkerError(
                        "maximum concurrent comparison suites reached"
                    )
                connection.execute(
                    """
                    INSERT INTO comparison_worker_leases
                    (lease_id, worker_instance_id, suite_id, attempt_id, pid,
                     process_group_id, host_identifier, acquired_at,
                     heartbeat_at, lease_expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        lease_id,
                        self.worker_instance_id,
                        self.suite_id,
                        self.attempt_id,
                        self.pid,
                        self.process_group_id,
                        self.host_identifier,
                        now,
                        now,
                        _future_time(self.lease_seconds),
                    ),
                )
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()
        self.lease_id = lease_id

    def _heartbeat(self) -> None:
        if self.lease_id is None:
            raise ComparisonWorkerError("worker lease is unavailable")
        with ComparisonStore(self.database) as store, store.connection:
            cursor = store.connection.execute(
                """
                UPDATE comparison_worker_leases
                SET heartbeat_at=?, lease_expires_at=?
                WHERE lease_id=? AND released_at IS NULL
                """,
                (utc_now(), _future_time(self.lease_seconds), self.lease_id),
            )
            if cursor.rowcount != 1:
                raise ComparisonWorkerError("worker lease was lost")

    def _release_lease(self, reason: str) -> None:
        with ComparisonStore(self.database) as store, store.connection:
            store.connection.execute(
                """
                UPDATE comparison_worker_leases
                SET released_at=COALESCE(released_at, ?),
                    terminal_reason=COALESCE(terminal_reason, ?)
                WHERE lease_id=?
                """,
                (utc_now(), reason[:2000], self.lease_id),
            )

    def _mark_suite_running(self) -> None:
        assert self.attempt_id is not None
        with ComparisonStore(self.database) as store, store.connection:
            store.connection.execute(
                """
                UPDATE comparison_execution_attempts SET status='running'
                WHERE attempt_id=?
                """,
                (self.attempt_id,),
            )
            store.connection.execute(
                """
                UPDATE comparison_suites
                SET status='running', started_at=COALESCE(started_at, ?),
                    failure_reason=NULL
                WHERE suite_id=?
                """,
                (utc_now(), self.suite_id),
            )

    def _ensure_runtime_campaign(self) -> None:
        store = ResearchStore(self.database)
        row = store.connection.execute(
            "SELECT campaign_id FROM comparison_runtime_campaigns WHERE suite_id=?",
            (self.suite_id,),
        ).fetchone()
        if row is None:
            campaign_id = _identifier("comparison-runtime")
            store.create_campaign(
                campaign_id=campaign_id,
                target="comparison_measurement",
                target_definition_sha256=sha256(
                    self.suite_id.encode("utf-8")
                ).hexdigest(),
                stop_mode="until_success",
                deadline_at=None,
                effective_context_mode="stateless_turns",
                context_recommendation_basis="comparison measurement bridge",
            )
            with store.transaction() as database:
                database.execute(
                    """
                    INSERT INTO comparison_runtime_campaigns
                    (suite_id, campaign_id, created_at) VALUES (?, ?, ?)
                    """,
                    (self.suite_id, campaign_id, utc_now()),
                )
        else:
            campaign_id = str(row["campaign_id"])
        self._research_store = store
        self._runtime_campaign_id = campaign_id

    async def _execute_arm(
        self,
        plan: dict[str, Any],
        authorization: dict[str, Any],
        arm: dict[str, Any],
    ) -> str:
        arm_id = str(arm["arm_id"])
        self._transition(arm_id, "preflight")
        with ComparisonStore(self.database) as store:
            contract = self._load_fixture_contract(store)
        group_id = str(arm["conversation_group_id"])
        runtime = self._groups.get(group_id)
        if arm["fresh_thread"]:
            if runtime is not None:
                raise ComparisonWorkerError("fresh arm collided with an active group")
            runtime = await self._start_runtime_group(plan, arm, contract)
            self._groups[group_id] = runtime
        elif arm["resume_prior_thread"]:
            if runtime is None:
                raise ComparisonWorkerError("persistent thread group is unavailable")
            runtime.session = await runtime.client.resume_thread(
                runtime.session.thread_id, contract.base_instructions
            )
            runtime.session_record_id = self._record_session(
                runtime.session,
                arm,
                parent_thread_id=runtime.session.thread_id,
            )
        else:
            raise ComparisonWorkerError("arm has no valid thread behavior")
        effective_model = runtime.session.server_reported_model
        effective_effort = runtime.session.server_reported_effort
        model_matched = (
            effective_model == arm["expected_model"]
            and effective_effort == arm["expected_reasoning_effort"]
        )
        effective_context = str(
            runtime.session.raw_thread.get(
                "effectiveContextMode", arm["context_mode"]
            )
        )
        context_matched = (
            effective_context == arm["context_mode"]
            and arm["context_mode"]
            in {"stateless_turns", "persistent_thread"}
        )
        with ComparisonStore(self.database) as store, store.connection:
            store.connection.execute(
                """
                UPDATE comparison_arms
                SET effective_model=?, effective_reasoning_effort=?,
                    effective_context_mode=?, model_contract_matched=?,
                    context_contract_matched=?, app_thread_id=?,
                    runtime_relative_dir=?
                WHERE arm_id=?
                """,
                (
                    effective_model,
                    effective_effort,
                    effective_context,
                    int(model_matched),
                    int(context_matched),
                    runtime.session.thread_id,
                    str(runtime.application_data.relative_to(self.workspace)),
                    arm_id,
                ),
            )
        if not model_matched or not context_matched:
            self._transition(arm_id, "failed", "runtime contract mismatch")
            return "failed"
        self._transition(arm_id, "thread_ready")
        reservation_id = self._reserve_inference(
            authorization, arm_id, str(plan["maximum_inference_starts"])
        )
        self._transition(arm_id, "inference_reserved")
        app_turn_record_id, comparison_turn_id = self._begin_turn(
            arm, runtime, contract
        )
        reached = False

        def on_event(event: AppServerTurnEvent) -> None:
            nonlocal reached
            assert self._research_store is not None
            if event.lifecycle_status in {"requested", "started", "in_progress"}:
                if not reached:
                    self._consume_inference(reservation_id)
                    self.inference_starts += 1
                    reached = True
                    self._transition(arm_id, "inference_started")
            self._research_store.record_turn_event(
                app_turn_record_id,
                event_sequence=event.sequence,
                lifecycle_status=event.lifecycle_status,
                request_id=event.request_id,
                thread_id=event.thread_id,
                turn_id=event.turn_id,
                items=event.items,
                terminal_reason=event.terminal_reason,
                usage=(
                    {
                        "input_tokens": event.usage.input_tokens,
                        "cached_input_tokens": event.usage.cached_input_tokens,
                        "cache_write_input_tokens": event.usage.cache_write_input_tokens,
                        "output_tokens": event.usage.output_tokens,
                        "reasoning_output_tokens": event.usage.reasoning_output_tokens,
                        "total_tokens": event.usage.total_tokens,
                        "raw": event.usage.raw,
                    }
                    if event.usage is not None
                    else None
                ),
            )
            self._sync_comparison_turn(comparison_turn_id, app_turn_record_id)
            if any(
                item_type not in {"userMessage", "reasoning", "agentMessage"}
                for _, item_type in event.items
            ):
                with ComparisonStore(
                    self.database
                ) as store, store.connection:
                    store.connection.execute(
                        """
                        UPDATE comparison_turns SET tool_call_count=1
                        WHERE comparison_turn_id=?
                        """,
                        (comparison_turn_id,),
                    )

        started = monotonic()
        try:
            result = await self._turn_with_controls(
                runtime.client,
                runtime.session,
                contract.prompt,
                contract.output_schema,
                on_event,
                float(plan["timeout_seconds"]),
                int(plan["maximum_worker_wall_seconds"]),
            )
        except AppServerTurnTimeout:
            if not reached:
                self._release_reservation(reservation_id, "timeout_before_inference")
            self._finish_incomplete_turn(
                comparison_turn_id,
                app_turn_record_id,
                "timed_out",
                "turn wall timeout",
                monotonic() - started,
            )
            self._release_reservation(reservation_id, "timed_out")
            self._transition(arm_id, "timed_out", "turn wall timeout")
            await self._close_group(group_id, interrupted=True)
            return "timed_out"
        except WorkerStopped:
            if not reached:
                self._release_reservation(reservation_id, "stopped_before_inference")
            self._finish_incomplete_turn(
                comparison_turn_id,
                app_turn_record_id,
                "stopped",
                "operator stop",
                monotonic() - started,
            )
            self._release_reservation(reservation_id, "stopped")
            self._transition(arm_id, "stopped", "operator stop")
            await self._close_group(group_id, interrupted=True)
            return "stopped"
        except BaseException as error:
            if not reached:
                self._release_reservation(reservation_id, "failed_before_inference")
            self._finish_incomplete_turn(
                comparison_turn_id,
                app_turn_record_id,
                "failed",
                f"{type(error).__name__}: {error}",
                monotonic() - started,
            )
            self._release_reservation(reservation_id, "failed")
            self._transition(
                arm_id, "failed", f"{type(error).__name__}: {error}"
            )
            await self._close_group(group_id, interrupted=True)
            return "failed"
        if not reached:
            self._release_reservation(reservation_id, "no_inference_event")
            self._transition(arm_id, "failed", "turn completed without inference event")
            return "failed"
        if runtime.client.unsupported_server_requests:
            self._finish_result(
                comparison_turn_id,
                app_turn_record_id,
                result,
                contract,
                "failed",
                ["unsupported server request"],
                monotonic() - started,
            )
            self._release_reservation(
                reservation_id, "unsupported_server_request"
            )
            self._transition(arm_id, "failed", "unsupported server request")
            return "failed"
        if result.retrying_errors:
            self._finish_result(
                comparison_turn_id,
                app_turn_record_id,
                result,
                contract,
                "failed",
                ["server reported a retry after inference start"],
                monotonic() - started,
                retry_count=len(result.retrying_errors),
            )
            self._release_reservation(reservation_id, "retry_after_inference")
            self._transition(
                arm_id, "failed", "server reported a retry after inference start"
            )
            return "failed"
        if (
            plan.get("maximum_total_server_tokens") is not None
            and result.usage is None
        ):
            self._finish_result(
                comparison_turn_id,
                app_turn_record_id,
                result,
                contract,
                "failed",
                ["authoritative usage missing under strict total-token cap"],
                monotonic() - started,
            )
            self._release_reservation(reservation_id, "missing_usage")
            self._transition(
                arm_id,
                "failed",
                "authoritative usage missing under strict total-token cap",
            )
            return "failed"
        if (
            result.usage is not None
            and plan.get("maximum_total_server_tokens") is not None
            and self._current_total_tokens() + result.usage.total_tokens
            > int(plan["maximum_total_server_tokens"])
        ):
            self._finish_result(
                comparison_turn_id,
                app_turn_record_id,
                result,
                contract,
                "failed",
                ["authoritative total-token cap exceeded by completed turn"],
                monotonic() - started,
            )
            self._release_reservation(reservation_id, "token_cap_exceeded")
            self._transition(
                arm_id,
                "failed",
                "authoritative total-token cap exceeded by completed turn",
            )
            return "failed"
        tool_items = [
            item_id
            for item_id, item_type in result.item_types
            if item_type not in {"userMessage", "reasoning", "agentMessage"}
        ]
        if tool_items:
            self._finish_result(
                comparison_turn_id,
                app_turn_record_id,
                result,
                contract,
                "failed",
                ["tool-call item was emitted"],
                monotonic() - started,
                tool_count=len(tool_items),
            )
            self._release_reservation(reservation_id, "tool_call_attempt")
            self._transition(arm_id, "failed", "tool-call attempt")
            return "failed"
        decision = result.parsed
        schema_valid = _schema_shape_valid(decision)
        if not schema_valid:
            status = "schema_invalid"
            semantic = False
            checks: dict[str, bool] = {}
            issues = ["$: structured result did not match Director envelope"]
            normalized = decision if isinstance(decision, dict) else {}
        else:
            assert isinstance(decision, dict)
            semantic, checks, issues, normalized = _automatic_validity(
                decision, _decision_context(contract)
            )
            status = "completed" if semantic else "semantic_invalid"
        self._finish_result(
            comparison_turn_id,
            app_turn_record_id,
            result,
            contract,
            status,
            issues,
            monotonic() - started,
            schema_valid=schema_valid,
            semantic_valid=semantic,
            automatic_validity=checks,
            normalized=normalized,
        )
        self._release_reservation(reservation_id, status)
        self._transition(arm_id, status, "; ".join(issues) or None)
        self._check_artifact_limit(plan)
        if arm["context_mode"] == DirectorContextMode.STATELESS_TURNS.value:
            await self._close_group(group_id)
        return status

    async def _start_runtime_group(
        self,
        plan: dict[str, Any],
        arm: dict[str, Any],
        contract: FixtureContract,
    ) -> RuntimeGroup:
        if arm["context_mode"] == DirectorContextMode.COMPACTED_THREAD.value:
            raise ComparisonWorkerError(
                "compacted_thread execution is not authorized in this milestone"
            )
        if self.auth_source is None:
            raise ComparisonWorkerError("server-configured auth source is unavailable")
        group = str(arm["conversation_group_id"])
        application_data = self._execution_root() / "runtime-groups" / group
        for relative in ("wire", "stderr", "audit"):
            directory = application_data / relative
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)
        _copy_auth_only(self.auth_source, application_data)
        self._transition(str(arm["arm_id"]), "auth_prepared")
        config = AppServerConfig(
            application_data=application_data,
            launcher=self.launcher,
            model=str(arm["model"]),
            effort=str(arm["reasoning_effort"]),
            turn_timeout_seconds=float(plan["timeout_seconds"]),
            usage_wait_seconds=0.5,
            stderr_limit_bytes=int(plan["maximum_stderr_bytes"]),
            wire_limit_bytes=int(plan["maximum_wire_log_bytes"]),
            max_jsonl_bytes=int(plan["maximum_stdout_bytes"]),
            allow_retrying_errors=False,
            environment_exclusions=(
                "SGLAB_CODEX_AUTH_SOURCE",
                "SGLAB_COMPARISON_CODEX_LAUNCHER_JSON",
                "SGLAB_COMPARISON_MAX_CONCURRENT",
            ),
        )
        client = AppServerClient(config)
        await client.start()
        self._transition(str(arm["arm_id"]), "server_started")
        session = await client.start_thread(contract.base_instructions)
        session_record_id = self._record_session(session, arm)
        return RuntimeGroup(client, session, session_record_id, application_data)

    def _record_session(
        self,
        session: AppServerSession,
        arm: dict[str, Any],
        *,
        parent_thread_id: str | None = None,
    ) -> str:
        assert self._research_store is not None
        assert self._runtime_campaign_id is not None
        return self._research_store.record_session(
            record_id=new_id("app-session"),
            campaign_id=self._runtime_campaign_id,
            thread_id=session.thread_id,
            session_id=session.session_id,
            thread_path=session.thread_path,
            parent_thread_id=parent_thread_id,
            model=str(arm["model"]),
            effort=str(arm["reasoning_effort"]),
            codex_version="runtime-discovered",
            executable_sha256="runtime-discovered",
            protocol_schema_sha256="installed-protocol-preflight",
            resumed=bool(arm["resume_prior_thread"]),
            context_mode=str(arm["context_mode"]),
        )

    def _begin_turn(
        self,
        arm: dict[str, Any],
        runtime: RuntimeGroup,
        contract: FixtureContract,
    ) -> tuple[str, str]:
        assert self._research_store is not None
        assert self._runtime_campaign_id is not None
        arm_id = str(arm["arm_id"])
        snapshot_id = f"comparison-snapshot-{arm_id}"
        trigger_id = f"comparison-trigger-{arm_id}"
        root = self._execution_root() / "arms" / arm_id
        request = {
            "prompt": contract.prompt,
            "output_schema": contract.output_schema,
            "evidence_registry": contract.evidence_registry,
            "advisory_registry": contract.advisory_registry,
            "executable_registry": contract.executable_registry,
            "applicable_action_space": contract.applicable_action_space,
            "measurement_only": True,
            "executed": False,
        }
        request_path = root / "request.json"
        request_digest = _write_private_json(request_path, request)
        snapshot_path = root / "director-state-v2.json"
        snapshot_digest = _write_private_json(snapshot_path, contract.state)
        wire_path = root / "wire.jsonl"
        self._research_store.record_snapshot(
            snapshot_id=snapshot_id,
            campaign_id=self._runtime_campaign_id,
            campaign_state_version=0,
            high_water={"comparison_arm_id": arm_id},
            artifact_ref=str(snapshot_path.relative_to(self.workspace)),
            artifact_sha256=snapshot_digest,
            payload_bytes=snapshot_path.stat().st_size,
        )
        self._research_store.record_trigger(
            trigger_id=trigger_id,
            campaign_id=self._runtime_campaign_id,
            campaign_state_version=0,
            reasons=["comparison_measurement"],
            first_event_at=utc_now(),
            snapshot_id=snapshot_id,
        )
        app_turn_id = new_id("app-turn")
        self._research_store.begin_turn(
            turn_record_id=app_turn_id,
            session_record_id=runtime.session_record_id,
            campaign_id=self._runtime_campaign_id,
            thread_id=runtime.session.thread_id,
            snapshot_id=snapshot_id,
            trigger_id=trigger_id,
            request_artifact_ref=str(request_path.relative_to(self.workspace)),
            request_sha256=request_digest,
            wire_artifact_ref=str(wire_path.relative_to(self.workspace)),
            evidence_registry_artifact_ref=str(
                request_path.relative_to(self.workspace)
            ),
            evidence_registry_sha256=canonical_sha256(
                contract.evidence_registry
            ),
            thread_lifecycle=(
                "resumed" if arm["resume_prior_thread"] else "fresh"
            ),
        )
        comparison_turn_id = _identifier("comparison-turn")
        with ComparisonStore(self.database) as store, store.connection:
            store.connection.execute(
                """
                INSERT INTO comparison_turns
                (comparison_turn_id, suite_id, arm_id,
                 app_server_turn_record_id, lifecycle_status,
                 thread_lifecycle, measurement_only, executed,
                 validation_issues_json, created_at, raw_request_artifact)
                VALUES (?, ?, ?, ?, 'inference_reserved', ?, 1, 0, '[]', ?, ?)
                """,
                (
                    comparison_turn_id,
                    self.suite_id,
                    arm_id,
                    app_turn_id,
                    "resumed" if arm["resume_prior_thread"] else "fresh",
                    utc_now(),
                    str(request_path.relative_to(self.workspace)),
                ),
            )
        return app_turn_id, comparison_turn_id

    async def _turn_with_controls(
        self,
        client: AppServerClient,
        session: AppServerSession,
        prompt: str,
        output_schema: dict[str, Any],
        on_event: Callable[[AppServerTurnEvent], None],
        timeout_seconds: float,
        maximum_worker_wall_seconds: int,
    ) -> AppServerTurnResult:
        task = asyncio.create_task(
            client.turn(
                session,
                prompt,
                output_schema=output_schema,
                on_event=on_event,
            )
        )
        next_heartbeat = monotonic() + HEARTBEAT_SECONDS
        try:
            while not task.done():
                await asyncio.sleep(0.1)
                if monotonic() >= next_heartbeat:
                    self._heartbeat()
                    next_heartbeat = monotonic() + HEARTBEAT_SECONDS
                if monotonic() - self.started > maximum_worker_wall_seconds:
                    await client.interrupt_active_turn()
                    raise ComparisonWorkerError(
                        "maximum worker wall time exceeded"
                    )
                if self._stop_requested():
                    self._observe_stop("interrupt_sent")
                    await client.interrupt_active_turn()
                    self._observe_stop("shutdown_draining")
                    try:
                        await asyncio.wait_for(
                            task,
                            timeout=client.config.timeout_drain_seconds,
                        )
                    except (TimeoutError, AppServerError):
                        pass
                    raise WorkerStopped("operator stop requested")
            return await asyncio.wait_for(task, timeout=timeout_seconds)
        except BaseException:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            raise

    def _reserve_inference(
        self,
        authorization: dict[str, Any],
        arm_id: str,
        maximum: str,
    ) -> str:
        assert self.attempt_id is not None
        reservation_id = _identifier("inference-reservation")
        with ComparisonStore(self.database) as store:
            connection = store.connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = connection.execute(
                    """
                    SELECT * FROM comparison_authorizations
                    WHERE authorization_id=?
                    """,
                    (authorization["authorization_id"],),
                ).fetchone()
                if (
                    current is None
                    or current["revoked_at"] is not None
                    or current["completed_at"] is not None
                    or current["plan_fingerprint"] != authorization["plan_fingerprint"]
                ):
                    raise ComparisonWorkerError("authorization is no longer valid")
                reserved = int(
                    connection.execute(
                        """
                        SELECT count(*) FROM comparison_inference_reservations
                        WHERE authorization_id=? AND released_at IS NULL
                          AND inference_reached_at IS NULL
                        """,
                        (authorization["authorization_id"],),
                    ).fetchone()[0]
                )
                consumed = int(current["consumed_inference_starts"])
                cap = min(int(maximum), int(current["maximum_inference_starts"]))
                if consumed + reserved >= cap:
                    raise ComparisonWorkerError("authorized inference cap exhausted")
                connection.execute(
                    """
                    INSERT INTO comparison_inference_reservations
                    (reservation_id, authorization_id, suite_id, arm_id,
                     attempt_id, plan_fingerprint, reserved_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reservation_id,
                        current["authorization_id"],
                        self.suite_id,
                        arm_id,
                        self.attempt_id,
                        current["plan_fingerprint"],
                        utc_now(),
                    ),
                )
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()
        return reservation_id

    def _consume_inference(self, reservation_id: str) -> None:
        with ComparisonStore(self.database) as store:
            connection = store.connection
            connection.execute("BEGIN IMMEDIATE")
            try:
                reservation = connection.execute(
                    """
                    SELECT * FROM comparison_inference_reservations
                    WHERE reservation_id=?
                    """,
                    (reservation_id,),
                ).fetchone()
                if reservation is None or reservation["released_at"] is not None:
                    raise ComparisonWorkerError("inference reservation is unavailable")
                if reservation["inference_reached_at"] is None:
                    connection.execute(
                        """
                        UPDATE comparison_inference_reservations
                        SET inference_reached_at=?
                        WHERE reservation_id=?
                        """,
                        (utc_now(), reservation_id),
                    )
                    connection.execute(
                        """
                        UPDATE comparison_authorizations
                        SET consumed_inference_starts=consumed_inference_starts+1
                        WHERE authorization_id=?
                        """,
                        (reservation["authorization_id"],),
                    )
                    connection.execute(
                        """
                        UPDATE comparison_suites
                        SET consumed_inference_starts=consumed_inference_starts+1
                        WHERE suite_id=?
                        """,
                        (self.suite_id,),
                    )
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _release_reservation(self, reservation_id: str, result: str) -> None:
        with ComparisonStore(self.database) as store, store.connection:
            row = store.connection.execute(
                """
                SELECT inference_reached_at FROM comparison_inference_reservations
                WHERE reservation_id=?
                """,
                (reservation_id,),
            ).fetchone()
            if row is None:
                return
            if row["inference_reached_at"] is not None:
                store.connection.execute(
                    """
                    UPDATE comparison_inference_reservations
                    SET terminal_result=? WHERE reservation_id=?
                    """,
                    (result, reservation_id),
                )
                return
            store.connection.execute(
                """
                UPDATE comparison_inference_reservations
                SET released_at=?, terminal_result=? WHERE reservation_id=?
                """,
                (utc_now(), result, reservation_id),
            )

    def _transition(
        self, arm_id: str, state: str, reason: str | None = None
    ) -> None:
        assert self.attempt_id is not None
        with ComparisonStore(self.database) as store:
            connection = store.connection
            sequence = int(
                connection.execute(
                    """
                    SELECT COALESCE(max(sequence_number), -1)+1
                    FROM comparison_arm_transitions WHERE arm_id=?
                    """,
                    (arm_id,),
                ).fetchone()[0]
            )
            with connection:
                connection.execute(
                    """
                    INSERT INTO comparison_arm_transitions
                    (transition_id, suite_id, arm_id, attempt_id,
                     lifecycle_state, recorded_at, reason, sequence_number)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _identifier("transition"),
                        self.suite_id,
                        arm_id,
                        self.attempt_id,
                        state,
                        utc_now(),
                        reason[:2000] if reason else None,
                        sequence,
                    ),
                )
                column_state = INTERMEDIATE_ARM_COLUMN_STATES.get(state, state)
                if column_state in {
                    "planned",
                    "preflight",
                    "inference_started",
                    "completed",
                    "schema_invalid",
                    "semantic_invalid",
                    "timed_out",
                    "aborted",
                    "failed",
                }:
                    connection.execute(
                        """
                        UPDATE comparison_arms
                        SET status=?, terminal_reason=CASE
                            WHEN ? IN ('completed', 'schema_invalid',
                                      'semantic_invalid', 'timed_out',
                                      'aborted', 'failed')
                            THEN ? ELSE terminal_reason END
                        WHERE arm_id=?
                        """,
                        (column_state, column_state, reason, arm_id),
                    )

    def _latest_transition(self, arm_id: str) -> str | None:
        with ComparisonStore(self.database) as store:
            row = store.connection.execute(
                """
                SELECT lifecycle_state FROM comparison_arm_transitions
                WHERE arm_id=? ORDER BY sequence_number DESC LIMIT 1
                """,
                (arm_id,),
            ).fetchone()
        return str(row[0]) if row is not None else None

    def _sync_comparison_turn(
        self, comparison_turn_id: str, app_turn_record_id: str
    ) -> None:
        with ComparisonStore(self.database) as store, store.connection:
            store.connection.execute(
                """
                UPDATE comparison_turns
                SET lifecycle_status=COALESCE((
                        SELECT lifecycle_status FROM app_server_turns
                        WHERE turn_record_id=?
                    ), lifecycle_status),
                    request_id=(SELECT request_id FROM app_server_turns
                                WHERE turn_record_id=?),
                    thread_id=(SELECT thread_id FROM app_server_turns
                               WHERE turn_record_id=?),
                    turn_id=(SELECT turn_id FROM app_server_turns
                             WHERE turn_record_id=?),
                    item_ids_json=COALESCE((
                        SELECT item_ids_json FROM app_server_turns
                        WHERE turn_record_id=?), '[]'),
                    reasoning_item_ids_json=COALESCE((
                        SELECT reasoning_item_ids_json FROM app_server_turns
                        WHERE turn_record_id=?), '[]'),
                    latest_event_sequence=COALESCE((
                        SELECT latest_event_sequence FROM app_server_turns
                        WHERE turn_record_id=?), 0),
                    terminal_reason=(SELECT terminal_reason FROM app_server_turns
                                     WHERE turn_record_id=?)
                WHERE comparison_turn_id=?
                """,
                (
                    app_turn_record_id,
                    app_turn_record_id,
                    app_turn_record_id,
                    app_turn_record_id,
                    app_turn_record_id,
                    app_turn_record_id,
                    app_turn_record_id,
                    app_turn_record_id,
                    comparison_turn_id,
                ),
            )

    def _finish_result(
        self,
        comparison_turn_id: str,
        app_turn_record_id: str,
        result: AppServerTurnResult,
        contract: FixtureContract,
        status: str,
        issues: list[str],
        wall_seconds: float,
        *,
        schema_valid: bool = False,
        semantic_valid: bool = False,
        automatic_validity: dict[str, bool] | None = None,
        normalized: dict[str, Any] | None = None,
        retry_count: int = 0,
        tool_count: int = 0,
    ) -> None:
        assert self._research_store is not None
        arm_row: Any
        with ComparisonStore(self.database) as store:
            arm_row = store.connection.execute(
                """
                SELECT t.arm_id, a.conversation_group_id
                FROM comparison_turns t
                JOIN comparison_arms a ON a.arm_id=t.arm_id
                WHERE t.comparison_turn_id=?
                """,
                (comparison_turn_id,),
            ).fetchone()
        assert arm_row is not None
        root = self._execution_root() / "arms" / str(arm_row["arm_id"])
        response_path = root / "response.json"
        response_digest = _write_private_json(
            response_path,
            result.parsed if isinstance(result.parsed, dict) else {"raw": result.text},
        )
        group = self._groups[str(arm_row["conversation_group_id"])]
        wire = group.client.take_wire_bytes()
        wire_path = root / "wire.jsonl"
        wire_digest = _write_private_bytes(wire_path, wire)
        stderr_path = root / "stderr.log"
        _write_private_bytes(
            stderr_path, group.client.stderr_text.encode("utf-8")
        )
        usage = _usage_payload(result)
        self._research_store.complete_turn(
            app_turn_record_id,
            turn_id=result.turn_id,
            status=(
                "completed_valid" if status == "completed" else "completed_invalid"
            ),
            final_agent_item_id=result.final_agent_item_id,
            response_artifact_ref=str(response_path.relative_to(self.workspace)),
            response_sha256=response_digest,
            wire_sha256=wire_digest,
            usage=usage,
            wall_seconds=wall_seconds,
            lifecycle_status="completed",
            terminal_reason="; ".join(issues) or None,
        )
        validity = automatic_validity or {}
        actions = (
            normalized.get("actions", [])
            if isinstance(normalized, dict)
            else []
        )
        selected_action = actions[0].get("type") if actions else None
        selected_algorithm = None
        selected_parameters: dict[str, Any] = {}
        if actions:
            spec = actions[0].get("spec")
            if isinstance(spec, dict):
                selected_algorithm = spec.get("algorithm")
                selected_parameters = dict(spec.get("parameters") or {})
        with ComparisonStore(self.database) as store, store.connection:
            store.connection.execute(
                """
                UPDATE comparison_turns
                SET lifecycle_status=?, schema_valid=?, semantic_valid=?,
                    evidence_references_valid=?,
                    action_inside_applicable_space=?,
                    executable_targets_valid=?,
                    implemented_parameters_only=?, budgets_respected=?,
                    no_false_counterexample_claim=?, no_tool_request=?,
                    no_code_request=?, no_shell_request=?,
                    no_measurement_execution_request=?,
                    selected_action=?, selected_algorithm=?,
                    selected_parameters_json=?, raw_decision_json=?,
                    normalized_decision_json=?, validation_issues_json=?,
                    validation_issue_count=?, input_tokens=?,
                    cached_input_tokens=?, cache_write_input_tokens=?,
                    output_tokens=?, reasoning_output_tokens=?,
                    server_reported_total_tokens=?,
                    first_item_latency_seconds=?,
                    final_answer_latency_seconds=?, total_wall_seconds=?,
                    tool_call_count=?, retry_count_reaching_inference=?,
                    completed_at=?, final_answer_present=1,
                    usage_present=?, raw_response_artifact=?,
                    thread_id=?, turn_id=?, item_ids_json=?,
                    reasoning_item_ids_json=?, latest_event_sequence=?,
                    applicable_action_space_json=?,
                    active_executable_lane_count=?,
                    active_candidate_target_count=?,
                    historical_evidence_target_count=?
                WHERE comparison_turn_id=?
                """,
                (
                    status,
                    int(schema_valid),
                    int(semantic_valid),
                    _bool_value(validity.get("evidence_references_valid")),
                    _bool_value(validity.get("action_inside_applicable_space")),
                    _bool_value(validity.get("executable_targets_valid")),
                    _bool_value(validity.get("implemented_parameters_only")),
                    _bool_value(validity.get("budgets_respected")),
                    _bool_value(validity.get("no_false_counterexample_claim")),
                    _bool_value(validity.get("no_tool_request")),
                    _bool_value(validity.get("no_code_request")),
                    _bool_value(validity.get("no_shell_request")),
                    _bool_value(validity.get("no_measurement_execution_request")),
                    selected_action,
                    selected_algorithm,
                    json.dumps(selected_parameters, sort_keys=True),
                    json.dumps(result.parsed, sort_keys=True),
                    json.dumps(normalized, sort_keys=True),
                    json.dumps(issues),
                    len(issues),
                    usage.get("input_tokens") if usage else None,
                    usage.get("cached_input_tokens") if usage else None,
                    usage.get("cache_write_input_tokens") if usage else None,
                    usage.get("output_tokens") if usage else None,
                    usage.get("reasoning_output_tokens") if usage else None,
                    usage.get("total_tokens") if usage else None,
                    result.first_item_latency_seconds,
                    result.final_answer_latency_seconds,
                    wall_seconds,
                    tool_count,
                    retry_count,
                    utc_now(),
                    int(usage is not None),
                    str(response_path.relative_to(self.workspace)),
                    result.thread_id,
                    result.turn_id,
                    json.dumps(result.item_ids),
                    json.dumps(result.reasoning_item_ids),
                    result.latest_event_sequence,
                    json.dumps(contract.applicable_action_space, sort_keys=True),
                    len(
                        contract.applicable_action_space.get(
                            "active_executable_lane_ids", []
                        )
                    ),
                    len(
                        contract.applicable_action_space.get(
                            "candidate_target_ids", []
                        )
                    ),
                    len(
                        contract.applicable_action_space.get(
                            "historical_lane_ids", []
                        )
                    ),
                    comparison_turn_id,
                ),
            )

    def _finish_incomplete_turn(
        self,
        comparison_turn_id: str,
        app_turn_record_id: str,
        status: str,
        reason: str,
        wall_seconds: float,
    ) -> None:
        assert self._research_store is not None
        self._research_store.complete_turn(
            app_turn_record_id,
            turn_id=None,
            status="failed",
            usage=None,
            wall_seconds=wall_seconds,
            error_kind=status,
            error_detail=reason,
            lifecycle_status=(
                "timed_out" if status == "timed_out" else "failed"
            ),
            terminal_reason=reason,
        )
        self._sync_comparison_turn(comparison_turn_id, app_turn_record_id)
        with ComparisonStore(self.database) as store, store.connection:
            store.connection.execute(
                """
                UPDATE comparison_turns
                SET lifecycle_status=?, terminal_reason=?, total_wall_seconds=?,
                    completed_at=?, final_answer_present=0, usage_present=0
                WHERE comparison_turn_id=?
                """,
                (status, reason, wall_seconds, utc_now(), comparison_turn_id),
            )

    async def _close_group(
        self, group_id: str, *, interrupted: bool = False
    ) -> None:
        runtime = self._groups.pop(group_id, None)
        if runtime is None:
            return
        await runtime.client.close(force=interrupted)
        if (
            runtime.client.last_shutdown_mode in {"sigterm", "sigkill"}
            and self._stop_requested()
        ):
            with ComparisonStore(self.database) as store, store.connection:
                store.connection.execute(
                    """
                    UPDATE comparison_stop_requests
                    SET state='forced_termination', forced_termination=1,
                        completed_at=COALESCE(completed_at, ?),
                        terminal_reason=COALESCE(
                            terminal_reason, 'App Server required forced shutdown'
                        )
                    WHERE stop_request_id=(
                        SELECT stop_request_id FROM comparison_stop_requests
                        WHERE suite_id=? ORDER BY requested_at DESC LIMIT 1
                    )
                    """,
                    (utc_now(), self.suite_id),
                )
                store.connection.execute(
                    """
                    UPDATE comparison_suites
                    SET stop_state='forced_termination' WHERE suite_id=?
                    """,
                    (self.suite_id,),
                )
        if self._research_store is not None:
            try:
                self._research_store.close_session(
                    runtime.session_record_id,
                    state="interrupted" if interrupted else "closed",
                )
            except RuntimeError:
                pass

    async def _close_groups(self) -> None:
        for group_id in list(self._groups):
            await self._close_group(group_id)

    def _stop_requested(self) -> bool:
        with ComparisonStore(self.database) as store:
            return (
                store.connection.execute(
                    """
                    SELECT 1 FROM comparison_stop_requests
                    WHERE suite_id=? AND completed_at IS NULL
                    ORDER BY requested_at DESC LIMIT 1
                    """,
                    (self.suite_id,),
                ).fetchone()
                is not None
            )

    def _observe_stop(self, state: str) -> None:
        column = {
            "observed": "observed_at",
            "interrupt_sent": "interrupt_sent_at",
            "shutdown_draining": "draining_started_at",
            "stopped": "completed_at",
        }[state]
        with ComparisonStore(self.database) as store, store.connection:
            cursor = store.connection.execute(
                f"""
                UPDATE comparison_stop_requests
                SET state=?, {column}=COALESCE({column}, ?)
                WHERE stop_request_id=(
                    SELECT stop_request_id FROM comparison_stop_requests
                    WHERE suite_id=? AND completed_at IS NULL
                    ORDER BY requested_at DESC LIMIT 1
                )
                """,
                (state, utc_now(), self.suite_id),
            )
            if cursor.rowcount:
                store.connection.execute(
                    "UPDATE comparison_suites SET stop_state=? WHERE suite_id=?",
                    (state, self.suite_id),
                )

    def _token_cap_reached(self, plan: dict[str, Any]) -> bool:
        maximum = plan.get("maximum_total_server_tokens")
        if maximum is None:
            return False
        with ComparisonStore(self.database) as store:
            rows = list(
                store.connection.execute(
                    """
                    SELECT server_reported_total_tokens, usage_present
                    FROM comparison_turns WHERE suite_id=?
                    """,
                    (self.suite_id,),
                )
            )
        if any(row["usage_present"] == 0 for row in rows):
            raise ComparisonWorkerError(
                "strict total-token cap cannot continue with missing usage"
            )
        total = sum(int(row["server_reported_total_tokens"] or 0) for row in rows)
        return total >= int(maximum)

    def _current_total_tokens(self) -> int:
        with ComparisonStore(self.database) as store:
            return int(
                store.connection.execute(
                    """
                    SELECT COALESCE(sum(server_reported_total_tokens), 0)
                    FROM comparison_turns WHERE suite_id=?
                    """,
                    (self.suite_id,),
                ).fetchone()[0]
            )

    def _check_worker_wall(self, plan: dict[str, Any]) -> None:
        if monotonic() - self.started > int(plan["maximum_worker_wall_seconds"]):
            raise ComparisonWorkerError("maximum worker wall time exceeded")

    def _check_artifact_limit(self, plan: dict[str, Any]) -> None:
        total = sum(
            path.stat().st_size
            for path in self._execution_root().rglob("*")
            if path.is_file() and path.name != "auth.json"
        )
        if total > int(plan["maximum_artifact_directory_bytes"]):
            raise ComparisonWorkerError("comparison artifact directory limit exceeded")

    def _block_remaining(
        self,
        arms: list[dict[str, Any]],
        current_arm_id: str,
        reason: str,
        *,
        include_current: bool = True,
    ) -> None:
        seen = False
        for arm in arms:
            arm_id = str(arm["arm_id"])
            if arm_id == current_arm_id:
                seen = True
                if not include_current:
                    continue
            if seen and self._latest_transition(arm_id) not in TERMINAL_STATES:
                self._transition(arm_id, "blocked", reason)

    def _finish_attempt(self, status: str, reason: str | None) -> None:
        if self.attempt_id is None:
            return
        with ComparisonStore(self.database) as store, store.connection:
            store.connection.execute(
                """
                UPDATE comparison_execution_attempts
                SET status=?, completed_at=?, terminal_reason=?
                WHERE attempt_id=?
                """,
                (status, utc_now(), reason, self.attempt_id),
            )

    def _fail_suite(self, reason: str) -> None:
        with ComparisonStore(self.database) as store, store.connection:
            store.connection.execute(
                """
                UPDATE comparison_suites
                SET status=?, completed_at=?, failure_reason=?
                WHERE suite_id=?
                """,
                (
                    "failed",
                    utc_now(),
                    str(reason)[:2000],
                    self.suite_id,
                ),
            )

    def _complete_authorization(self) -> None:
        with ComparisonStore(self.database) as store, store.connection:
            store.connection.execute(
                """
                UPDATE comparison_authorizations SET completed_at=?
                WHERE suite_id=? AND revoked_at IS NULL AND completed_at IS NULL
                """,
                (utc_now(), self.suite_id),
            )

    def _finish_runtime_campaign(self, detail: str) -> None:
        if self._research_store is None or self._runtime_campaign_id is None:
            return
        try:
            self._research_store.finish_campaign(
                self._runtime_campaign_id,
                terminal_kind="stopped_by_operator",
                detail=detail,
            )
        except (KeyError, RuntimeError):
            pass

    def _execution_root(self) -> Path:
        root = self.workspace / ".sglab" / "comparisons" / self.suite_id
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        return root


def _bool_value(value: bool | None) -> int | None:
    return None if value is None else int(value)


def request_stop(database: Path, suite_id: str) -> str:
    with ComparisonStore(database) as store:
        suite = store._suite_row(suite_id)
        store._require_mutable(suite)
        if suite["status"] not in {"authorized", "running"}:
            raise ValueError("suite cannot be stopped in its current state")
        request_id = _identifier("comparison-stop")
        attempt = store.connection.execute(
            """
            SELECT attempt_id FROM comparison_execution_attempts
            WHERE suite_id=? AND status IN ('launching', 'running')
            ORDER BY started_at DESC LIMIT 1
            """,
            (suite_id,),
        ).fetchone()
        with store.connection:
            store.connection.execute(
                """
                INSERT INTO comparison_stop_requests
                (stop_request_id, suite_id, attempt_id, requested_at, state)
                VALUES (?, ?, ?, ?, 'requested')
                """,
                (
                    request_id,
                    suite_id,
                    attempt["attempt_id"] if attempt else None,
                    utc_now(),
                ),
            )
            if attempt is None:
                store.connection.execute(
                    """
                    UPDATE comparison_stop_requests
                    SET state='stopped', observed_at=?, completed_at=?,
                        terminal_reason='stopped before worker launch'
                    WHERE stop_request_id=?
                    """,
                    (utc_now(), utc_now(), request_id),
                )
                store.connection.execute(
                    """
                    UPDATE comparison_suites
                    SET status='stopped', stop_state='stopped',
                        completed_at=?, failure_reason='stopped before worker launch'
                    WHERE suite_id=?
                    """,
                    (utc_now(), suite_id),
                )
            else:
                store.connection.execute(
                    """
                    UPDATE comparison_suites SET stop_state='requested'
                    WHERE suite_id=?
                    """,
                    (suite_id,),
                )
        return request_id


def recover_stale_workers(database: Path) -> list[str]:
    recovered: list[str] = []
    with ComparisonStore(database) as store:
        rows = list(
            store.connection.execute(
                """
                SELECT * FROM comparison_worker_leases
                WHERE released_at IS NULL
                """
            )
        )
        now = datetime.now(UTC)
        for row in rows:
            if (
                _parse_time(str(row["lease_expires_at"])) >= now
                or process_is_live(int(row["pid"]))
            ):
                continue
            reason = "expired lease and dead PID; automatic paid resume forbidden"
            with store.connection:
                store.connection.execute(
                    """
                    UPDATE comparison_worker_leases
                    SET released_at=?, terminal_reason=?
                    WHERE lease_id=?
                    """,
                    (utc_now(), reason, row["lease_id"]),
                )
                store.connection.execute(
                    """
                    UPDATE comparison_execution_attempts
                    SET status='interrupted', completed_at=?, terminal_reason=?
                    WHERE attempt_id=? AND status IN ('launching', 'running')
                    """,
                    (utc_now(), reason, row["attempt_id"]),
                )
                store.connection.execute(
                    """
                    UPDATE comparison_inference_reservations
                    SET released_at=?, terminal_result='worker_crash_before_inference'
                    WHERE attempt_id=? AND inference_reached_at IS NULL
                      AND released_at IS NULL
                    """,
                    (utc_now(), row["attempt_id"]),
                )
                store.connection.execute(
                    """
                    UPDATE comparison_suites
                    SET status='failed', completed_at=?, failure_reason=?
                    WHERE suite_id=? AND status='running'
                    """,
                    (utc_now(), reason, row["suite_id"]),
                )
            recovered.append(str(row["suite_id"]))
    return recovered
