from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from random import Random
from typing import Any, Iterable
import json
import math
import sqlite3
import uuid

from .db import connect
from .research.context import (
    CONTEXT_RECOMMENDATION_BASIS,
    DEFAULT_DIRECTOR_CONTEXT_MODE,
    DirectorContextMode,
)
from .state import utc_now

MAX_ARMS = 24
MAX_REPETITIONS = 8
MAX_INFERENCE_STARTS = 64
MAX_TIMEOUT_SECONDS = 900
MAX_CLIENT_TOKENS = 12000
VALID_SUITE_STATES = {
    "draft",
    "prepared",
    "authorized",
    "running",
    "completed",
    "failed",
    "stopped",
}
VALID_ARM_STATES = {
    "planned",
    "preflight",
    "inference_started",
    "completed",
    "schema_invalid",
    "semantic_invalid",
    "timed_out",
    "aborted",
    "failed",
}
TERMINAL_ARM_STATES = VALID_ARM_STATES - {
    "planned",
    "preflight",
    "inference_started",
}


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def canonical_sha256(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


@dataclass(frozen=True, slots=True)
class ModelCatalog:
    models: dict[str, frozenset[str]]

    @classmethod
    def load(cls, path: Path | None = None) -> ModelCatalog:
        payload = json.loads(
            path.read_text(encoding="utf-8")
            if path is not None
            else files("sglab.research")
            .joinpath("assets/comparison_catalog.json")
            .read_text(encoding="utf-8")
        )
        if payload.get("schema_version") != "1.0":
            raise ValueError("unsupported comparison catalog schema")
        models: dict[str, frozenset[str]] = {}
        for model, record in payload.get("models", {}).items():
            if not isinstance(model, str) or not model:
                raise ValueError("catalog model names must be non-empty strings")
            efforts = record.get("reasoning_efforts")
            if not isinstance(efforts, list) or not efforts:
                raise ValueError(f"catalog model {model} has no efforts")
            normalized = frozenset(str(value) for value in efforts)
            if normalized - {"medium", "high", "xhigh"}:
                raise ValueError(f"catalog model {model} has unsupported efforts")
            models[model] = normalized
        if not models:
            raise ValueError("comparison catalog is empty")
        return cls(models=models)

    def validate(self, model: str, effort: str) -> None:
        if model not in self.models:
            raise ValueError(f"unsupported model: {model}")
        if effort not in self.models[model]:
            raise ValueError(f"unsupported model/effort combination: {model}:{effort}")

    def as_dict(self) -> dict[str, list[str]]:
        return {model: sorted(efforts) for model, efforts in sorted(self.models.items())}


@dataclass(frozen=True, slots=True)
class CostResult:
    relative_cost_units: float | None
    api_equivalent_input_cost: float | None
    api_equivalent_output_cost: float | None
    api_equivalent_total_cost: float | None
    currency: str | None


def calculate_cost(
    *,
    input_tokens: int | None,
    cached_input_tokens: int | None,
    output_tokens: int | None,
    server_reported_total_tokens: int | None,
    relative_multiplier: float | None,
    api_input_per_million: float | None,
    api_cached_input_per_million: float | None,
    api_output_per_million: float | None,
    currency: str | None,
) -> CostResult:
    if server_reported_total_tokens is None or relative_multiplier is None:
        relative = None
    else:
        relative = server_reported_total_tokens * relative_multiplier
    input_cost = output_cost = total_cost = None
    if (
        input_tokens is not None
        and output_tokens is not None
        and api_input_per_million is not None
        and api_output_per_million is not None
    ):
        cached = cached_input_tokens or 0
        if not 0 <= cached <= input_tokens:
            raise ValueError("cached input must be a subset of input")
        uncached = input_tokens - cached
        cached_rate = (
            api_cached_input_per_million
            if api_cached_input_per_million is not None
            else api_input_per_million
        )
        input_cost = (
            uncached * api_input_per_million + cached * cached_rate
        ) / 1_000_000
        output_cost = output_tokens * api_output_per_million / 1_000_000
        total_cost = input_cost + output_cost
    return CostResult(relative, input_cost, output_cost, total_cost, currency)


def pareto_frontier(points: Iterable[dict[str, Any]]) -> set[str]:
    usable = [
        point
        for point in points
        if point.get("cost") is not None and point.get("quality") is not None
    ]
    frontier: set[str] = set()
    for point in usable:
        dominated = any(
            other["id"] != point["id"]
            and float(other["cost"]) <= float(point["cost"])
            and float(other["quality"]) >= float(point["quality"])
            and (
                float(other["cost"]) < float(point["cost"])
                or float(other["quality"]) > float(point["quality"])
            )
            for other in usable
        )
        if not dominated:
            frontier.add(str(point["id"]))
    return frontier


def _safe_text(value: Any, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = value.strip()
    if not text or len(text) > maximum:
        raise ValueError(f"{field} must contain 1-{maximum} characters")
    if any(char in text for char in ("\x00", "`", "$(", ";", "|", "&&", "../", "..\\")):
        raise ValueError(f"{field} contains forbidden shell or path syntax")
    return text


def _nullable_text(value: Any, field: str, maximum: int) -> str:
    if value in (None, ""):
        return ""
    return _safe_text(value, field, maximum)


class ComparisonStore:
    def __init__(self, path: Path, *, catalog: ModelCatalog | None = None):
        self.path = path.resolve()
        self.connection = connect(self.path)
        self.catalog = catalog or ModelCatalog.load()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> ComparisonStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def seed_fixture(
        self,
        *,
        fixture_id: str,
        display_name: str,
        fixture_type: str,
        source_artifact_reference: str,
        director_state: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        state_bytes = canonical_bytes(director_state)
        digest = sha256(state_bytes).hexdigest()
        hashes = metadata.get("hashes", {})
        self.connection.execute(
            """
            INSERT OR IGNORE INTO comparison_fixtures
            (fixture_id, display_name, fixture_type, source_artifact_reference,
             fixture_sha256, director_state_schema_version,
             target_statement_id, status_timestamp, serialized_bytes,
             estimated_client_owned_tokens, director_state_json, prompt_sha256,
             output_schema_sha256, applicable_action_space_sha256,
             evidence_registry_sha256, advisory_registry_sha256,
             executable_registry_sha256, base_instructions_sha256,
             developer_instructions_sha256, personality,
             campaign_budget_sha256, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?)
            """,
            (
                fixture_id,
                display_name,
                fixture_type,
                source_artifact_reference,
                digest,
                str(director_state.get("schema_version", "2.0")),
                str(metadata.get("target_statement_id", "erdos_gyarfas")),
                str(metadata.get("status_timestamp", "unknown")),
                len(state_bytes),
                int(metadata.get("estimated_client_owned_tokens", math.ceil(len(state_bytes) / 4))),
                state_bytes.decode("ascii"),
                str(hashes.get("prompt", "")),
                str(hashes.get("output_schema", "")),
                str(hashes.get("applicable_action_space", "")),
                str(hashes.get("evidence_registry", "")),
                str(hashes.get("advisory_registry", "")),
                str(hashes.get("executable_registry", "")),
                str(hashes.get("base_instructions", "")),
                str(hashes.get("developer_instructions", sha256(b"").hexdigest())),
                metadata.get("personality"),
                str(hashes.get("campaign_budget", "")),
                utc_now(),
            ),
        )
        self.connection.commit()

    def create_suite(self, payload: dict[str, Any], *, created_by: str = "web") -> str:
        allowed = {
            "name",
            "description",
            "fixture_id",
            "arms",
            "timeout_seconds",
            "ordering",
            "ordering_seed",
            "measurement_only",
            "execute_decisions",
            "fail_closed",
            "maximum_inference_starts",
            "maximum_total_server_tokens",
            "maximum_client_owned_tokens_per_turn",
            "notes",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"unsupported suite fields: {sorted(unknown)}")
        name = _safe_text(payload.get("name"), "name", 120)
        description = _nullable_text(payload.get("description"), "description", 2000)
        notes = _nullable_text(payload.get("notes"), "notes", 2000)
        fixture_id = _safe_text(payload.get("fixture_id"), "fixture_id", 120)
        fixture = self.connection.execute(
            "SELECT * FROM comparison_fixtures WHERE fixture_id=?", (fixture_id,)
        ).fetchone()
        if fixture is None:
            raise ValueError("unknown fixture_id")
        measurement_only = payload.get("measurement_only", True)
        execute_decisions = payload.get("execute_decisions", False)
        fail_closed = payload.get("fail_closed", True)
        if measurement_only is not True or execute_decisions is not False:
            raise ValueError("this milestone permits measurement_only with no execution")
        if not isinstance(fail_closed, bool):
            raise ValueError("fail_closed must be boolean")
        timeout = payload.get("timeout_seconds", 300)
        if isinstance(timeout, bool) or not isinstance(timeout, int):
            raise ValueError("timeout_seconds must be an integer")
        if not 1 <= timeout <= MAX_TIMEOUT_SECONDS:
            raise ValueError("timeout_seconds must be between 1 and 900")
        ordering = payload.get("ordering", "fixed")
        if ordering not in {"fixed", "randomized"}:
            raise ValueError("ordering must be fixed or randomized")
        seed = payload.get("ordering_seed", 0)
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**63:
            raise ValueError("ordering_seed must be a bounded non-negative integer")
        arms = self._expand_arms(payload.get("arms"))
        maximum = payload.get("maximum_inference_starts", len(arms))
        if isinstance(maximum, bool) or not isinstance(maximum, int):
            raise ValueError("maximum_inference_starts must be an integer")
        if not len(arms) <= maximum <= MAX_INFERENCE_STARTS:
            raise ValueError("maximum inference starts cannot be below planned arms")
        max_total = payload.get("maximum_total_server_tokens")
        if max_total is not None and (
            isinstance(max_total, bool)
            or not isinstance(max_total, int)
            or not 1 <= max_total <= 100_000_000
        ):
            raise ValueError("maximum_total_server_tokens is out of bounds")
        max_client = payload.get(
            "maximum_client_owned_tokens_per_turn", MAX_CLIENT_TOKENS
        )
        if isinstance(max_client, bool) or not isinstance(max_client, int):
            raise ValueError("maximum_client_owned_tokens_per_turn must be integer")
        if not 100 <= max_client <= MAX_CLIENT_TOKENS:
            raise ValueError("maximum client-owned token limit is out of bounds")
        if int(fixture["estimated_client_owned_tokens"]) > max_client:
            raise ValueError("fixture exceeds the client-owned token limit")

        suite_id = _id("comparison")
        randomized = ordering == "randomized"
        order = list(range(len(arms)))
        if randomized:
            Random(seed).shuffle(order)
        effective_by_planned = {planned: effective for effective, planned in enumerate(order)}
        now = utc_now()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO comparison_suites
                (suite_id, name, description, fixture_type, fixture_reference,
                 fixture_sha256, created_at, created_by, status,
                 measurement_only, execute_decisions, randomized_arm_order,
                 ordering_seed, planned_inference_count,
                 maximum_inference_starts, maximum_total_server_tokens,
                 maximum_client_owned_tokens_per_turn, timeout_seconds,
                 fail_closed, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', 1, 0, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?)
                """,
                (
                    suite_id,
                    name,
                    description,
                    str(fixture["fixture_type"]),
                    fixture_id,
                    str(fixture["fixture_sha256"]),
                    now,
                    created_by,
                    int(randomized),
                    seed if randomized else None,
                    len(arms),
                    maximum,
                    max_total,
                    max_client,
                    timeout,
                    int(fail_closed),
                    notes,
                ),
            )
            for planned_order, arm in enumerate(arms):
                profile = self._active_cost_profile(arm["model"], arm["reasoning_effort"])
                profile_values = self._profile_snapshot(profile)
                self.connection.execute(
                    """
                    INSERT INTO comparison_arms
                    (arm_id, suite_id, display_name, model, reasoning_effort,
                     context_mode, repetition_index, planned_order,
                     effective_order, expected_model,
                     expected_reasoning_effort, prompt_sha256,
                     director_state_sha256, output_schema_sha256,
                     evidence_registry_sha256, advisory_registry_sha256,
                     executable_registry_sha256,
                     applicable_action_space_sha256,
                     base_instructions_sha256,
                     developer_instructions_sha256, campaign_budget_sha256,
                     status, cost_profile_id,
                     relative_cost_multiplier_snapshot,
                     api_input_per_million_snapshot,
                     api_cached_input_per_million_snapshot,
                     api_output_per_million_snapshot, currency_snapshot)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _id("arm"),
                        suite_id,
                        arm["display_name"],
                        arm["model"],
                        arm["reasoning_effort"],
                        arm["context_mode"],
                        arm["repetition_index"],
                        planned_order,
                        effective_by_planned[planned_order],
                        arm["model"],
                        arm["reasoning_effort"],
                        fixture["prompt_sha256"],
                        fixture["fixture_sha256"],
                        fixture["output_schema_sha256"],
                        fixture["evidence_registry_sha256"],
                        fixture["advisory_registry_sha256"],
                        fixture["executable_registry_sha256"],
                        fixture["applicable_action_space_sha256"],
                        fixture["base_instructions_sha256"],
                        fixture["developer_instructions_sha256"],
                        fixture["campaign_budget_sha256"],
                        *profile_values,
                    ),
                )
        return suite_id

    def _expand_arms(self, raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list) or not raw:
            raise ValueError("arms must be a non-empty array")
        result: list[dict[str, Any]] = []
        for index, spec in enumerate(raw):
            if not isinstance(spec, dict):
                raise ValueError(f"arms[{index}] must be an object")
            unknown = set(spec) - {
                "display_name",
                "model",
                "reasoning_effort",
                "context_mode",
                "repetitions",
            }
            if unknown:
                raise ValueError(f"arms[{index}] has unsupported fields")
            model = str(spec.get("model", ""))
            effort = str(spec.get("reasoning_effort", ""))
            self.catalog.validate(model, effort)
            try:
                mode = DirectorContextMode(str(spec.get("context_mode", ""))).value
            except ValueError as error:
                raise ValueError(f"unsupported context_mode in arms[{index}]") from error
            repetitions = spec.get("repetitions", 1)
            if (
                isinstance(repetitions, bool)
                or not isinstance(repetitions, int)
                or not 1 <= repetitions <= MAX_REPETITIONS
            ):
                raise ValueError("repetitions must be between 1 and 8")
            display = _safe_text(
                spec.get("display_name", f"{model}:{effort}:{mode}"),
                f"arms[{index}].display_name",
                120,
            )
            for repetition in range(repetitions):
                result.append(
                    {
                        "display_name": display,
                        "model": model,
                        "reasoning_effort": effort,
                        "context_mode": mode,
                        "repetition_index": repetition,
                    }
                )
        if len(result) > MAX_ARMS:
            raise ValueError(f"expanded arm count exceeds {MAX_ARMS}")
        return result

    def _active_cost_profile(self, model: str, effort: str) -> sqlite3.Row | None:
        return self.connection.execute(
            """
            SELECT * FROM model_cost_profiles
            WHERE model=? AND reasoning_effort=? AND enabled=1
            ORDER BY effective_from DESC, created_at DESC LIMIT 1
            """,
            (model, effort),
        ).fetchone()

    @staticmethod
    def _profile_snapshot(profile: sqlite3.Row | None) -> tuple[Any, ...]:
        if profile is None:
            return (None, None, None, None, None, None)
        return (
            profile["profile_id"],
            profile["relative_cost_multiplier"],
            profile["api_input_per_million"],
            profile["api_cached_input_per_million"],
            profile["api_output_per_million"],
            profile["currency"],
        )

    def _plan_payload(self, suite_id: str) -> dict[str, Any]:
        suite = self._suite_row(suite_id)
        arms = [
            dict(row)
            for row in self.connection.execute(
                """
                SELECT display_name, model, reasoning_effort, context_mode,
                       repetition_index, planned_order, effective_order,
                       prompt_sha256, director_state_sha256,
                       output_schema_sha256, evidence_registry_sha256,
                       advisory_registry_sha256, executable_registry_sha256,
                       applicable_action_space_sha256
                FROM comparison_arms WHERE suite_id=?
                ORDER BY effective_order, planned_order
                """,
                (suite_id,),
            )
        ]
        compared_hashes = (
            "prompt_sha256",
            "director_state_sha256",
            "output_schema_sha256",
            "evidence_registry_sha256",
            "advisory_registry_sha256",
            "executable_registry_sha256",
            "applicable_action_space_sha256",
        )
        equality = {
            key: len({str(arm[key]) for arm in arms}) <= 1
            for key in compared_hashes
        }
        return {
            "schema_version": "1.0",
            "suite_id": suite_id,
            "fixture_reference": suite["fixture_reference"],
            "fixture_sha256": suite["fixture_sha256"],
            "arms": arms,
            "fixture_equality": {
                "all_equal": all(equality.values()),
                "fields": equality,
            },
            "planned_inference_count": suite["planned_inference_count"],
            "maximum_inference_starts": suite["maximum_inference_starts"],
            "timeout_seconds": suite["timeout_seconds"],
            "measurement_only": bool(suite["measurement_only"]),
            "execute_decisions": bool(suite["execute_decisions"]),
            "randomized_arm_order": bool(suite["randomized_arm_order"]),
            "ordering_seed": suite["ordering_seed"],
            "maximum_total_server_tokens": suite["maximum_total_server_tokens"],
            "maximum_client_owned_tokens_per_turn": suite[
                "maximum_client_owned_tokens_per_turn"
            ],
        }

    def prepare(self, suite_id: str) -> dict[str, Any]:
        suite = self._suite_row(suite_id)
        self._require_mutable(suite)
        if suite["status"] not in {"draft", "prepared"}:
            raise ValueError("only a draft suite can be prepared")
        plan = self._plan_payload(suite_id)
        fingerprint = canonical_sha256(plan)
        with self.connection:
            self.connection.execute(
                """
                UPDATE comparison_authorizations SET revoked_at=?
                WHERE suite_id=? AND revoked_at IS NULL AND completed_at IS NULL
                """,
                (utc_now(), suite_id),
            )
            self.connection.execute(
                """
                UPDATE comparison_suites
                SET status='prepared', plan_fingerprint=?,
                    authorization_status='unauthorized'
                WHERE suite_id=?
                """,
                (fingerprint, suite_id),
            )
        return {**plan, "plan_fingerprint": fingerprint}

    def authorize(self, suite_id: str, plan_fingerprint: str) -> str:
        suite = self._suite_row(suite_id)
        self._require_mutable(suite)
        if suite["status"] != "prepared":
            raise ValueError("suite must be prepared before authorization")
        if not isinstance(plan_fingerprint, str) or not hmac_equal(
            str(suite["plan_fingerprint"]), plan_fingerprint
        ):
            raise ValueError("authorization fingerprint does not match exact plan")
        arms = list(
            self.connection.execute(
                "SELECT model, reasoning_effort, context_mode FROM comparison_arms "
                "WHERE suite_id=?",
                (suite_id,),
            )
        )
        authorization_id = _id("authorization")
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO comparison_authorizations
                (authorization_id, suite_id, plan_fingerprint,
                 maximum_inference_starts, authorized_models,
                 authorized_efforts, authorized_context_modes, authorized_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    authorization_id,
                    suite_id,
                    plan_fingerprint,
                    suite["maximum_inference_starts"],
                    json.dumps(sorted({str(row["model"]) for row in arms})),
                    json.dumps(
                        sorted({str(row["reasoning_effort"]) for row in arms})
                    ),
                    json.dumps(sorted({str(row["context_mode"]) for row in arms})),
                    utc_now(),
                ),
            )
            self.connection.execute(
                """
                UPDATE comparison_suites
                SET status='authorized', authorization_status='authorized'
                WHERE suite_id=?
                """,
                (suite_id,),
            )
        return authorization_id

    def start(self, suite_id: str, *, auth_available: bool) -> None:
        suite = self._suite_row(suite_id)
        self._require_mutable(suite)
        if suite["status"] != "authorized":
            raise ValueError("suite is not authorized")
        if not auth_available:
            raise ValueError("server-configured Codex auth source is unavailable")
        current = canonical_sha256(self._plan_payload(suite_id))
        if not hmac_equal(current, str(suite["plan_fingerprint"])):
            self.invalidate_authorization(suite_id)
            raise ValueError("plan changed after authorization")
        with self.connection:
            self.connection.execute(
                "UPDATE comparison_suites SET status='running', started_at=? "
                "WHERE suite_id=?",
                (utc_now(), suite_id),
            )

    def record_model_contract(
        self,
        arm_id: str,
        *,
        effective_model: str,
        effective_reasoning_effort: str,
        effective_context_mode: str,
    ) -> bool:
        arm = self.connection.execute(
            "SELECT * FROM comparison_arms WHERE arm_id=?", (arm_id,)
        ).fetchone()
        if arm is None:
            raise KeyError(arm_id)
        self.catalog.validate(effective_model, effective_reasoning_effort)
        try:
            mode = DirectorContextMode(effective_context_mode).value
        except ValueError as error:
            raise ValueError("unsupported effective context mode") from error
        matched = (
            effective_model == arm["expected_model"]
            and effective_reasoning_effort == arm["expected_reasoning_effort"]
            and mode == arm["context_mode"]
        )
        with self.connection:
            self.connection.execute(
                """
                UPDATE comparison_arms
                SET effective_model=?, effective_reasoning_effort=?,
                    effective_context_mode=?, model_contract_matched=?,
                    status=CASE WHEN ? THEN 'preflight' ELSE 'failed' END
                WHERE arm_id=?
                """,
                (
                    effective_model,
                    effective_reasoning_effort,
                    mode,
                    int(matched),
                    int(matched),
                    arm_id,
                ),
            )
        return matched

    def stop(self, suite_id: str) -> None:
        suite = self._suite_row(suite_id)
        self._require_mutable(suite)
        if suite["status"] not in {"authorized", "running"}:
            raise ValueError("suite cannot be stopped in its current state")
        with self.connection:
            self.connection.execute(
                "UPDATE comparison_suites SET status='stopped', completed_at=? "
                "WHERE suite_id=?",
                (utc_now(), suite_id),
            )

    def invalidate_authorization(self, suite_id: str) -> None:
        with self.connection:
            self.connection.execute(
                "UPDATE comparison_authorizations SET revoked_at=? "
                "WHERE suite_id=? AND revoked_at IS NULL AND completed_at IS NULL",
                (utc_now(), suite_id),
            )
            self.connection.execute(
                "UPDATE comparison_suites SET status='draft', "
                "authorization_status='invalidated', plan_fingerprint=NULL "
                "WHERE suite_id=?",
                (suite_id,),
            )

    def record_turn(
        self,
        suite_id: str,
        arm_id: str,
        *,
        lifecycle_status: str,
        usage: dict[str, int | None] | None = None,
        decision: dict[str, Any] | None = None,
        schema_valid: bool | None = None,
        semantic_valid: bool | None = None,
        validation_issues: list[str] | None = None,
        latencies: dict[str, float | None] | None = None,
        automatic_validity: dict[str, bool | None] | None = None,
    ) -> str:
        if lifecycle_status not in VALID_ARM_STATES:
            raise ValueError("invalid arm lifecycle state")
        suite = self._suite_row(suite_id)
        arm = self.connection.execute(
            "SELECT * FROM comparison_arms WHERE arm_id=? AND suite_id=?",
            (arm_id, suite_id),
        ).fetchone()
        if arm is None:
            raise ValueError("arm is not part of suite")
        earlier = list(
            self.connection.execute(
                """
                SELECT a.effective_order, t.lifecycle_status
                FROM comparison_arms a
                LEFT JOIN comparison_turns t ON t.arm_id=a.arm_id
                WHERE a.suite_id=? AND a.effective_order<?
                ORDER BY a.effective_order
                """,
                (suite_id, arm["effective_order"]),
            )
        )
        if any(row["lifecycle_status"] is None for row in earlier):
            raise ValueError("comparison turns must follow the authorized arm order")
        if suite["fail_closed"] and any(
            row["lifecycle_status"] != "completed" for row in earlier
        ):
            raise ValueError("fail-closed suite cannot continue after an arm failure")
        existing = self.connection.execute(
            "SELECT comparison_turn_id FROM comparison_turns WHERE arm_id=?",
            (arm_id,),
        ).fetchone()
        if existing is not None:
            raise ValueError("an arm cannot exceed its authorized turn plan")
        if int(suite["consumed_inference_starts"]) >= int(
            suite["maximum_inference_starts"]
        ):
            raise ValueError("maximum inference starts exhausted")
        normalized_usage = usage or {}
        cached = normalized_usage.get("cached_input_tokens")
        inputs = normalized_usage.get("input_tokens")
        reasoning = normalized_usage.get("reasoning_output_tokens")
        outputs = normalized_usage.get("output_tokens")
        if cached is not None and inputs is not None and cached > inputs:
            raise ValueError("cached input must be a subset of input")
        if reasoning is not None and outputs is not None and reasoning > outputs:
            raise ValueError("reasoning output must be a subset of output")
        maximum_tokens = suite["maximum_total_server_tokens"]
        new_total = normalized_usage.get("server_reported_total_tokens")
        if maximum_tokens is not None and new_total is not None:
            consumed_tokens = int(
                self.connection.execute(
                    """
                    SELECT COALESCE(sum(server_reported_total_tokens), 0)
                    FROM comparison_turns WHERE suite_id=?
                    """,
                    (suite_id,),
                ).fetchone()[0]
            )
            if consumed_tokens + int(new_total) > int(maximum_tokens):
                raise ValueError("maximum total server token budget exceeded")
        issues = validation_issues or []
        validity = automatic_validity or {}
        lat = latencies or {}
        action = None
        algorithm = None
        parameters: dict[str, Any] = {}
        if decision:
            actions = decision.get("actions", [])
            if actions:
                action = actions[0].get("type")
                algorithm = actions[0].get("spec", {}).get("algorithm")
                parameters = actions[0].get("spec", {}).get("parameters", {})
        turn_id = _id("comparison-turn")
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO comparison_turns
                (comparison_turn_id, suite_id, arm_id, lifecycle_status,
                 schema_valid, semantic_valid, evidence_references_valid,
                 action_inside_applicable_space, executable_targets_valid,
                 implemented_parameters_only, budgets_respected,
                 no_false_counterexample_claim, no_tool_request,
                 no_code_request, no_shell_request,
                 no_measurement_execution_request, selected_action,
                 selected_algorithm, selected_parameters_json,
                 raw_decision_json, normalized_decision_json,
                 validation_issues_json, measurement_only, executed,
                 input_tokens, cached_input_tokens, cache_write_input_tokens,
                 output_tokens, reasoning_output_tokens,
                 server_reported_total_tokens, first_item_latency_seconds,
                 final_answer_latency_seconds, total_wall_seconds,
                 retry_count_reaching_inference, tool_call_count,
                 validation_issue_count, cost_profile_id,
                 relative_cost_multiplier_snapshot,
                 api_input_per_million_snapshot,
                 api_cached_input_per_million_snapshot,
                 api_output_per_million_snapshot, currency_snapshot,
                 created_at, completed_at)
                SELECT ?, ?, arm_id, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?,
                       cost_profile_id, relative_cost_multiplier_snapshot,
                       api_input_per_million_snapshot,
                       api_cached_input_per_million_snapshot,
                       api_output_per_million_snapshot, currency_snapshot, ?, ?
                FROM comparison_arms WHERE arm_id=?
                """,
                (
                    turn_id,
                    suite_id,
                    lifecycle_status,
                    _bool(schema_valid),
                    _bool(semantic_valid),
                    _bool(validity.get("evidence_references_valid")),
                    _bool(validity.get("action_inside_applicable_space")),
                    _bool(validity.get("executable_targets_valid")),
                    _bool(validity.get("implemented_parameters_only")),
                    _bool(validity.get("budgets_respected")),
                    _bool(validity.get("no_false_counterexample_claim")),
                    _bool(validity.get("no_tool_request")),
                    _bool(validity.get("no_code_request")),
                    _bool(validity.get("no_shell_request")),
                    _bool(validity.get("no_measurement_execution_request")),
                    action,
                    algorithm,
                    json.dumps(parameters, sort_keys=True),
                    json.dumps(decision, sort_keys=True) if decision else None,
                    json.dumps(decision, sort_keys=True) if decision else None,
                    json.dumps(issues),
                    inputs,
                    cached,
                    normalized_usage.get("cache_write_input_tokens"),
                    outputs,
                    reasoning,
                    normalized_usage.get("server_reported_total_tokens"),
                    lat.get("first_item_latency_seconds"),
                    lat.get("final_answer_latency_seconds"),
                    lat.get("total_wall_seconds"),
                    len(issues),
                    utc_now(),
                    utc_now() if lifecycle_status in TERMINAL_ARM_STATES else None,
                    arm_id,
                ),
            )
            self.connection.execute(
                "UPDATE comparison_arms SET status=? WHERE arm_id=?",
                (lifecycle_status, arm_id),
            )
            self.connection.execute(
                """
                UPDATE comparison_suites
                SET consumed_inference_starts=consumed_inference_starts+1
                WHERE suite_id=?
                """,
                (suite_id,),
            )
            if lifecycle_status != "completed":
                self.connection.execute(
                    """
                    UPDATE comparison_suites
                    SET status='failed', completed_at=?, failure_reason=?
                    WHERE suite_id=?
                    """,
                    (utc_now(), f"arm terminal status: {lifecycle_status}", suite_id),
                )
            else:
                remaining = self.connection.execute(
                    """
                    SELECT count(*) FROM comparison_arms a
                    LEFT JOIN comparison_turns t ON t.arm_id=a.arm_id
                    WHERE a.suite_id=? AND t.comparison_turn_id IS NULL
                    """,
                    (suite_id,),
                ).fetchone()[0]
                if int(remaining) == 0:
                    self.connection.execute(
                        """
                        UPDATE comparison_suites
                        SET status='completed', completed_at=?
                        WHERE suite_id=?
                        """,
                        (utc_now(), suite_id),
                    )
        return turn_id

    def add_manual_rating(self, suite_id: str, payload: dict[str, Any]) -> str:
        turn_id = _safe_text(payload.get("comparison_turn_id"), "comparison_turn_id", 100)
        turn = self.connection.execute(
            """
            SELECT t.*, s.read_only FROM comparison_turns t
            JOIN comparison_suites s ON s.suite_id=t.suite_id
            WHERE t.comparison_turn_id=? AND t.suite_id=?
            """,
            (turn_id, suite_id),
        ).fetchone()
        if turn is None:
            raise ValueError("turn is not part of suite")
        if turn["read_only"]:
            raise ValueError("historical comparison suite is read-only")
        if turn["lifecycle_status"] != "completed" or not (
            turn["schema_valid"] and turn["semantic_valid"]
        ):
            raise ValueError("only valid completed turns can be rated")
        values = []
        for field in ("scientific_usefulness", "clarity", "novelty"):
            value = payload.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 5:
                raise ValueError(f"{field} must be an integer from 1 to 5")
            values.append(value)
        would_execute = payload.get("would_execute")
        if would_execute not in {"yes", "no", "uncertain"}:
            raise ValueError("would_execute must be yes, no or uncertain")
        comment = _nullable_text(payload.get("comment"), "comment", 2000)
        rating_id = _id("rating")
        with self.connection:
            self.connection.execute(
                "INSERT INTO manual_ratings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (rating_id, turn_id, *values, would_execute, comment, utc_now()),
            )
        return rating_id

    def add_pairwise_rating(self, suite_id: str, payload: dict[str, Any]) -> str:
        suite = self._suite_row(suite_id)
        self._require_mutable(suite)
        left = _safe_text(payload.get("left_turn_id"), "left_turn_id", 100)
        right = _safe_text(payload.get("right_turn_id"), "right_turn_id", 100)
        preferred = payload.get("preferred")
        if preferred not in {"left", "equal", "right", "skip"}:
            raise ValueError("invalid pairwise preference")
        if left == right:
            raise ValueError("pairwise turns must differ")
        rows = list(
            self.connection.execute(
                """
                SELECT comparison_turn_id, lifecycle_status, schema_valid
                FROM comparison_turns
                WHERE suite_id=? AND comparison_turn_id IN (?, ?)
                """,
                (suite_id, left, right),
            )
        )
        if len(rows) != 2 or any(
            row["lifecycle_status"] != "completed" or not row["schema_valid"]
            for row in rows
        ):
            raise ValueError("blind comparison requires two completed schema-valid turns")
        seed = payload.get("blind_order_seed", 0)
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("blind_order_seed must be an integer")
        comment = _nullable_text(payload.get("comment"), "comment", 2000)
        rating_id = _id("pairwise")
        with self.connection:
            self.connection.execute(
                "INSERT INTO pairwise_ratings VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (rating_id, suite_id, left, right, preferred, comment, seed, utc_now()),
            )
        return rating_id

    def create_cost_profile(self, payload: dict[str, Any]) -> str:
        allowed = {
            "model",
            "reasoning_effort",
            "display_name",
            "relative_cost_multiplier",
            "api_input_per_million",
            "api_cached_input_per_million",
            "api_output_per_million",
            "currency",
            "source_label",
            "effective_from",
            "enabled",
        }
        if set(payload) - allowed:
            raise ValueError("unsupported cost profile fields")
        model = str(payload.get("model", ""))
        effort = str(payload.get("reasoning_effort", ""))
        self.catalog.validate(model, effort)
        display = _safe_text(payload.get("display_name"), "display_name", 120)
        source = _safe_text(payload.get("source_label"), "source_label", 200)
        multiplier = _nonnegative_number(
            payload.get("relative_cost_multiplier"), "relative_cost_multiplier"
        )
        input_rate = _optional_nonnegative_number(
            payload.get("api_input_per_million"), "api_input_per_million"
        )
        cached_rate = _optional_nonnegative_number(
            payload.get("api_cached_input_per_million"),
            "api_cached_input_per_million",
        )
        output_rate = _optional_nonnegative_number(
            payload.get("api_output_per_million"), "api_output_per_million"
        )
        currency = payload.get("currency")
        if any(value is not None for value in (input_rate, cached_rate, output_rate)):
            if input_rate is None or output_rate is None:
                raise ValueError("API estimate requires input and output rates")
            currency = _safe_text(currency, "currency", 12)
        elif currency not in (None, ""):
            raise ValueError("currency requires API rates")
        effective = _safe_text(payload.get("effective_from"), "effective_from", 40)
        enabled = payload.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be boolean")
        profile_id = _id("cost-profile")
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO model_cost_profiles VALUES
                (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    profile_id,
                    model,
                    effort,
                    display,
                    multiplier,
                    input_rate,
                    cached_rate,
                    output_rate,
                    currency or None,
                    source,
                    effective,
                    int(enabled),
                    utc_now(),
                ),
            )
        return profile_id

    def suite_detail(self, suite_id: str, *, blind: bool = False) -> dict[str, Any]:
        suite = dict(self._suite_row(suite_id))
        arms = [
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM comparison_arms WHERE suite_id=? "
                "ORDER BY effective_order, planned_order",
                (suite_id,),
            )
        ]
        turns = [
            dict(row)
            for row in self.connection.execute(
                """
                SELECT t.*, a.display_name, a.model, a.reasoning_effort,
                       a.context_mode
                FROM comparison_turns t
                JOIN comparison_arms a ON a.arm_id=t.arm_id
                WHERE t.suite_id=? ORDER BY a.effective_order, a.planned_order
                """,
                (suite_id,),
            )
        ]
        ratings = [
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM manual_ratings WHERE comparison_turn_id IN "
                "(SELECT comparison_turn_id FROM comparison_turns WHERE suite_id=?)",
                (suite_id,),
            )
        ]
        pairwise = [
            dict(row)
            for row in self.connection.execute(
                "SELECT * FROM pairwise_ratings WHERE suite_id=? "
                "ORDER BY created_at",
                (suite_id,),
            )
        ]
        for turn in turns:
            cost = calculate_cost(
                input_tokens=turn["input_tokens"],
                cached_input_tokens=turn["cached_input_tokens"],
                output_tokens=turn["output_tokens"],
                server_reported_total_tokens=turn["server_reported_total_tokens"],
                relative_multiplier=turn["relative_cost_multiplier_snapshot"],
                api_input_per_million=turn["api_input_per_million_snapshot"],
                api_cached_input_per_million=turn[
                    "api_cached_input_per_million_snapshot"
                ],
                api_output_per_million=turn["api_output_per_million_snapshot"],
                currency=turn["currency_snapshot"],
            )
            turn["cost"] = {
                "relative_cost_units": cost.relative_cost_units,
                "api_equivalent_input_cost": cost.api_equivalent_input_cost,
                "api_equivalent_output_cost": cost.api_equivalent_output_cost,
                "api_equivalent_total_cost": cost.api_equivalent_total_cost,
                "currency": cost.currency,
                "profile_id": turn["cost_profile_id"],
            }
        metrics = _comparison_metrics(turns, ratings, pairwise)
        blind_order_seed = None
        if blind:
            blind_order_seed = (
                int(suite["ordering_seed"])
                if suite["ordering_seed"] is not None
                else int(sha256(str(suite["suite_id"]).encode()).hexdigest()[:12], 16)
            )
            Random(blind_order_seed).shuffle(turns)
            for turn in turns:
                for key in (
                    "model",
                    "reasoning_effort",
                    "context_mode",
                    "input_tokens",
                    "cached_input_tokens",
                    "cache_write_input_tokens",
                    "output_tokens",
                    "reasoning_output_tokens",
                    "server_reported_total_tokens",
                    "first_item_latency_seconds",
                    "final_answer_latency_seconds",
                    "total_wall_seconds",
                    "cost",
                ):
                    turn.pop(key, None)
            metrics = {
                "valid_response_rate": metrics["valid_response_rate"],
                "quality_cost_points": [],
                "pairwise": {},
            }
        return {
            "suite": suite,
            "arms": arms,
            "turns": turns,
            "ratings": ratings,
            "pairwise_ratings": pairwise,
            "comparison_metrics": metrics,
            "blind_order_seed": blind_order_seed,
        }

    def list_suites(self, filters: dict[str, str] | None = None) -> list[dict[str, Any]]:
        records = []
        for row in self.connection.execute(
            "SELECT * FROM comparison_suites ORDER BY created_at DESC LIMIT 200"
        ):
            suite = dict(row)
            arms = list(
                self.connection.execute(
                    "SELECT model, reasoning_effort, context_mode FROM comparison_arms "
                    "WHERE suite_id=?",
                    (suite["suite_id"],),
                )
            )
            turns = list(
                self.connection.execute(
                    "SELECT * FROM comparison_turns WHERE suite_id=?",
                    (suite["suite_id"],),
                )
            )
            suite.update(
                {
                    "arm_count": len(arms),
                    "models": sorted({str(value["model"]) for value in arms}),
                    "efforts": sorted(
                        {str(value["reasoning_effort"]) for value in arms}
                    ),
                    "context_modes": sorted(
                        {str(value["context_mode"]) for value in arms}
                    ),
                    "completion_count": sum(
                        turn["lifecycle_status"] == "completed" for turn in turns
                    ),
                    "timeout_count": sum(
                        turn["lifecycle_status"] == "timed_out" for turn in turns
                    ),
                    "invalid_decision_count": sum(
                        turn["schema_valid"] == 0 or turn["semantic_valid"] == 0
                        for turn in turns
                    ),
                    "total_server_tokens": sum(
                        int(turn["server_reported_total_tokens"] or 0)
                        for turn in turns
                    ),
                    "relative_cost_units": sum(
                        (
                            int(turn["server_reported_total_tokens"])
                            * float(turn["relative_cost_multiplier_snapshot"])
                        )
                        if turn["server_reported_total_tokens"] is not None
                        and turn["relative_cost_multiplier_snapshot"] is not None
                        else 0.0
                        for turn in turns
                    ),
                }
            )
            if _matches_filters(suite, filters or {}):
                records.append(suite)
        return records

    def _suite_row(self, suite_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM comparison_suites WHERE suite_id=?", (suite_id,)
        ).fetchone()
        if row is None:
            raise KeyError(suite_id)
        return row

    @staticmethod
    def _require_mutable(suite: sqlite3.Row) -> None:
        if suite["read_only"]:
            raise ValueError("historical comparison suite is read-only")


def import_m6_context_report(database: Path, report_path: Path) -> str:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    runtime = report["runtime"]
    if not runtime.get("ok"):
        raise ValueError("M6 report is not a successful comparison")
    with ComparisonStore(database) as store:
        existing = store.connection.execute(
            "SELECT suite_id FROM comparison_suites "
            "WHERE fixture_reference='m6-preserved-a4' AND read_only=1"
        ).fetchone()
        if existing is not None:
            return str(existing[0])
        prep = runtime["deterministic_preparation"]
        budgets = {record["source_state"]: record for record in prep["context_budgets"]}
        for source in ("A1", "A4"):
            record = budgets[source]
            state_descriptor = {
                "schema_version": "2.0",
                "source_snapshot_id": record["snapshot_id"],
                "preserved_director_state_sha256": record["director_state_sha256"],
                "immutable_source_report_sha256": sha256(
                    report_path.read_bytes()
                ).hexdigest(),
            }
            store.seed_fixture(
                fixture_id=f"m6-preserved-{source.lower()}",
                display_name=f"M6 preserved {source}",
                fixture_type="preserved_director_state",
                source_artifact_reference=report_path.name,
                director_state=state_descriptor,
                metadata={
                    "status_timestamp": report["date"],
                    "estimated_client_owned_tokens": record[
                        "client_owned_estimated_tokens"
                    ],
                    "hashes": {
                        "prompt": record["prompt_sha256"],
                        "output_schema": record["output_schema_sha256"],
                        "applicable_action_space": record[
                            "allowed_action_space_sha256"
                        ],
                        "evidence_registry": record["evidence_registry_sha256"],
                        "advisory_registry": record[
                            "advisory_target_registry_sha256"
                        ],
                        "executable_registry": record[
                            "executable_target_registry_sha256"
                        ],
                        "base_instructions": canonical_sha256(
                            {"bytes": record["base_instructions_bytes"]}
                        ),
                        "campaign_budget": record["campaign_budget_sha256"],
                    },
                },
            )
        fixture = store.connection.execute(
            "SELECT * FROM comparison_fixtures WHERE fixture_id='m6-preserved-a4'"
        ).fetchone()
        assert fixture is not None
        historical_profile_id = "historical-m6-luna-xhigh-relative-1"
        with store.connection:
            store.connection.execute(
                """
                INSERT OR IGNORE INTO model_cost_profiles
                (profile_id, model, reasoning_effort, display_name,
                 relative_cost_multiplier, source_label, effective_from,
                 enabled, created_at)
                VALUES (?, 'gpt-5.6-luna', 'xhigh',
                        'M6 Luna xhigh relative baseline', 1.0,
                        'M6 historical display baseline', ?, 1, ?)
                """,
                (historical_profile_id, report["date"], utc_now()),
            )
        suite_id = "historical-m6-context-screen"
        now = utc_now()
        with store.connection:
            store.connection.execute(
                """
                INSERT INTO comparison_suites
                (suite_id, name, description, fixture_type, fixture_reference,
                 fixture_sha256, created_at, created_by, status,
                 measurement_only, execute_decisions, randomized_arm_order,
                 planned_inference_count, maximum_inference_starts,
                 timeout_seconds, fail_closed, plan_fingerprint,
                 authorization_status, consumed_inference_starts, read_only,
                 runtime_executed_elsewhere, recommendation_status,
                 recommendation_basis, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'deterministic-import',
                        'completed', 1, 0, 0, 3, 3, 300, 1, ?, 'historical',
                        0, 1, 1, 'stateless_turns', ?, ?)
                """,
                (
                    suite_id,
                    "M6 reduced context screen",
                    "Imported read-only S2/P1/P2 controlled context comparison.",
                    fixture["fixture_type"],
                    fixture["fixture_id"],
                    fixture["fixture_sha256"],
                    now,
                    prep["plan_fingerprint"],
                    CONTEXT_RECOMMENDATION_BASIS,
                    now,
                ),
            )
        slot_records: list[tuple[str, dict[str, Any]]] = []
        for mode, arm in runtime["arms"].items():
            for turn in arm["turns"]:
                slot_records.append((mode, turn))
        slot_records.sort(key=lambda item: {"S2": 0, "P1": 1, "P2": 2}[item[1]["slot"]])
        for order, (mode, turn) in enumerate(slot_records):
            arm_id = f"historical-{turn['slot'].lower()}"
            model_contract = turn["model_contract"]
            with store.connection:
                store.connection.execute(
                    """
                    INSERT INTO comparison_arms
                    (arm_id, suite_id, display_name, model, reasoning_effort,
                     context_mode, repetition_index, planned_order,
                     effective_order, expected_model,
                     expected_reasoning_effort, effective_model,
                     effective_reasoning_effort, effective_context_mode,
                     model_contract_matched, prompt_sha256,
                     director_state_sha256, output_schema_sha256,
                     evidence_registry_sha256, advisory_registry_sha256,
                     executable_registry_sha256,
                     applicable_action_space_sha256,
                     base_instructions_sha256,
                     developer_instructions_sha256, campaign_budget_sha256,
                     status)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?,
                            ?, ?, ?, ?, ?, '', '', '', 'completed')
                    """,
                    (
                        arm_id,
                        suite_id,
                        turn["slot"],
                        model_contract["effective_model"],
                        model_contract["effective_reasoning_effort"],
                        mode,
                        order,
                        order,
                        model_contract["expected_model"],
                        model_contract["expected_reasoning_effort"],
                        model_contract["effective_model"],
                        model_contract["effective_reasoning_effort"],
                        mode,
                        turn["prompt_sha256"],
                        turn["director_state_sha256"],
                        turn["output_schema_sha256"],
                        turn["evidence_registry_sha256"],
                        turn["advisory_target_registry_sha256"],
                        turn["executable_target_registry_sha256"],
                        turn["applicable_action_space_sha256"],
                    ),
                )
                store.connection.execute(
                    """
                    UPDATE comparison_arms
                    SET cost_profile_id=?,
                        relative_cost_multiplier_snapshot=1.0
                    WHERE arm_id=?
                    """,
                    (historical_profile_id, arm_id),
                )
            usage = turn["usage"]
            store.record_turn(
                suite_id,
                arm_id,
                lifecycle_status="completed",
                usage=usage,
                decision=turn["normalized_decision"],
                schema_valid=bool(turn["schema_validity"]),
                semantic_valid=bool(turn["local_semantic_validity"]),
                validation_issues=list(turn["validation_issues"]),
                latencies={
                    "first_item_latency_seconds": turn["first_item_latency_seconds"],
                    "final_answer_latency_seconds": turn[
                        "final_answer_latency_seconds"
                    ],
                    "total_wall_seconds": turn["latency_seconds"],
                },
                automatic_validity={
                    key: bool(value)
                    for key, value in turn["semantic_rubric"].items()
                    if isinstance(value, bool)
                },
            )
        with store.connection:
            store.connection.execute(
                """
                UPDATE comparison_suites
                SET status='completed', consumed_inference_starts=3,
                    completed_at=?
                WHERE suite_id=?
                """,
                (now, suite_id),
            )
        return suite_id


def run_replay_dry_run(database: Path) -> dict[str, Any]:
    """Exercise comparison persistence without auth, inference, or search."""

    with ComparisonStore(database) as store:
        digest = "d" * 64
        store.seed_fixture(
            fixture_id="replay-dry-run-fixture",
            display_name="Replay dry-run fixture",
            fixture_type="custom_director_state_json",
            source_artifact_reference="deterministic-inline",
            director_state={
                "schema_version": "2.0",
                "source_snapshot_id": "replay-dry-run",
                "measurement_only": True,
            },
            metadata={
                "status_timestamp": utc_now(),
                "estimated_client_owned_tokens": 64,
                "hashes": {
                    "prompt": digest,
                    "output_schema": digest,
                    "applicable_action_space": digest,
                    "evidence_registry": digest,
                    "advisory_registry": digest,
                    "executable_registry": digest,
                    "base_instructions": digest,
                    "campaign_budget": digest,
                },
            },
        )
        profile_id = store.create_cost_profile(
            {
                "model": "gpt-5.6-luna",
                "reasoning_effort": "xhigh",
                "display_name": "Replay relative profile",
                "relative_cost_multiplier": 1.0,
                "api_input_per_million": 1.0,
                "api_cached_input_per_million": 0.5,
                "api_output_per_million": 2.0,
                "currency": "USD",
                "source_label": "deterministic test values, not price claims",
                "effective_from": utc_now(),
                "enabled": True,
            }
        )
        suite_id = store.create_suite(
            {
                "name": "Deterministic replay comparison",
                "description": "Three simulated arms with no model and no execution.",
                "fixture_id": "replay-dry-run-fixture",
                "arms": [
                    {
                        "display_name": "Replay A",
                        "model": "gpt-5.6-luna",
                        "reasoning_effort": "xhigh",
                        "context_mode": "stateless_turns",
                    },
                    {
                        "display_name": "Replay B",
                        "model": "gpt-5.6-luna",
                        "reasoning_effort": "xhigh",
                        "context_mode": "persistent_thread",
                    },
                    {
                        "display_name": "Replay failure",
                        "model": "gpt-5.6-sol",
                        "reasoning_effort": "high",
                        "context_mode": "stateless_turns",
                    },
                ],
                "timeout_seconds": 30,
                "ordering": "randomized",
                "ordering_seed": 20260725,
                "measurement_only": True,
                "execute_decisions": False,
                "fail_closed": True,
                "maximum_inference_starts": 3,
            },
            created_by="deterministic-replay",
        )
        plan = store.prepare(suite_id)
        no_start_without_authorization = False
        try:
            store.start(suite_id, auth_available=False)
        except ValueError:
            no_start_without_authorization = True
        authorization_id = store.authorize(suite_id, plan["plan_fingerprint"])
        arms = list(
            store.connection.execute(
                "SELECT arm_id FROM comparison_arms WHERE suite_id=? "
                "ORDER BY effective_order",
                (suite_id,),
            )
        )
        valid_decision = {
            "schema_version": "1.0",
            "actions": [{"type": "request_diagnostic", "spec": {}}],
        }
        validity = {
            "evidence_references_valid": True,
            "action_inside_applicable_space": True,
            "executable_targets_valid": True,
            "implemented_parameters_only": True,
            "budgets_respected": True,
            "no_false_counterexample_claim": True,
            "no_tool_request": True,
            "no_code_request": True,
            "no_shell_request": True,
            "no_measurement_execution_request": True,
        }
        turn_ids = []
        for row, total, status in zip(
            arms,
            (120, 180, None),
            ("completed", "completed", "failed"),
            strict=True,
        ):
            usage = (
                {
                    "input_tokens": total - 20,
                    "cached_input_tokens": 10,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 20,
                    "reasoning_output_tokens": 5,
                    "server_reported_total_tokens": total,
                }
                if total is not None
                else None
            )
            turn_ids.append(
                store.record_turn(
                    suite_id,
                    str(row["arm_id"]),
                    lifecycle_status=status,
                    usage=usage,
                    decision=valid_decision if status == "completed" else None,
                    schema_valid=True if status == "completed" else None,
                    semantic_valid=True if status == "completed" else None,
                    automatic_validity=validity if status == "completed" else None,
                )
            )
        store.add_manual_rating(
            suite_id,
            {
                "comparison_turn_id": turn_ids[0],
                "scientific_usefulness": 4,
                "clarity": 4,
                "novelty": 3,
                "would_execute": "uncertain",
                "comment": "deterministic replay rating",
            },
        )
        store.add_manual_rating(
            suite_id,
            {
                "comparison_turn_id": turn_ids[1],
                "scientific_usefulness": 3,
                "clarity": 4,
                "novelty": 3,
                "would_execute": "no",
                "comment": "",
            },
        )
        store.add_pairwise_rating(
            suite_id,
            {
                "left_turn_id": turn_ids[0],
                "right_turn_id": turn_ids[1],
                "preferred": "left",
                "comment": "blind deterministic preference",
                "blind_order_seed": 99,
            },
        )
        with store.connection:
            store.connection.execute(
                "UPDATE comparison_suites SET status='completed', completed_at=? "
                "WHERE suite_id=?",
                (utc_now(), suite_id),
            )
            store.connection.execute(
                "UPDATE comparison_authorizations SET completed_at=? "
                "WHERE authorization_id=?",
                (utc_now(), authorization_id),
            )
        detail = store.suite_detail(suite_id)
        return {
            "ok": True,
            "suite_id": suite_id,
            "arm_count": len(arms),
            "maximum_inference_starts": 3,
            "simulated_turn_count": len(turn_ids),
            "model_inferences": 0,
            "auth_access": 0,
            "search_batches": 0,
            "lanes": 0,
            "decision_execution": 0,
            "no_start_without_authorization": no_start_without_authorization,
            "measurement_only": all(
                bool(turn["measurement_only"]) and not bool(turn["executed"])
                for turn in detail["turns"]
            ),
            "missing_usage_is_null": detail["turns"][2][
                "server_reported_total_tokens"
            ]
            is None,
            "cost_profile_id": profile_id,
            "sqlite_integrity_check": store.connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0],
        }


def hmac_equal(left: str, right: str) -> bool:
    if len(left) != len(right):
        return False
    difference = 0
    for a, b in zip(left.encode("utf-8"), right.encode("utf-8"), strict=True):
        difference |= a ^ b
    return difference == 0


def _bool(value: bool | None) -> int | None:
    return None if value is None else int(value)


def _nonnegative_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return normalized


def _optional_nonnegative_number(value: Any, field: str) -> float | None:
    return None if value in (None, "") else _nonnegative_number(value, field)


def _matches_filters(suite: dict[str, Any], filters: dict[str, str]) -> bool:
    for field, collection in (
        ("model", "models"),
        ("effort", "efforts"),
        ("context_mode", "context_modes"),
    ):
        if filters.get(field) and filters[field] not in suite[collection]:
            return False
    if filters.get("fixture") and filters["fixture"] != suite["fixture_reference"]:
        return False
    if filters.get("status") and filters["status"] != suite["status"]:
        return False
    return True


def _comparison_metrics(
    turns: list[dict[str, Any]],
    ratings: list[dict[str, Any]],
    pairwise: list[dict[str, Any]],
) -> dict[str, Any]:
    ratings_by_turn: dict[str, list[dict[str, Any]]] = {}
    for rating in ratings:
        ratings_by_turn.setdefault(str(rating["comparison_turn_id"]), []).append(rating)
    points = []
    for turn in turns:
        turn_id = str(turn["comparison_turn_id"])
        turn_ratings = ratings_by_turn.get(turn_id, [])
        quality = (
            sum(float(value["scientific_usefulness"]) for value in turn_ratings)
            / len(turn_ratings)
            if turn_ratings
            else None
        )
        cost = turn.get("cost", {}).get("relative_cost_units")
        points.append(
            {
                "id": turn_id,
                "label": (
                    f"{turn.get('model')}:{turn.get('reasoning_effort')}:"
                    f"{turn.get('context_mode')}"
                ),
                "cost": cost,
                "tokens": turn.get("server_reported_total_tokens"),
                "quality": quality,
            }
        )
    frontier = pareto_frontier(points)
    for point in points:
        point["pareto_frontier"] = point["id"] in frontier
    outcomes: dict[str, dict[str, int]] = {
        str(turn["comparison_turn_id"]): {"wins": 0, "draws": 0, "losses": 0}
        for turn in turns
    }
    for rating in pairwise:
        left, right = str(rating["left_turn_id"]), str(rating["right_turn_id"])
        if rating["preferred"] == "left":
            outcomes[left]["wins"] += 1
            outcomes[right]["losses"] += 1
        elif rating["preferred"] == "right":
            outcomes[right]["wins"] += 1
            outcomes[left]["losses"] += 1
        elif rating["preferred"] == "equal":
            outcomes[left]["draws"] += 1
            outcomes[right]["draws"] += 1
    valid_count = sum(
        turn.get("lifecycle_status") == "completed"
        and bool(turn.get("schema_valid"))
        and bool(turn.get("semantic_valid"))
        for turn in turns
    )
    total_tokens = sum(
        int(turn["server_reported_total_tokens"] or 0) for turn in turns
    )
    return {
        "valid_response_rate": valid_count / len(turns) if turns else None,
        "mean_manual_usefulness": (
            sum(float(rating["scientific_usefulness"]) for rating in ratings)
            / len(ratings)
            if ratings
            else None
        ),
        "token_cost_per_valid_response": (
            total_tokens / valid_count if valid_count else None
        ),
        "quality_cost_points": points,
        "pairwise": outcomes,
    }


def default_context_summary() -> dict[str, str]:
    return {
        "default_context_mode": DEFAULT_DIRECTOR_CONTEXT_MODE.value,
        "recommendation_basis": CONTEXT_RECOMMENDATION_BASIS,
    }
