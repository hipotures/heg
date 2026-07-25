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
import stat
import uuid

from .comparisons import (
    INDEPENDENT_INVALID_CONTINUE_POLICY,
    MODEL_INVALID_ARM_STATES,
    ComparisonStore,
    canonical_bytes,
    canonical_sha256,
)
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
from .research.protocol import hypothesis_updates_match_schema_contract
from .research.store import ResearchStore, new_id
from .research.validation import DecisionContext, validate_decision
from .resource_accounting import (
    CREDENTIAL_MATERIAL,
    LOGS,
    PRESERVED_ARTIFACTS,
    RUNTIME_SCRATCH,
    ResourceAccountingError,
    account_execution_root,
    discover_trusted_codex_roots,
)
from .state import atomic_write_json, read_json, utc_now


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


class ComparisonResourceLimitError(ComparisonWorkerError):
    def __init__(
        self,
        category: str,
        limit_bytes: int,
        peak_bytes: int,
        contributor: str,
        stage: str,
        *,
        failure_domain: str = "byte_quota",
        failure_code: str = "byte_quota_exceeded",
    ):
        if peak_bytes <= limit_bytes:
            raise ValueError("resource quota errors require measured bytes > limit")
        self.category = category
        self.limit_bytes = limit_bytes
        self.peak_bytes = peak_bytes
        self.contributor = contributor
        self.stage = stage
        self.failure_domain = failure_domain
        self.failure_code = failure_code
        super().__init__(
            f"{category} limit exceeded at {stage}: "
            f"{peak_bytes} > {limit_bytes}; largest={contributor or 'none'}"
        )


class ComparisonFilesystemPolicyError(ComparisonWorkerError):
    def __init__(self, code: str, label: str, stage: str):
        self.failure_domain = "filesystem_policy"
        self.failure_code = code
        self.label = label
        self.stage = stage
        super().__init__(
            f"filesystem policy violation at {stage}: {code}; "
            f"entry={label or 'unavailable'}"
        )


class ComparisonAccountingError(ComparisonWorkerError):
    def __init__(self, code: str, stage: str):
        self.failure_domain = "accounting_error"
        self.failure_code = code
        self.stage = stage
        super().__init__(f"resource accounting failed at {stage}: {code}")


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
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(
            encoding="utf-8"
        ).split()
    except (FileNotFoundError, ProcessLookupError):
        return False
    except (OSError, UnicodeError):
        return True
    if len(fields) >= 3 and fields[2] == "Z":
        return False
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


def _schema_shape_valid(value: Any, context: DecisionContext) -> bool:
    return (
        isinstance(value, dict)
        and set(value)
        == {
            "schema_version",
            "snapshot_id",
            "campaign_assessment",
            "hypothesis_updates",
            "actions",
            "next_review",
        }
        and hypothesis_updates_match_schema_contract(
            value["hypothesis_updates"],
            context.hypothesis_ids,
        )
    )


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
        self._resource_peaks: dict[str, tuple[int, int]] = {}
        self._resource_previous: dict[str, int] = {}
        self._resource_last_sample = 0.0
        self._active_plan: dict[str, Any] | None = None
        self._trusted_symlink_roots = discover_trusted_codex_roots(
            self.launcher
        )

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
        self._active_plan = plan
        self._create_attempt(plan, authorization)
        self._sample_resources(plan, "before_auth_preparation")
        self._acquire_lease()
        self._mark_suite_running()
        self._ensure_runtime_campaign()
        arms = list(plan["arms"])
        independent_invalid_continues = (
            plan.get("arm_failure_policy")
            == INDEPENDENT_INVALID_CONTINUE_POLICY
        )
        nonfatal_failures: list[str] = []
        current_arm_id: str | None = None
        try:
            for actual_order, arm in enumerate(arms):
                current_arm_id = str(arm["arm_id"])
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
                        if plan["fail_closed"] and not independent_invalid_continues:
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
                    if (
                        independent_invalid_continues
                        and outcome in MODEL_INVALID_ARM_STATES
                    ):
                        nonfatal_failures.append(
                            f"{arm['arm_id']}: {outcome}"
                        )
                        continue
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
        except BaseException as error:
            if current_arm_id is not None:
                if self._latest_transition(current_arm_id) not in TERMINAL_STATES:
                    self._transition(
                        current_arm_id,
                        "failed",
                        f"infrastructure failure: {type(error).__name__}",
                    )
                self._block_remaining(
                    arms,
                    current_arm_id,
                    f"infrastructure failure: {type(error).__name__}",
                    include_current=False,
                )
            self._sample_resources(
                plan,
                "before_graceful_shutdown",
                arm_id=current_arm_id,
                enforce=False,
            )
            await self._close_groups()
            self._sample_resources(
                plan,
                "after_cleanup",
                arm_id=current_arm_id,
                enforce=False,
                terminal=True,
                cleanup=True,
            )
            self._record_resource_terminal_context(current_arm_id)
            raise
        await self._close_groups()
        self._sample_resources(
            plan, "after_cleanup", enforce=False, terminal=True, cleanup=True
        )
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
            if int(suite["resource_accounting_version"]) < 2:
                raise ComparisonWorkerError(
                    "legacy resource plan cannot execute; create a fresh suite"
                )
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
        digest = self._write_preserved_json(
            artifact, payload, "plan_verification_write"
        )
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
        self._sample_resources(plan, "after_thread_start", arm_id=arm_id)
        reservation_id = self._reserve_inference(
            authorization, arm_id, str(plan["maximum_inference_starts"])
        )
        self._transition(arm_id, "inference_reserved")
        app_turn_record_id, comparison_turn_id = self._begin_turn(
            arm, runtime, contract
        )
        self._sample_resources(plan, "after_turn_start", arm_id=arm_id)
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
            now = monotonic()
            if now - self._resource_last_sample >= 0.25:
                self._sample_resources(
                    plan, "wire_log_growth", arm_id=arm_id
                )
                self._resource_last_sample = now
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
                plan,
                arm_id,
            )
            self._sample_resources(plan, "after_final_answer", arm_id=arm_id)
            if result.usage is not None:
                self._sample_resources(plan, "after_usage", arm_id=arm_id)
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
        decision_context = _decision_context(contract)
        schema_valid = _schema_shape_valid(decision, decision_context)
        if not schema_valid:
            status = "schema_invalid"
            semantic = False
            checks: dict[str, bool] = {}
            issues = ["$: structured result did not match Director envelope"]
            normalized = decision if isinstance(decision, dict) else {}
        else:
            assert isinstance(decision, dict)
            semantic, checks, issues, normalized = _automatic_validity(
                decision, decision_context
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
        self._sample_resources(plan, "after_preservation", arm_id=arm_id)
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
        self._sample_resources(
            plan, "after_runtime_home_creation", arm_id=str(arm["arm_id"])
        )
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
        self._sample_resources(
            plan, "after_private_directories", arm_id=str(arm["arm_id"])
        )
        try:
            await client.start()
            self._transition(str(arm["arm_id"]), "server_started")
            self._sample_resources(
                plan, "after_app_server_start", arm_id=str(arm["arm_id"])
            )
            session = await client.start_thread(contract.base_instructions)
            session_record_id = self._record_session(session, arm)
            return RuntimeGroup(
                client,
                session,
                session_record_id,
                application_data,
            )
        except BaseException:
            await client.close()
            raise

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
        request_digest = self._write_preserved_json(
            request_path, request, "request_preservation"
        )
        snapshot_path = root / "director-state-v2.json"
        snapshot_digest = self._write_preserved_json(
            snapshot_path, contract.state, "director_state_preservation"
        )
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
        plan: dict[str, Any],
        arm_id: str,
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
                    self._sample_resources(
                        plan, "turn_runtime_poll", arm_id=arm_id
                    )
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
        except (
            ComparisonResourceLimitError,
            ComparisonFilesystemPolicyError,
            ComparisonAccountingError,
        ):
            await client.interrupt_active_turn()
            self._mark_resource_interruption()
            try:
                await asyncio.wait_for(
                    asyncio.shield(task),
                    timeout=client.config.timeout_drain_seconds,
                )
            except (TimeoutError, AppServerError):
                pass
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            raise
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
        response_digest = self._write_preserved_json(
            response_path,
            result.parsed if isinstance(result.parsed, dict) else {"raw": result.text},
            "response_preservation",
        )
        group = self._groups[str(arm_row["conversation_group_id"])]
        wire = group.client.take_wire_bytes()
        wire_path = root / "wire.jsonl"
        wire_digest = self._write_preserved_bytes(
            wire_path, wire, "wire_log_preservation"
        )
        stderr_path = root / "stderr.log"
        self._write_preserved_bytes(
            stderr_path,
            group.client.stderr_text.encode("utf-8"),
            "stderr_log_preservation",
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
        if self._active_plan is not None:
            self._sample_resources(
                self._active_plan,
                "during_shutdown_draining",
                enforce=False,
            )
        await runtime.client.close(force=interrupted)
        if self._active_plan is not None:
            self._sample_resources(
                self._active_plan,
                "after_app_server_shutdown",
                enforce=not interrupted,
            )
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

    def _resource_limit(self, plan: dict[str, Any], category: str) -> int | None:
        if category == PRESERVED_ARTIFACTS:
            return int(plan["max_preserved_artifact_bytes"])
        if category == RUNTIME_SCRATCH:
            return int(plan["max_runtime_scratch_bytes"])
        return None

    def _account_resources(self) -> Any:
        return account_execution_root(
            self._execution_root(),
            research_workspace=self.workspace,
            trusted_symlink_roots=self._trusted_symlink_roots,
        )

    def _write_preserved_json(
        self, path: Path, value: dict[str, Any], stage: str
    ) -> str:
        encoded = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode(
            "utf-8"
        )
        self._preflight_preserved_write(path, len(encoded), stage)
        return _write_private_json(path, value)

    def _write_preserved_bytes(
        self, path: Path, value: bytes, stage: str
    ) -> str:
        self._preflight_preserved_write(path, len(value), stage)
        return _write_private_bytes(path, value)

    def _preflight_preserved_write(
        self, path: Path, size: int, stage: str
    ) -> None:
        plan = self._active_plan
        if plan is None:
            raise ComparisonWorkerError("resource plan is unavailable")
        root = self._execution_root()
        try:
            relative = path.absolute().relative_to(root.absolute())
        except ValueError as error:
            raise ComparisonWorkerError(
                "preserved artifact path escapes execution root"
            ) from error
        accounting = self._account_resources()
        total = accounting.categories[PRESERVED_ARTIFACTS].apparent_bytes
        if path.exists():
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode):
                raise ComparisonWorkerError(
                    "preserved artifact target is not a regular file"
                )
            total -= int(metadata.st_size)
        prospective = total + size
        single_limit = int(plan["max_single_preserved_artifact_bytes"])
        total_limit = int(plan["max_preserved_artifact_bytes"])
        log_limit: int | None = None
        lowered = relative.as_posix().lower()
        if "wire" in lowered:
            log_limit = int(plan["maximum_wire_log_bytes"])
        elif "stderr" in lowered:
            log_limit = int(plan["maximum_stderr_bytes"])
        elif "stdout" in lowered:
            log_limit = int(plan["maximum_stdout_bytes"])
        if log_limit is not None and size > log_limit:
            self._raise_prospective_limit(
                accounting,
                LOGS,
                log_limit,
                size,
                relative.as_posix(),
                stage,
                failure_domain="log_quota",
                failure_code="log_quota_exceeded",
            )
        if size > single_limit:
            self._raise_prospective_limit(
                accounting,
                PRESERVED_ARTIFACTS,
                single_limit,
                size,
                relative.as_posix(),
                stage,
                failure_domain="single_file_quota",
                failure_code="single_preserved_artifact_exceeded",
            )
        if prospective > total_limit:
            self._raise_prospective_limit(
                accounting,
                PRESERVED_ARTIFACTS,
                total_limit,
                prospective,
                relative.as_posix(),
                stage,
                failure_domain="byte_quota",
                failure_code="preserved_artifact_quota_exceeded",
            )

    def _raise_prospective_limit(
        self,
        accounting: Any,
        category: str,
        limit: int,
        measured: int,
        contributor: str,
        stage: str,
        *,
        failure_domain: str,
        failure_code: str,
    ) -> None:
        old_peak = self._resource_peaks.get(category, (0, 0))
        peak = max(old_peak[0], measured)
        self._resource_peaks[category] = (peak, old_peak[1])
        self._persist_resource_sample(
            accounting=accounting,
            category=category,
            sample_kind="threshold_crossing",
            stage=stage,
            arm_id=None,
            peak=(peak, old_peak[1]),
            growth={
                "stage": stage,
                "pending_write_bytes": measured,
                "pending_relative_path": contributor,
            },
            decision="exceeded",
            limit=limit,
            cleanup=False,
            errors=[],
            byte_quota_status="exceeded",
            byte_quota_exceeded=True,
            accounting_status="ok",
            symlink_policy_status="passed",
            policy_violation_code=None,
            failure_domain=failure_domain,
            failure_code=failure_code,
            symlink_observations=[],
        )
        self._persist_resource_diagnostic(
            accounting,
            category,
            limit,
            peak,
            contributor,
            stage,
            None,
            failure_domain=failure_domain,
            failure_code=failure_code,
        )
        if self.attempt_id is not None:
            with ComparisonStore(self.database) as store, store.connection:
                store.connection.execute(
                    """
                    UPDATE comparison_suites
                    SET resource_exceeded_category=?,
                        resource_exceeded_limit_bytes=?,
                        resource_peak_bytes=?,
                        resource_largest_contributor=?,
                        resource_enforcement_stage=?,
                        resource_cleanup_status='pending',
                        byte_quota_status='exceeded',
                        byte_quota_exceeded=1,
                        accounting_status='ok',
                        symlink_policy_status='passed',
                        policy_violation_code=NULL,
                        failure_domain=?,
                        failure_code=?,
                        resource_policy_label=NULL
                    WHERE suite_id=?
                    """,
                    (
                        category,
                        limit,
                        peak,
                        contributor,
                        stage,
                        failure_domain,
                        failure_code,
                        self.suite_id,
                    ),
                )
        raise ComparisonResourceLimitError(
            category,
            limit,
            peak,
            contributor,
            stage,
            failure_domain=failure_domain,
            failure_code=failure_code,
        )

    def _sample_resources(
        self,
        plan: dict[str, Any],
        stage: str,
        *,
        arm_id: str | None = None,
        enforce: bool = True,
        terminal: bool = False,
        cleanup: bool = False,
    ) -> None:
        try:
            accounting = self._account_resources()
        except ResourceAccountingError as error:
            if self.attempt_id is not None:
                with ComparisonStore(
                    self.database
                ) as store, store.connection:
                    store.connection.execute(
                        """
                        UPDATE comparison_suites
                        SET accounting_status='error',
                            symlink_policy_status='unknown',
                            byte_quota_status='unknown',
                            byte_quota_exceeded=0,
                            failure_domain='accounting_error',
                            failure_code='resource_traversal_error',
                            resource_enforcement_stage=?
                        WHERE suite_id=?
                        """,
                        (stage, self.suite_id),
                    )
            raise ComparisonAccountingError(
                "resource_traversal_error", stage
            ) from error

        byte_violations: list[dict[str, Any]] = []
        byte_results: dict[str, tuple[str, bool, int | None]] = {}
        for category, totals in accounting.categories.items():
            limit = self._resource_limit(plan, category)
            exceeded = (
                limit is not None and totals.apparent_bytes > limit
            )
            byte_results[category] = (
                "exceeded"
                if exceeded
                else "within_limit"
                if limit is not None
                else "not_applicable",
                exceeded,
                limit,
            )
            if exceeded:
                byte_violations.append(
                    {
                        "category": category,
                        "limit": int(limit),
                        "measured": totals.apparent_bytes,
                        "contributor": (
                            totals.largest_files[0].relative_path
                            if totals.largest_files
                            else ""
                        ),
                        "failure_domain": "byte_quota",
                        "failure_code": f"{category}_quota_exceeded",
                    }
                )

        single_file_violations: list[dict[str, Any]] = []
        for value in accounting.files:
            cap: int | None = None
            failure_domain = "single_file_quota"
            failure_code = "single_runtime_file_exceeded"
            if value.category == PRESERVED_ARTIFACTS:
                cap = int(plan["max_single_preserved_artifact_bytes"])
                failure_code = "single_preserved_artifact_exceeded"
            elif value.category == RUNTIME_SCRATCH:
                cap = int(plan["max_single_runtime_file_bytes"])
            elif value.category == LOGS:
                failure_domain = "log_quota"
                lowered = value.relative_path.lower()
                if "wire" in lowered:
                    cap = int(plan["maximum_wire_log_bytes"])
                    failure_code = "wire_log_quota_exceeded"
                elif "stderr" in lowered:
                    cap = int(plan["maximum_stderr_bytes"])
                    failure_code = "stderr_log_quota_exceeded"
                elif "stdout" in lowered:
                    cap = int(plan["maximum_stdout_bytes"])
                    failure_code = "stdout_log_quota_exceeded"
                else:
                    cap = int(plan["max_single_runtime_file_bytes"])
                    failure_code = "runtime_log_file_exceeded"
            if cap is not None and value.apparent_bytes > cap:
                single_file_violations.append(
                    {
                        "category": value.category,
                        "limit": cap,
                        "measured": value.apparent_bytes,
                        "contributor": value.relative_path,
                        "failure_domain": failure_domain,
                        "failure_code": failure_code,
                    }
                )

        rejected_links = [
            value
            for value in accounting.symlinks
            if value.policy_status == "rejected"
        ]
        violation: dict[str, Any] | None = None
        if accounting.accounting_status == "error":
            observed = rejected_links[0]
            violation = {
                "category": RUNTIME_SCRATCH,
                "limit": None,
                "measured": accounting.categories[
                    RUNTIME_SCRATCH
                ].apparent_bytes,
                "contributor": observed.relative_path,
                "failure_domain": "accounting_error",
                "failure_code": (
                    observed.policy_violation_code
                    or "resource_accounting_error"
                ),
            }
        elif rejected_links:
            observed = rejected_links[0]
            violation = {
                "category": RUNTIME_SCRATCH,
                "limit": None,
                "measured": accounting.categories[
                    RUNTIME_SCRATCH
                ].apparent_bytes,
                "contributor": observed.relative_path,
                "failure_domain": "filesystem_policy",
                "failure_code": (
                    observed.policy_violation_code
                    or "unexpected_external_symlink"
                ),
            }
        elif single_file_violations:
            violation = single_file_violations[0]
        elif byte_violations:
            violation = byte_violations[0]

        errors = [
            value.relative_path
            for value in rejected_links
        ]
        observations = [
            value.as_dict() for value in accounting.symlinks
        ]
        for category, totals in accounting.categories.items():
            previous = self._resource_previous.get(category, 0)
            old_peak = self._resource_peaks.get(category, (0, 0))
            peak = (
                max(old_peak[0], totals.apparent_bytes),
                max(old_peak[1], totals.allocated_bytes),
            )
            is_new_peak = peak != old_peak
            self._resource_peaks[category] = peak
            self._resource_previous[category] = totals.apparent_bytes
            growth = (
                {
                    "stage": stage,
                    "previous_apparent_bytes": previous,
                    "current_apparent_bytes": totals.apparent_bytes,
                    "growth_bytes": totals.apparent_bytes - previous,
                }
                if totals.apparent_bytes > previous
                else None
            )
            byte_status, byte_exceeded, limit = byte_results[category]
            contributor = (
                totals.largest_files[0].relative_path
                if totals.largest_files
                else None
            )
            decision = "within_limit"
            if (
                violation is not None
                and violation["category"] == category
                and violation["failure_domain"] == "accounting_error"
            ):
                decision = "accounting_error"
            elif (
                violation is not None
                and violation["category"] == category
                and violation["failure_domain"] == "filesystem_policy"
            ):
                decision = "policy_violation"
            elif byte_exceeded:
                decision = "exceeded"
            self._persist_resource_sample(
                accounting=accounting,
                category=category,
                sample_kind="terminal" if terminal else "latest",
                stage=stage,
                arm_id=arm_id,
                peak=peak,
                growth=growth,
                decision=decision,
                limit=limit,
                cleanup=cleanup,
                errors=errors,
                byte_quota_status=byte_status,
                byte_quota_exceeded=byte_exceeded,
                accounting_status=accounting.accounting_status,
                symlink_policy_status=accounting.symlink_policy_status,
                policy_violation_code=accounting.policy_violation_code,
                failure_domain=(
                    violation["failure_domain"]
                    if violation is not None
                    and violation["category"] == category
                    else None
                ),
                failure_code=(
                    violation["failure_code"]
                    if violation is not None
                    and violation["category"] == category
                    else None
                ),
                symlink_observations=observations,
            )
            if is_new_peak:
                self._persist_resource_sample(
                    accounting=accounting,
                    category=category,
                    sample_kind="peak",
                    stage=stage,
                    arm_id=arm_id,
                    peak=peak,
                    growth=growth,
                    decision=decision,
                    limit=limit,
                    cleanup=cleanup,
                    errors=errors,
                    byte_quota_status=byte_status,
                    byte_quota_exceeded=byte_exceeded,
                    accounting_status=accounting.accounting_status,
                    symlink_policy_status=accounting.symlink_policy_status,
                    policy_violation_code=accounting.policy_violation_code,
                    failure_domain=(
                        violation["failure_domain"]
                        if violation is not None
                        and violation["category"] == category
                        else None
                    ),
                    failure_code=(
                        violation["failure_code"]
                        if violation is not None
                        and violation["category"] == category
                        else None
                    ),
                    symlink_observations=observations,
                )

        if violation is not None and enforce:
            category = str(violation["category"])
            limit = violation["limit"]
            measured = int(violation["measured"])
            contributor = str(violation["contributor"])
            failure_domain = str(violation["failure_domain"])
            failure_code = str(violation["failure_code"])
            peak = max(self._resource_peaks.get(category, (0, 0))[0], measured)
            byte_status, byte_exceeded, configured_limit = byte_results[
                category
            ]
            self._persist_resource_sample(
                accounting=accounting,
                category=category,
                sample_kind="threshold_crossing",
                stage=stage,
                arm_id=arm_id,
                peak=(peak, self._resource_peaks.get(category, (0, 0))[1]),
                growth=None,
                decision=(
                    "exceeded"
                    if failure_domain
                    in {"byte_quota", "single_file_quota", "log_quota"}
                    else "accounting_error"
                    if failure_domain == "accounting_error"
                    else "policy_violation"
                ),
                limit=(
                    int(limit)
                    if limit is not None
                    else configured_limit
                ),
                cleanup=False,
                errors=errors,
                byte_quota_status=byte_status,
                byte_quota_exceeded=byte_exceeded,
                accounting_status=accounting.accounting_status,
                symlink_policy_status=accounting.symlink_policy_status,
                policy_violation_code=accounting.policy_violation_code,
                failure_domain=failure_domain,
                failure_code=failure_code,
                symlink_observations=observations,
            )
            self._persist_resource_diagnostic(
                accounting,
                category,
                limit,
                peak,
                contributor,
                stage,
                arm_id,
                failure_domain=failure_domain,
                failure_code=failure_code,
            )
            with ComparisonStore(self.database) as store, store.connection:
                store.connection.execute(
                    """
                    UPDATE comparison_suites
                    SET resource_exceeded_category=?,
                        resource_exceeded_limit_bytes=?,
                        resource_peak_bytes=?,
                        resource_largest_contributor=?,
                        resource_enforcement_stage=?,
                        resource_cleanup_status='pending',
                        byte_quota_status=?,
                        byte_quota_exceeded=?,
                        accounting_status=?,
                        symlink_policy_status=?,
                        policy_violation_code=?,
                        failure_domain=?,
                        failure_code=?,
                        resource_policy_label=?
                    WHERE suite_id=?
                    """,
                    (
                        (
                            category
                            if failure_domain
                            in {
                                "byte_quota",
                                "single_file_quota",
                                "log_quota",
                            }
                            else None
                        ),
                        (
                            int(limit)
                            if limit is not None
                            and failure_domain
                            in {
                                "byte_quota",
                                "single_file_quota",
                                "log_quota",
                            }
                            else None
                        ),
                        (
                            peak
                            if failure_domain
                            in {
                                "byte_quota",
                                "single_file_quota",
                                "log_quota",
                            }
                            else None
                        ),
                        (
                            contributor
                            if failure_domain
                            in {
                                "byte_quota",
                                "single_file_quota",
                                "log_quota",
                            }
                            else None
                        ),
                        stage,
                        byte_status,
                        int(byte_exceeded),
                        accounting.accounting_status,
                        accounting.symlink_policy_status,
                        accounting.policy_violation_code,
                        failure_domain,
                        failure_code,
                        (
                            contributor
                            if failure_domain
                            in {"filesystem_policy", "accounting_error"}
                            else None
                        ),
                        self.suite_id,
                    ),
                )
            if failure_domain == "filesystem_policy":
                raise ComparisonFilesystemPolicyError(
                    failure_code, contributor, stage
                )
            if failure_domain == "accounting_error":
                raise ComparisonAccountingError(failure_code, stage)
            assert limit is not None
            raise ComparisonResourceLimitError(
                category,
                int(limit),
                peak,
                contributor,
                stage,
                failure_domain=failure_domain,
                failure_code=failure_code,
            )

    def _persist_resource_sample(
        self,
        *,
        accounting: Any,
        category: str,
        sample_kind: str,
        stage: str,
        arm_id: str | None,
        peak: tuple[int, int],
        growth: dict[str, Any] | None,
        decision: str,
        limit: int | None,
        cleanup: bool,
        errors: list[str],
        byte_quota_status: str,
        byte_quota_exceeded: bool,
        accounting_status: str,
        symlink_policy_status: str,
        policy_violation_code: str | None,
        failure_domain: str | None,
        failure_code: str | None,
        symlink_observations: list[dict[str, Any]],
    ) -> None:
        if self.attempt_id is None:
            return
        totals = accounting.categories[category]
        largest = totals.largest_files[0] if totals.largest_files else None
        cleanup_reduced = (
            int(totals.apparent_bytes < peak[0]) if cleanup else None
        )
        values = (
            _identifier("resource-sample"),
            self.suite_id,
            self.attempt_id,
            arm_id,
            category,
            sample_kind,
            stage,
            utc_now(),
            totals.apparent_bytes,
            totals.allocated_bytes,
            peak[0],
            peak[1],
            totals.file_count,
            largest.relative_path if largest else None,
            largest.apparent_bytes if largest else None,
            json.dumps(
                [value.as_dict() for value in totals.largest_files],
                sort_keys=True,
            ),
            json.dumps(totals.largest_directories, sort_keys=True),
            json.dumps(growth, sort_keys=True) if growth else None,
            decision,
            limit,
            0,
            cleanup_reduced,
            json.dumps(errors, sort_keys=True),
            byte_quota_status,
            int(byte_quota_exceeded),
            accounting_status,
            symlink_policy_status,
            policy_violation_code,
            failure_domain,
            failure_code,
            json.dumps(symlink_observations, sort_keys=True),
        )
        with ComparisonStore(self.database) as store, store.connection:
            store.connection.execute(
                """
                INSERT INTO comparison_resource_samples
                (resource_sample_id, suite_id, attempt_id, arm_id, category,
                 sample_kind, lifecycle_stage, sampled_at,
                 current_apparent_bytes, current_allocated_bytes,
                 peak_apparent_bytes, peak_allocated_bytes, file_count,
                 largest_contributor_relative_path,
                 largest_contributor_bytes, largest_files_json,
                 largest_directories_json, last_growth_event_json,
                 enforcement_decision, configured_limit_bytes,
                 interruption_sent, cleanup_reduced_size,
                 accounting_errors_json, byte_quota_status,
                 byte_quota_exceeded, accounting_status,
                 symlink_policy_status, policy_violation_code,
                 failure_domain, failure_code, symlink_observations_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(suite_id, attempt_id, category, sample_kind)
                DO UPDATE SET
                    arm_id=excluded.arm_id,
                    lifecycle_stage=excluded.lifecycle_stage,
                    sampled_at=excluded.sampled_at,
                    current_apparent_bytes=excluded.current_apparent_bytes,
                    current_allocated_bytes=excluded.current_allocated_bytes,
                    peak_apparent_bytes=MAX(
                        comparison_resource_samples.peak_apparent_bytes,
                        excluded.peak_apparent_bytes
                    ),
                    peak_allocated_bytes=MAX(
                        comparison_resource_samples.peak_allocated_bytes,
                        excluded.peak_allocated_bytes
                    ),
                    file_count=excluded.file_count,
                    largest_contributor_relative_path=
                        excluded.largest_contributor_relative_path,
                    largest_contributor_bytes=
                        excluded.largest_contributor_bytes,
                    largest_files_json=excluded.largest_files_json,
                    largest_directories_json=excluded.largest_directories_json,
                    last_growth_event_json=COALESCE(
                        excluded.last_growth_event_json,
                        comparison_resource_samples.last_growth_event_json
                    ),
                    enforcement_decision=excluded.enforcement_decision,
                    configured_limit_bytes=excluded.configured_limit_bytes,
                    interruption_sent=MAX(
                        comparison_resource_samples.interruption_sent,
                        excluded.interruption_sent
                    ),
                    cleanup_reduced_size=COALESCE(
                        excluded.cleanup_reduced_size,
                        comparison_resource_samples.cleanup_reduced_size
                    ),
                    accounting_errors_json=excluded.accounting_errors_json,
                    byte_quota_status=excluded.byte_quota_status,
                    byte_quota_exceeded=excluded.byte_quota_exceeded,
                    accounting_status=excluded.accounting_status,
                    symlink_policy_status=excluded.symlink_policy_status,
                    policy_violation_code=excluded.policy_violation_code,
                    failure_domain=excluded.failure_domain,
                    failure_code=excluded.failure_code,
                    symlink_observations_json=
                        excluded.symlink_observations_json
                """,
                values,
            )

    def _persist_resource_diagnostic(
        self,
        accounting: Any,
        category: str,
        limit: int | None,
        peak: int,
        contributor: str,
        stage: str,
        arm_id: str | None,
        *,
        failure_domain: str,
        failure_code: str,
    ) -> None:
        if self.attempt_id is None:
            return
        totals = accounting.categories[category]
        payload = {
            "schema_version": "2.0",
            "suite_id": self.suite_id,
            "attempt_id": self.attempt_id,
            "arm_id": arm_id,
            "category": category,
            "configured_limit_bytes": limit,
            "byte_quota_status": (
                "exceeded"
                if failure_domain == "byte_quota"
                else "within_limit"
                if category in {PRESERVED_ARTIFACTS, RUNTIME_SCRATCH}
                else "not_applicable"
            ),
            "byte_quota_exceeded": bool(
                failure_domain == "byte_quota"
            ),
            "accounting_status": accounting.accounting_status,
            "symlink_policy_status": accounting.symlink_policy_status,
            "policy_violation_code": accounting.policy_violation_code,
            "failure_domain": failure_domain,
            "failure_code": failure_code,
            "current_apparent_bytes": totals.apparent_bytes,
            "current_allocated_bytes": totals.allocated_bytes,
            "peak_apparent_bytes": peak,
            "largest_contributor": contributor,
            "largest_files": [
                value.as_dict() for value in totals.largest_files[:8]
            ],
            "largest_directories": totals.largest_directories[:8],
            "symlink_observations": [
                value.as_dict() for value in accounting.symlinks
            ],
            "lifecycle_stage": stage,
            "interruption_sent": False,
            "cleanup_reduced_size": None,
            "sampled_at": utc_now(),
        }
        path = (
            self._execution_root()
            / "resource-diagnostics"
            / f"{self.attempt_id}-{category}.json"
        )
        _write_private_json(path, payload)

    def _mark_resource_interruption(self) -> None:
        if self.attempt_id is None:
            return
        with ComparisonStore(self.database) as store, store.connection:
            store.connection.execute(
                """
                UPDATE comparison_resource_samples SET interruption_sent=1
                WHERE suite_id=? AND attempt_id=?
                  AND sample_kind='threshold_crossing'
                """,
                (self.suite_id, self.attempt_id),
            )
        self._update_resource_diagnostic(interruption_sent=True)

    def _record_resource_terminal_context(
        self, arm_id: str | None
    ) -> None:
        if self.attempt_id is None:
            return
        with ComparisonStore(self.database) as store, store.connection:
            completed = False
            if arm_id is not None:
                row = store.connection.execute(
                    """
                    SELECT lifecycle_status FROM comparison_turns
                    WHERE arm_id=?
                    """,
                    (arm_id,),
                ).fetchone()
                completed = row is not None and row["lifecycle_status"] == "completed"
            blocked = bool(
                store.connection.execute(
                    """
                    SELECT count(*) FROM comparison_arm_transitions
                    WHERE suite_id=? AND lifecycle_state='blocked'
                    """,
                    (self.suite_id,),
                ).fetchone()[0]
            )
            store.connection.execute(
                """
                UPDATE comparison_suites
                SET resource_cleanup_status='sampled_after_cleanup',
                    resource_active_turn_completed=?,
                    resource_later_arms_blocked=?
                WHERE suite_id=?
                """,
                (int(completed), int(blocked), self.suite_id),
            )
        self._update_resource_diagnostic(
            active_turn_completed=completed,
            later_arms_blocked=blocked,
            cleanup_reduced_size=True,
        )

    def _update_resource_diagnostic(
        self,
        *,
        interruption_sent: bool | None = None,
        active_turn_completed: bool | None = None,
        later_arms_blocked: bool | None = None,
        cleanup_reduced_size: bool | None = None,
    ) -> None:
        if self.attempt_id is None:
            return
        with ComparisonStore(self.database) as store:
            categories = [
                str(row["category"])
                for row in store.connection.execute(
                    """
                    SELECT category FROM comparison_resource_samples
                    WHERE suite_id=? AND attempt_id=?
                      AND sample_kind='threshold_crossing'
                    """,
                    (self.suite_id, self.attempt_id),
                )
            ]
        for category in categories:
            path = (
                self._execution_root()
                / "resource-diagnostics"
                / f"{self.attempt_id}-{category}.json"
            )
            if not path.is_file() or path.is_symlink():
                continue
            payload = read_json(path)
            if interruption_sent is not None:
                payload["interruption_sent"] = interruption_sent
            if active_turn_completed is not None:
                payload["active_turn_completed"] = active_turn_completed
            if later_arms_blocked is not None:
                payload["later_arms_blocked"] = later_arms_blocked
            if cleanup_reduced_size is not None:
                with ComparisonStore(self.database) as store:
                    row = store.connection.execute(
                        """
                        SELECT cleanup_reduced_size
                        FROM comparison_resource_samples
                        WHERE suite_id=? AND attempt_id=? AND category=?
                          AND sample_kind='terminal'
                        """,
                        (self.suite_id, self.attempt_id, category),
                    ).fetchone()
                payload["cleanup_reduced_size"] = (
                    bool(row["cleanup_reduced_size"])
                    if row is not None
                    and row["cleanup_reduced_size"] is not None
                    else cleanup_reduced_size
                )
            _write_private_json(path, payload)

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
