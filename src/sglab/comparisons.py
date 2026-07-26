from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from random import Random
from typing import Any, Iterable
import json
import math
import re
import shutil
import sqlite3
import tempfile
import uuid

from .db import connect
from .research.context import (
    CONTEXT_RECOMMENDATION_BASIS,
    DEFAULT_DIRECTOR_CONTEXT_MODE,
    DirectorContextMode,
    evidence_registry_ids,
)
from .state import utc_now

MAX_ARMS = 24
MAX_REPETITIONS = 8
MAX_INFERENCE_STARTS = 64
MAX_TIMEOUT_SECONDS = 900
MAX_CLIENT_TOKENS = 12000
DEFAULT_WORKER_WALL_SECONDS = 7200
MAX_WORKER_WALL_SECONDS = 86400
INDEPENDENT_INVALID_CONTINUE_POLICY = (
    "independent_invalid_continue_v1"
)
MODEL_INVALID_ARM_STATES = frozenset(
    {"schema_invalid", "semantic_invalid"}
)
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
    "auth_prepared",
    "server_started",
    "thread_ready",
    "inference_reserved",
    "inference_started",
    "completed",
    "schema_invalid",
    "semantic_invalid",
    "timed_out",
    "aborted",
    "failed",
    "blocked",
    "stopped",
}
TERMINAL_ARM_STATES = VALID_ARM_STATES - {
    "planned",
    "preflight",
    "auth_prepared",
    "server_started",
    "thread_ready",
    "inference_reserved",
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


def _optional_canonical_json(value: Any) -> str | None:
    return canonical_bytes(value).decode("ascii") if value is not None else None


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
    if any(char in text for char in ("\x00", "`", "$(", "|", "&&", "../", "..\\")):
        raise ValueError(f"{field} contains forbidden shell or path syntax")
    return text


def _nullable_text(value: Any, field: str, maximum: int) -> str:
    if value in (None, ""):
        return ""
    return _safe_text(value, field, maximum)


def _bounded_integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return value


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
        materials = metadata.get("materials", {})
        if not isinstance(materials, dict):
            raise ValueError("fixture materials must be an object")
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
             campaign_budget_sha256, created_at, prompt_text,
             output_schema_json, applicable_action_space_json,
             evidence_registry_json, advisory_registry_json,
             executable_registry_json, base_instructions_text,
             developer_instructions_text, campaign_budget_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                materials.get("prompt"),
                _optional_canonical_json(materials.get("output_schema")),
                _optional_canonical_json(materials.get("applicable_action_space")),
                _optional_canonical_json(materials.get("evidence_registry")),
                _optional_canonical_json(materials.get("advisory_registry")),
                _optional_canonical_json(materials.get("executable_registry")),
                materials.get("base_instructions"),
                materials.get("developer_instructions", ""),
                _optional_canonical_json(materials.get("campaign_budget")),
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
            "maximum_stdout_bytes",
            "maximum_stderr_bytes",
            "maximum_wire_log_bytes",
            "maximum_artifact_directory_bytes",
            "max_preserved_artifact_bytes",
            "max_runtime_scratch_bytes",
            "max_single_preserved_artifact_bytes",
            "max_single_runtime_file_bytes",
            "maximum_worker_wall_seconds",
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
        legacy_artifact_limit = payload.get("maximum_artifact_directory_bytes")
        preserved_limit = payload.get("max_preserved_artifact_bytes")
        if legacy_artifact_limit is not None and preserved_limit is not None:
            if legacy_artifact_limit != preserved_limit:
                raise ValueError(
                    "deprecated maximum_artifact_directory_bytes must equal "
                    "max_preserved_artifact_bytes"
                )
        if preserved_limit is None:
            preserved_limit = (
                legacy_artifact_limit
                if legacy_artifact_limit is not None
                else 64 * 1024 * 1024
            )
        resource_limits = {
            "maximum_stdout_bytes": _bounded_integer(
                payload.get("maximum_stdout_bytes", 1024 * 1024),
                "maximum_stdout_bytes",
                4096,
                64 * 1024 * 1024,
            ),
            "maximum_stderr_bytes": _bounded_integer(
                payload.get("maximum_stderr_bytes", 256 * 1024),
                "maximum_stderr_bytes",
                4096,
                16 * 1024 * 1024,
            ),
            "maximum_wire_log_bytes": _bounded_integer(
                payload.get("maximum_wire_log_bytes", 8 * 1024 * 1024),
                "maximum_wire_log_bytes",
                4096,
                128 * 1024 * 1024,
            ),
            "max_preserved_artifact_bytes": _bounded_integer(
                preserved_limit,
                "max_preserved_artifact_bytes",
                1024 * 1024,
                1024 * 1024 * 1024,
            ),
            "max_runtime_scratch_bytes": _bounded_integer(
                payload.get("max_runtime_scratch_bytes", 512 * 1024 * 1024),
                "max_runtime_scratch_bytes",
                1024 * 1024,
                4 * 1024 * 1024 * 1024,
            ),
            "max_single_preserved_artifact_bytes": _bounded_integer(
                payload.get(
                    "max_single_preserved_artifact_bytes", 32 * 1024 * 1024
                ),
                "max_single_preserved_artifact_bytes",
                1024,
                1024 * 1024 * 1024,
            ),
            "max_single_runtime_file_bytes": _bounded_integer(
                payload.get(
                    "max_single_runtime_file_bytes", 256 * 1024 * 1024
                ),
                "max_single_runtime_file_bytes",
                1024,
                4 * 1024 * 1024 * 1024,
            ),
            "maximum_worker_wall_seconds": _bounded_integer(
                payload.get(
                    "maximum_worker_wall_seconds", DEFAULT_WORKER_WALL_SECONDS
                ),
                "maximum_worker_wall_seconds",
                1,
                MAX_WORKER_WALL_SECONDS,
            ),
        }
        if (
            resource_limits["max_single_preserved_artifact_bytes"]
            > resource_limits["max_preserved_artifact_bytes"]
        ):
            raise ValueError(
                "single preserved artifact limit exceeds preserved total"
            )
        if (
            resource_limits["max_single_runtime_file_bytes"]
            > resource_limits["max_runtime_scratch_bytes"]
        ):
            raise ValueError("single runtime file limit exceeds scratch total")

        suite_id = _id("comparison")
        randomized = ordering == "randomized"
        grouped_order: dict[str, list[int]] = {}
        group_sequence: list[str] = []
        for index, arm in enumerate(arms):
            key = str(arm["conversation_group_id"] or f"independent-{index}")
            if key not in grouped_order:
                grouped_order[key] = []
                group_sequence.append(key)
            grouped_order[key].append(index)
        if randomized:
            Random(seed).shuffle(group_sequence)
        order = [
            index
            for key in group_sequence
            for index in grouped_order[key]
        ]
        effective_by_planned = {planned: effective for effective, planned in enumerate(order)}
        now = utc_now()
        arm_ids = [_id("arm") for _ in arms]
        group_previous: dict[str, str] = {}
        arm_execution: list[dict[str, Any]] = []
        for index, arm in enumerate(arms):
            arm_id = arm_ids[index]
            group = arm["conversation_group_id"] or arm_id
            previous = group_previous.get(group)
            resume = bool(arm["resume_prior_thread"])
            if resume and arm["context_mode"] != "persistent_thread":
                raise ValueError("only persistent_thread arms may resume a thread")
            if resume and previous is None:
                raise ValueError("a resumed conversation requires an earlier group arm")
            if not resume and previous is not None:
                raise ValueError(
                    "later arms in a conversation group must explicitly resume"
                )
            arm_execution.append(
                {
                    "arm_id": arm_id,
                    "conversation_group_id": group,
                    "sequence_index": sum(
                        value["conversation_group_id"] == group
                        for value in arm_execution
                    ),
                    "depends_on_arm_id": previous if resume else None,
                    "requires_prior_success": int(resume),
                    "fresh_thread": int(not resume),
                    "resume_prior_thread": int(resume),
                }
            )
            group_previous[group] = arm_id
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
                 fail_closed, notes, maximum_stdout_bytes,
                 maximum_stderr_bytes, maximum_wire_log_bytes,
                 maximum_artifact_directory_bytes,
                 maximum_worker_wall_seconds, resource_accounting_version,
                 max_preserved_artifact_bytes, max_runtime_scratch_bytes,
                 max_single_preserved_artifact_bytes,
                 max_single_runtime_file_bytes, arm_failure_policy)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', 1, 0, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, 2, ?, ?, ?, ?, ?)
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
                    resource_limits["maximum_stdout_bytes"],
                    resource_limits["maximum_stderr_bytes"],
                    resource_limits["maximum_wire_log_bytes"],
                    resource_limits["max_preserved_artifact_bytes"],
                    resource_limits["maximum_worker_wall_seconds"],
                    resource_limits["max_preserved_artifact_bytes"],
                    resource_limits["max_runtime_scratch_bytes"],
                    resource_limits["max_single_preserved_artifact_bytes"],
                    resource_limits["max_single_runtime_file_bytes"],
                    INDEPENDENT_INVALID_CONTINUE_POLICY,
                ),
            )
            for planned_order, arm in enumerate(arms):
                execution = arm_execution[planned_order]
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
                     api_output_per_million_snapshot, currency_snapshot,
                     conversation_group_id, sequence_index,
                     depends_on_arm_id, requires_prior_success,
                     fresh_thread, resume_prior_thread)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?)
                    """,
                    (
                        execution["arm_id"],
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
                        execution["conversation_group_id"],
                        execution["sequence_index"],
                        execution["depends_on_arm_id"],
                        execution["requires_prior_success"],
                        execution["fresh_thread"],
                        execution["resume_prior_thread"],
                    ),
                )
                self.connection.execute(
                    """
                    INSERT INTO comparison_arm_transitions
                    (transition_id, suite_id, arm_id, lifecycle_state,
                     recorded_at, sequence_number)
                    VALUES (?, ?, ?, 'planned', ?, 0)
                    """,
                    (_id("transition"), suite_id, execution["arm_id"], now),
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
                "conversation_group_id",
                "resume_prior_thread",
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
            raw_group = spec.get("conversation_group_id")
            group = (
                _safe_text(
                    raw_group,
                    f"arms[{index}].conversation_group_id",
                    120,
                )
                if raw_group not in (None, "")
                else None
            )
            if group is not None and re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}", group
            ) is None:
                raise ValueError(
                    "conversation_group_id contains unsupported characters"
                )
            resume = spec.get("resume_prior_thread", False)
            if not isinstance(resume, bool):
                raise ValueError("resume_prior_thread must be boolean")
            if repetitions != 1 and (group is not None or resume):
                raise ValueError(
                    "conversation sequencing requires repetitions=1"
                )
            for repetition in range(repetitions):
                result.append(
                    {
                        "display_name": display,
                        "model": model,
                        "reasoning_effort": effort,
                        "context_mode": mode,
                        "repetition_index": repetition,
                        "conversation_group_id": group,
                        "resume_prior_thread": resume,
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
                SELECT arm_id, display_name, model, reasoning_effort, context_mode,
                       repetition_index, planned_order, effective_order,
                       conversation_group_id, sequence_index,
                       depends_on_arm_id, requires_prior_success,
                       fresh_thread, resume_prior_thread,
                       expected_model, expected_reasoning_effort,
                       prompt_sha256, director_state_sha256,
                       output_schema_sha256, evidence_registry_sha256,
                       advisory_registry_sha256, executable_registry_sha256,
                       applicable_action_space_sha256,
                       base_instructions_sha256,
                       developer_instructions_sha256, campaign_budget_sha256
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
        plan = {
            "schema_version": "2.0",
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
            "fail_closed": bool(suite["fail_closed"]),
            "measurement_only": bool(suite["measurement_only"]),
            "execute_decisions": bool(suite["execute_decisions"]),
            "randomized_arm_order": bool(suite["randomized_arm_order"]),
            "ordering_seed": suite["ordering_seed"],
            "maximum_total_server_tokens": suite["maximum_total_server_tokens"],
            "maximum_client_owned_tokens_per_turn": suite[
                "maximum_client_owned_tokens_per_turn"
            ],
            "maximum_stdout_bytes": suite["maximum_stdout_bytes"],
            "maximum_stderr_bytes": suite["maximum_stderr_bytes"],
            "maximum_wire_log_bytes": suite["maximum_wire_log_bytes"],
            "maximum_artifact_directory_bytes": suite[
                "maximum_artifact_directory_bytes"
            ],
            "maximum_worker_wall_seconds": suite[
                "maximum_worker_wall_seconds"
            ],
        }
        if int(suite["resource_accounting_version"]) >= 2:
            plan["schema_version"] = "2.1"
            plan["resource_accounting_version"] = 2
            plan["max_preserved_artifact_bytes"] = suite[
                "max_preserved_artifact_bytes"
            ]
            plan["max_runtime_scratch_bytes"] = suite[
                "max_runtime_scratch_bytes"
            ]
            plan["max_single_preserved_artifact_bytes"] = suite[
                "max_single_preserved_artifact_bytes"
            ]
            plan["max_single_runtime_file_bytes"] = suite[
                "max_single_runtime_file_bytes"
            ]
            plan["deprecated_resource_limit_mapping"] = {
                "maximum_artifact_directory_bytes": (
                    "max_preserved_artifact_bytes"
                )
            }
        if suite["arm_failure_policy"] is not None:
            plan["schema_version"] = "2.2"
            plan["arm_failure_policy"] = str(
                suite["arm_failure_policy"]
            )
            plan["arm_failure_contract"] = {
                "infrastructure_security_protocol_resource_model_contract": (
                    "stop_later_arms"
                ),
                "schema_or_semantic_invalid_independent": "continue",
                "dependent_requires_prior_success": "block",
                "returned_actions": "never_execute",
            }
        return plan

    def plan_payload(self, suite_id: str) -> dict[str, Any]:
        return self._plan_payload(suite_id)

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
        if suite["fail_closed"]:
            policy = suite["arm_failure_policy"]
            if policy == INDEPENDENT_INVALID_CONTINUE_POLICY:
                dependency_status = None
                if arm["requires_prior_success"]:
                    dependency_status = self.connection.execute(
                        """
                        SELECT t.lifecycle_status
                        FROM comparison_arms a
                        LEFT JOIN comparison_turns t ON t.arm_id=a.arm_id
                        WHERE a.arm_id=?
                        """,
                        (arm["depends_on_arm_id"],),
                    ).fetchone()
                if (
                    dependency_status is not None
                    and dependency_status["lifecycle_status"] != "completed"
                ):
                    raise ValueError(
                        "dependent arm requires a completed predecessor"
                    )
                if any(
                    row["lifecycle_status"]
                    not in {"completed", *MODEL_INVALID_ARM_STATES}
                    for row in earlier
                ):
                    raise ValueError(
                        "fail-closed suite cannot continue after an "
                        "infrastructure or incomplete arm failure"
                    )
            elif any(
                row["lifecycle_status"] != "completed" for row in earlier
            ):
                raise ValueError(
                    "fail-closed suite cannot continue after an arm failure"
                )
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
        transitions = [
            dict(row)
            for row in self.connection.execute(
                """
                SELECT * FROM comparison_arm_transitions
                WHERE suite_id=? ORDER BY recorded_at, sequence_number
                """,
                (suite_id,),
            )
        ]
        latest_by_arm: dict[str, dict[str, Any]] = {}
        for transition in transitions:
            latest_by_arm[str(transition["arm_id"])] = transition
        for arm in arms:
            latest = latest_by_arm.get(str(arm["arm_id"]))
            arm["lifecycle_state"] = (
                latest["lifecycle_state"] if latest else arm["status"]
            )
            arm["lifecycle_reason"] = latest["reason"] if latest else None
            arm["display_lifecycle_state"] = arm["lifecycle_state"]
            if (
                suite["status"] == "failed"
                and arm["lifecycle_state"] == "planned"
                and int(suite["consumed_inference_starts"])
                < int(suite["planned_inference_count"])
            ):
                arm["display_lifecycle_state"] = "blocked / not started"
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
        attempt = self.connection.execute(
            """
            SELECT * FROM comparison_execution_attempts
            WHERE suite_id=? ORDER BY started_at DESC LIMIT 1
            """,
            (suite_id,),
        ).fetchone()
        lease = self.connection.execute(
            """
            SELECT * FROM comparison_worker_leases
            WHERE suite_id=? ORDER BY acquired_at DESC LIMIT 1
            """,
            (suite_id,),
        ).fetchone()
        stop_request = self.connection.execute(
            """
            SELECT * FROM comparison_stop_requests
            WHERE suite_id=? ORDER BY requested_at DESC LIMIT 1
            """,
            (suite_id,),
        ).fetchone()
        resource_samples = [
            dict(row)
            for row in self.connection.execute(
                """
                SELECT * FROM comparison_resource_samples
                WHERE suite_id=? AND category<>'credential_material'
                ORDER BY sampled_at, category, sample_kind
                """,
                (suite_id,),
            )
        ]
        worker = {
            "attempt": dict(attempt) if attempt is not None else None,
            "lease": dict(lease) if lease is not None else None,
            "stop_request": (
                dict(stop_request) if stop_request is not None else None
            ),
            "completed_arms": sum(
                arm["lifecycle_state"] == "completed" for arm in arms
            ),
            "planned_arms": len(arms),
            "total_server_tokens": sum(
                int(turn["server_reported_total_tokens"] or 0)
                for turn in turns
            ),
            "resource_samples": resource_samples,
        }
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
            for arm in arms:
                for key in (
                    "model",
                    "reasoning_effort",
                    "context_mode",
                    "expected_model",
                    "expected_reasoning_effort",
                    "effective_model",
                    "effective_reasoning_effort",
                    "effective_context_mode",
                    "cost_profile_id",
                    "relative_cost_multiplier_snapshot",
                    "api_input_per_million_snapshot",
                    "api_cached_input_per_million_snapshot",
                    "api_output_per_million_snapshot",
                    "currency_snapshot",
                ):
                    arm.pop(key, None)
            worker = {
                "completed_arms": worker["completed_arms"],
                "planned_arms": worker["planned_arms"],
            }
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
            "worker": worker,
            "arm_transitions": transitions,
            "resource_samples": [] if blind else resource_samples,
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


def import_comparison_fixture_bundle(
    database: Path, bundle_path: Path
) -> str:
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    required = {
        "schema_version",
        "fixture_id",
        "display_name",
        "fixture_type",
        "director_state",
        "status_timestamp",
        "target_statement_id",
        "materials",
    }
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError("fixture bundle has an unsupported shape")
    if payload["schema_version"] != "1.0":
        raise ValueError("unsupported fixture bundle schema")
    fixture_id = _safe_text(payload["fixture_id"], "fixture_id", 120)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}", fixture_id) is None:
        raise ValueError("fixture_id contains unsupported characters")
    fixture_type = str(payload["fixture_type"])
    if fixture_type not in {
        "preserved_director_state",
        "campaign_snapshot",
        "custom_director_state_json",
    }:
        raise ValueError("unsupported fixture_type")
    state = payload["director_state"]
    materials = payload["materials"]
    if not isinstance(state, dict) or not isinstance(materials, dict):
        raise ValueError("fixture state and materials must be objects")
    material_keys = {
        "prompt",
        "output_schema",
        "applicable_action_space",
        "evidence_registry",
        "advisory_registry",
        "executable_registry",
        "base_instructions",
        "developer_instructions",
        "campaign_budget",
    }
    if set(materials) != material_keys:
        raise ValueError("fixture materials are incomplete")
    if not isinstance(materials["prompt"], str):
        raise ValueError("fixture prompt must be a string")
    if not isinstance(materials["base_instructions"], str):
        raise ValueError("fixture base instructions must be a string")
    if materials["developer_instructions"] != "":
        raise ValueError("comparison fixtures require empty developer instructions")
    hashes = {
        "prompt": sha256(materials["prompt"].encode("utf-8")).hexdigest(),
        "output_schema": canonical_sha256(materials["output_schema"]),
        "applicable_action_space": canonical_sha256(
            materials["applicable_action_space"]
        ),
        "evidence_registry": canonical_sha256(materials["evidence_registry"]),
        "advisory_registry": canonical_sha256(materials["advisory_registry"]),
        "executable_registry": canonical_sha256(
            materials["executable_registry"]
        ),
        "base_instructions": sha256(
            materials["base_instructions"].encode("utf-8")
        ).hexdigest(),
        "developer_instructions": sha256(b"").hexdigest(),
        "campaign_budget": canonical_sha256(materials["campaign_budget"]),
    }
    with ComparisonStore(database) as store:
        store.seed_fixture(
            fixture_id=fixture_id,
            display_name=_safe_text(
                payload["display_name"], "display_name", 120
            ),
            fixture_type=fixture_type,
            source_artifact_reference=bundle_path.name,
            director_state=state,
            metadata={
                "target_statement_id": _safe_text(
                    payload["target_statement_id"],
                    "target_statement_id",
                    120,
                ),
                "status_timestamp": _safe_text(
                    payload["status_timestamp"], "status_timestamp", 80
                ),
                "estimated_client_owned_tokens": math.ceil(
                    (
                        len(canonical_bytes(state))
                        + len(materials["prompt"].encode("utf-8"))
                        + len(canonical_bytes(materials["output_schema"]))
                        + len(materials["base_instructions"].encode("utf-8"))
                    )
                    / 4
                ),
                "hashes": hashes,
                "materials": materials,
            },
        )
    return fixture_id


def import_campaign_snapshot_fixture(
    *,
    source_workspace: Path,
    destination_workspace: Path,
    snapshot_reference: str,
    display_name: str,
) -> dict[str, Any]:
    """Create an isolated live-comparison workspace from one scientific snapshot."""

    from .research.context import prepare_director_state_v2
    from .research.context_screen import build_context_screen_prompt
    from .research.director import base_instructions
    from .research.protocol import director_decision_schema
    from .state import atomic_write_json

    source = source_workspace.resolve()
    destination = destination_workspace.resolve()
    if source == destination:
        raise ValueError("source and destination workspaces must differ")
    if not source.is_dir():
        raise ValueError("source workspace does not exist")
    if destination.exists():
        raise ValueError("destination workspace already exists")
    _reject_synthetic_source_workspace(source)

    source_database = source / "results.sqlite3"
    report_path = source / "ai-experiment-report.json"
    pointer_path = source / "active-research-campaign.json"
    if not source_database.is_file() or not report_path.is_file() or not pointer_path.is_file():
        raise ValueError("source workspace lacks preserved campaign evidence")

    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or not isinstance(pointer, dict):
        raise ValueError("source campaign metadata is malformed")
    campaign_dir = Path(str(pointer.get("campaign_dir", ""))).resolve()
    campaign_dir.relative_to(source)

    snapshot_id = str(snapshot_reference)
    if snapshot_id == "A4":
        snapshot_id = str(report.get("second_snapshot_id", ""))
    if re.fullmatch(r"snapshot-[A-Za-z0-9]+", snapshot_id) is None:
        raise ValueError("snapshot reference does not identify preserved A4")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(
            prefix=".model-comparison-import-",
            dir=destination.parent,
        )
    )
    try:
        backup_database = temporary_root / "source-online-backup.sqlite3"
        source_uri = f"file:{source_database.as_posix()}?mode=ro"
        with (
            closing(sqlite3.connect(source_uri, uri=True)) as source_connection,
            closing(sqlite3.connect(backup_database)) as backup_connection,
        ):
            source_connection.backup(backup_connection)
        with closing(sqlite3.connect(backup_database)) as backup_connection:
            backup_connection.row_factory = sqlite3.Row
            source_schema = int(
                backup_connection.execute("PRAGMA user_version").fetchone()[0]
            )
            source_integrity = str(
                backup_connection.execute("PRAGMA integrity_check").fetchone()[0]
            )
            source_foreign_keys = list(
                backup_connection.execute("PRAGMA foreign_key_check")
            )
            snapshot_row = backup_connection.execute(
                """
                SELECT snapshot_id, campaign_id, artifact_ref, artifact_sha256,
                       payload_bytes, created_at
                FROM director_snapshots WHERE snapshot_id=?
                """,
                (snapshot_id,),
            ).fetchone()
            backup_connection.execute("PRAGMA journal_mode=DELETE")
        if source_integrity != "ok" or source_foreign_keys:
            raise RuntimeError("source Online Backup failed SQLite validation")
        if snapshot_row is None:
            raise ValueError("preserved snapshot is absent from source database")
        if str(snapshot_row["campaign_id"]) != str(report.get("campaign_id")):
            raise ValueError("snapshot campaign does not match source report")
        backup_database.unlink()

        source_artifact = (campaign_dir / str(snapshot_row["artifact_ref"])).resolve()
        source_artifact.relative_to(campaign_dir)
        raw_snapshot = source_artifact.read_bytes()
        source_artifact_sha256 = sha256(raw_snapshot).hexdigest()
        if source_artifact_sha256 != str(snapshot_row["artifact_sha256"]):
            raise ValueError("source snapshot artifact hash mismatch")
        if len(raw_snapshot) != int(snapshot_row["payload_bytes"]):
            raise ValueError("source snapshot artifact size mismatch")
        snapshot = json.loads(raw_snapshot)
        if not isinstance(snapshot, dict) or snapshot.get("snapshot_id") != snapshot_id:
            raise ValueError("source snapshot artifact has an unexpected shape")

        prepared = prepare_director_state_v2(snapshot)
        state = prepared.state
        materials = {
            "prompt": build_context_screen_prompt(snapshot),
            "output_schema": director_decision_schema(
                state["allowed_action_space"],
                existing_hypothesis_ids=evidence_registry_ids(
                    prepared.evidence_registry,
                    kinds=frozenset({"hypothesis"}),
                ),
                submitted_evidence_ids=evidence_registry_ids(
                    prepared.evidence_registry
                ),
            ),
            "applicable_action_space": state["allowed_action_space"],
            "evidence_registry": prepared.evidence_registry,
            "advisory_registry": prepared.advisory_target_registry,
            "executable_registry": prepared.executable_target_registry,
            "base_instructions": base_instructions(),
            "developer_instructions": "",
            "campaign_budget": state["campaign_budget"],
        }
        _reject_private_fixture_material({"director_state": state, "materials": materials})

        fixture_id = "m6-executable-preserved-a4"
        target = state["target"]
        bundle = {
            "schema_version": "1.0",
            "fixture_id": fixture_id,
            "display_name": _safe_text(display_name, "display_name", 120),
            "fixture_type": "campaign_snapshot",
            "director_state": state,
            "status_timestamp": str(target["status_timestamp"]),
            "target_statement_id": str(target["statement_id"]),
            "materials": materials,
        }
        artifact_directory = temporary_root / "scientific-artifacts"
        artifact_directory.mkdir(parents=True)
        preserved_snapshot = artifact_directory / f"{snapshot_id}.json"
        shutil.copyfile(source_artifact, preserved_snapshot)
        bundle_path = artifact_directory / "m6-executable-preserved-a4.json"
        atomic_write_json(bundle_path, bundle)

        destination_database = temporary_root / "results.sqlite3"
        imported_fixture_id = import_comparison_fixture_bundle(
            destination_database, bundle_path
        )
        with ComparisonStore(destination_database) as store:
            destination_schema = int(
                store.connection.execute("PRAGMA user_version").fetchone()[0]
            )
            destination_integrity = str(
                store.connection.execute("PRAGMA integrity_check").fetchone()[0]
            )
            destination_foreign_keys = list(
                store.connection.execute("PRAGMA foreign_key_check")
            )
            fixture = store.connection.execute(
                "SELECT fixture_sha256 FROM comparison_fixtures WHERE fixture_id=?",
                (imported_fixture_id,),
            ).fetchone()
        if destination_integrity != "ok" or destination_foreign_keys:
            raise RuntimeError("destination workspace failed SQLite validation")
        assert fixture is not None

        marker = {
            "workspace_kind": "model_comparison_live",
            "synthetic_data": False,
            "source_workspace": source.name,
            "source_campaign_id": str(report["campaign_id"]),
            "source_snapshot_id": snapshot_id,
            "source_snapshot_artifact_sha256": source_artifact_sha256,
            "source_report_sha256": sha256(report_bytes).hexdigest(),
            "fixture_id": fixture_id,
            "fixture_sha256": str(fixture["fixture_sha256"]),
            "schema_version": destination_schema,
        }
        atomic_write_json(temporary_root / "workspace.json", marker)
        temporary_root.replace(destination)
        return {
            "ok": True,
            **marker,
            "source_schema_version": source_schema,
            "source_integrity_check": source_integrity,
            "source_foreign_key_check_rows": len(source_foreign_keys),
            "destination_integrity_check": destination_integrity,
            "destination_foreign_key_check_rows": len(destination_foreign_keys),
            "auth_access": False,
            "model_inferences": 0,
            "search_batches": 0,
            "action_dispatches": 0,
        }
    except BaseException:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise


def _reject_synthetic_source_workspace(source: Path) -> None:
    for name in ("workspace.json", "fixture-summary.json"):
        marker_path = source / name
        if not marker_path.is_file():
            continue
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        if not isinstance(marker, dict):
            raise ValueError("source workspace marker is malformed")
        if marker.get("synthetic_data") is True or marker.get("workspace_kind") == "ui_demo":
            raise ValueError("synthetic or demo workspaces cannot seed live comparisons")


def _reject_private_fixture_material(value: Any) -> None:
    prohibited = (
        "auth.json",
        "codex-home",
        "codex-sqlite-home",
        "/wire/",
        "/sessions/",
        "rollout-",
    )
    if isinstance(value, dict):
        for child in value.values():
            _reject_private_fixture_material(child)
        return
    if isinstance(value, list):
        for child in value:
            _reject_private_fixture_material(child)
        return
    if not isinstance(value, str):
        return
    lowered = value.lower()
    if value.startswith("/") or any(token in lowered for token in prohibited):
        raise ValueError("fixture material contains a private runtime reference")


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
