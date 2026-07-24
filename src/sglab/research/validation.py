from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
import math
import re

from .catalog import (
    ACTION_TYPES,
    ALGORITHMS,
    ALGORITHM_PARAMETERS,
    DIAGNOSTICS,
    GRAPH_FAMILIES,
    PARAMETER_DOMAINS,
    REVIEW_EVENTS,
)
from .protocol import (
    DecisionValidation,
    MAX_DECISION_BYTES,
    ValidationIssue,
    canonical_json,
)

IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
COMMON_ACTION_FIELDS = {
    "action_id",
    "type",
    "priority",
    "hypothesis_ids",
    "evidence_ids",
    "rationale",
    "expected_effect",
    "evaluation_window",
    "idempotency_key",
    "lease_seconds",
    "fallback",
}
ACTION_FIELDS = {
    "start_lane": {"spec"},
    "patch_lane": {"lane_id", "expected_lane_version", "patch"},
    "fork_lane": {
        "lane_id",
        "expected_lane_version",
        "checkpoint_id",
        "variants",
    },
    "restart_lane": {"lane_id", "expected_lane_version", "restart_spec"},
    "stop_lane": {"lane_id", "expected_lane_version"},
    "reallocate_resources": {"allocations"},
    "promote_candidate": {"candidate_id"},
    "request_diagnostic": {"diagnostic_type", "subject_ids"},
    "schedule_verification": {"candidate_ids", "verification_priority"},
    "set_review_trigger": {"review_trigger"},
}


@dataclass(frozen=True, slots=True)
class DecisionContext:
    snapshot_id: str
    evidence_ids: frozenset[str]
    lane_versions: dict[str, int]
    lane_algorithms: dict[str, str]
    checkpoint_ids: frozenset[str]
    candidate_ids: frozenset[str]
    hypothesis_ids: frozenset[str] = frozenset()
    max_active_lanes: int = 8


class _Issues:
    def __init__(self) -> None:
        self.values: list[ValidationIssue] = []

    def add(self, path: str, message: str) -> None:
        self.values.append(ValidationIssue(path, message))

    def exact_keys(
        self,
        value: Any,
        path: str,
        required: set[str],
        allowed: set[str] | None = None,
    ) -> bool:
        if not isinstance(value, dict):
            self.add(path, "must be an object")
            return False
        allowed = required if allowed is None else allowed
        missing = required - value.keys()
        extra = value.keys() - allowed
        for key in sorted(missing):
            self.add(f"{path}.{key}", "is required")
        for key in sorted(extra):
            self.add(f"{path}.{key}", "is not allowed")
        return not missing and not extra


def validate_decision(
    value: Any,
    context: DecisionContext,
) -> DecisionValidation:
    issues = _Issues()
    try:
        canonical_json(value, max_bytes=MAX_DECISION_BYTES)
    except (TypeError, ValueError) as error:
        issues.add("$", str(error))
        return DecisionValidation(False, tuple(issues.values))
    top_fields = {
        "schema_version",
        "snapshot_id",
        "campaign_assessment",
        "hypothesis_updates",
        "actions",
        "next_review",
    }
    if not issues.exact_keys(value, "$", top_fields):
        return DecisionValidation(False, tuple(issues.values))
    assert isinstance(value, dict)
    if value["schema_version"] != "1.0":
        issues.add("$.schema_version", "must equal 1.0")
    if value["snapshot_id"] != context.snapshot_id:
        issues.add("$.snapshot_id", "does not match the committed snapshot")
    _bounded_text(
        issues,
        value["campaign_assessment"],
        "$.campaign_assessment",
        1,
        6000,
    )
    new_hypotheses = _validate_hypotheses(
        issues, value["hypothesis_updates"], context
    )
    actions = value["actions"]
    if not isinstance(actions, list) or not 1 <= len(actions) <= 12:
        issues.add("$.actions", "must contain between 1 and 12 actions")
        actions = []
    action_ids: set[str] = set()
    idempotency_keys: set[str] = set()
    projected_starts = 0
    for index, action in enumerate(actions):
        path = f"$.actions[{index}]"
        action_type = action.get("type") if isinstance(action, dict) else None
        if action_type not in ACTION_TYPES:
            issues.add(f"{path}.type", "is not in the reviewed action catalog")
            continue
        required = COMMON_ACTION_FIELDS | ACTION_FIELDS[action_type]
        if not issues.exact_keys(action, path, required):
            continue
        action_id = _identifier(issues, action["action_id"], f"{path}.action_id")
        if action_id in action_ids:
            issues.add(f"{path}.action_id", "is duplicated in this batch")
        action_ids.add(action_id)
        key = _identifier(
            issues,
            action["idempotency_key"],
            f"{path}.idempotency_key",
            minimum=8,
        )
        if key in idempotency_keys:
            issues.add(f"{path}.idempotency_key", "is duplicated in this batch")
        idempotency_keys.add(key)
        _integer(issues, action["priority"], f"{path}.priority", 0, 100)
        _integer(
            issues, action["lease_seconds"], f"{path}.lease_seconds", 30, 7200
        )
        _bounded_text(issues, action["rationale"], f"{path}.rationale", 1, 4000)
        _bounded_text(
            issues,
            action["expected_effect"],
            f"{path}.expected_effect",
            1,
            2000,
        )
        _id_list(
            issues,
            action["evidence_ids"],
            f"{path}.evidence_ids",
            maximum=32,
            allowlist=context.evidence_ids,
        )
        _id_list(
            issues,
            action["hypothesis_ids"],
            f"{path}.hypothesis_ids",
            maximum=16,
            allowlist=context.hypothesis_ids | new_hypotheses,
        )
        _evaluation_window(
            issues, action["evaluation_window"], f"{path}.evaluation_window"
        )
        if not issues.exact_keys(
            action["fallback"],
            f"{path}.fallback",
            {"on_precondition_failure"},
        ):
            pass
        elif action["fallback"]["on_precondition_failure"] not in {
            "reject",
            "replan",
        }:
            issues.add(
                f"{path}.fallback.on_precondition_failure",
                "must be reject or replan",
            )
        if action_type == "start_lane":
            projected_starts += 1
            _start_lane(issues, action["spec"], f"{path}.spec")
        elif action_type in {
            "patch_lane",
            "fork_lane",
            "restart_lane",
            "stop_lane",
        }:
            algorithm = _lane_target(issues, action, path, context)
            if action_type == "patch_lane":
                _parameters(
                    issues,
                    action["patch"],
                    f"{path}.patch",
                    algorithm,
                    partial=True,
                )
            elif action_type == "fork_lane":
                _fork(issues, action, path, context, algorithm)
                if isinstance(action["variants"], list):
                    projected_starts += len(action["variants"])
            elif action_type == "restart_lane":
                _restart(issues, action["restart_spec"], f"{path}.restart_spec", context)
        elif action_type == "reallocate_resources":
            _allocations(issues, action["allocations"], f"{path}.allocations", context)
        elif action_type == "promote_candidate":
            _candidate(
                issues, action["candidate_id"], f"{path}.candidate_id", context
            )
        elif action_type == "request_diagnostic":
            if action["diagnostic_type"] not in DIAGNOSTICS:
                issues.add(
                    f"{path}.diagnostic_type", "is not a reviewed diagnostic"
                )
            _id_list(
                issues,
                action["subject_ids"],
                f"{path}.subject_ids",
                minimum=1,
                maximum=32,
                allowlist=(
                    context.evidence_ids
                    | context.candidate_ids
                    | frozenset(context.lane_versions)
                ),
            )
        elif action_type == "schedule_verification":
            _candidate_list(
                issues,
                action["candidate_ids"],
                f"{path}.candidate_ids",
                context,
            )
            _integer(
                issues,
                action["verification_priority"],
                f"{path}.verification_priority",
                0,
                100,
            )
        elif action_type == "set_review_trigger":
            _review(issues, action["review_trigger"], f"{path}.review_trigger")
    active_count = len(context.lane_versions) + projected_starts
    if active_count > context.max_active_lanes:
        issues.add(
            "$.actions",
            f"would exceed max_active_lanes={context.max_active_lanes}",
        )
    _review(issues, value["next_review"], "$.next_review")
    return DecisionValidation(
        not issues.values,
        tuple(issues.values),
        dict(value) if not issues.values else None,
    )


def _validate_hypotheses(
    issues: _Issues,
    value: Any,
    context: DecisionContext,
) -> frozenset[str]:
    if not isinstance(value, list) or len(value) > 32:
        issues.add("$.hypothesis_updates", "must be an array of at most 32 items")
        return frozenset()
    created: set[str] = set()
    fields = {
        "hypothesis_id",
        "operation",
        "statement",
        "confidence",
        "evidence_for",
        "evidence_against",
    }
    for index, item in enumerate(value):
        path = f"$.hypothesis_updates[{index}]"
        if not issues.exact_keys(item, path, fields):
            continue
        identifier = _identifier(
            issues, item["hypothesis_id"], f"{path}.hypothesis_id"
        )
        operation = item["operation"]
        if operation not in {"create", "confirm", "weaken", "reject", "revise"}:
            issues.add(f"{path}.operation", "is not supported")
        if operation == "create":
            if identifier in context.hypothesis_ids or identifier in created:
                issues.add(f"{path}.hypothesis_id", "already exists")
            created.add(identifier)
        elif identifier not in context.hypothesis_ids:
            issues.add(
                f"{path}.hypothesis_id",
                "must reference an existing hypothesis",
            )
        _bounded_text(issues, item["statement"], f"{path}.statement", 1, 4000)
        _number(issues, item["confidence"], f"{path}.confidence", 0, 1)
        for name in ("evidence_for", "evidence_against"):
            _id_list(
                issues,
                item[name],
                f"{path}.{name}",
                maximum=32,
                allowlist=context.evidence_ids,
            )
    return frozenset(created)


def _start_lane(issues: _Issues, spec: Any, path: str) -> None:
    fields = {"algorithm", "graph_family", "seed", "parameters", "resource_share"}
    if not issues.exact_keys(spec, path, fields):
        return
    algorithm = spec["algorithm"]
    if algorithm not in ALGORITHMS:
        issues.add(f"{path}.algorithm", "is not supported")
        algorithm = None
    if spec["graph_family"] not in GRAPH_FAMILIES:
        issues.add(f"{path}.graph_family", "is not supported")
    _integer(issues, spec["seed"], f"{path}.seed", 0, 2**63 - 1)
    _number(issues, spec["resource_share"], f"{path}.resource_share", 0, 1, exclusive_min=True)
    _parameters(issues, spec["parameters"], f"{path}.parameters", algorithm)
    if (
        isinstance(spec["parameters"], dict)
        and spec["graph_family"] == "connected_cubic"
        and isinstance(spec["parameters"].get("order"), int)
        and spec["parameters"]["order"] % 2
    ):
        issues.add(f"{path}.parameters.order", "must be even for connected_cubic")


def _lane_target(
    issues: _Issues,
    action: dict[str, Any],
    path: str,
    context: DecisionContext,
) -> str | None:
    lane_id = _identifier(issues, action["lane_id"], f"{path}.lane_id")
    version = _integer(
        issues,
        action["expected_lane_version"],
        f"{path}.expected_lane_version",
        0,
        2**63 - 1,
    )
    if lane_id not in context.lane_versions:
        issues.add(f"{path}.lane_id", "does not reference an active lane")
        return None
    if version != context.lane_versions[lane_id]:
        issues.add(
            f"{path}.expected_lane_version",
            "is stale for the committed snapshot",
        )
    return context.lane_algorithms.get(lane_id)


def _fork(
    issues: _Issues,
    action: dict[str, Any],
    path: str,
    context: DecisionContext,
    algorithm: str | None,
) -> None:
    checkpoint = _identifier(
        issues, action["checkpoint_id"], f"{path}.checkpoint_id"
    )
    if checkpoint not in context.checkpoint_ids:
        issues.add(f"{path}.checkpoint_id", "is not an admissible checkpoint")
    variants = action["variants"]
    if not isinstance(variants, list) or not 1 <= len(variants) <= 4:
        issues.add(f"{path}.variants", "must contain between 1 and 4 variants")
        return
    for index, variant in enumerate(variants):
        variant_path = f"{path}.variants[{index}]"
        fields = {"name", "patch", "resource_share"}
        if not issues.exact_keys(variant, variant_path, fields):
            continue
        _bounded_text(issues, variant["name"], f"{variant_path}.name", 1, 128)
        _parameters(
            issues,
            variant["patch"],
            f"{variant_path}.patch",
            algorithm,
            partial=True,
        )
        _number(
            issues,
            variant["resource_share"],
            f"{variant_path}.resource_share",
            0,
            1,
            exclusive_min=True,
        )


def _restart(
    issues: _Issues,
    spec: Any,
    path: str,
    context: DecisionContext,
) -> None:
    required = {"source", "seed"}
    allowed = required | {"checkpoint_id", "candidate_id"}
    if not issues.exact_keys(spec, path, required, allowed):
        return
    source = spec["source"]
    if source not in {"new_seed", "checkpoint", "archive_elite"}:
        issues.add(f"{path}.source", "is not supported")
    _integer(issues, spec["seed"], f"{path}.seed", 0, 2**63 - 1)
    if source == "checkpoint":
        checkpoint = spec.get("checkpoint_id")
        if checkpoint not in context.checkpoint_ids:
            issues.add(f"{path}.checkpoint_id", "is not admissible")
    if source == "archive_elite":
        candidate = spec.get("candidate_id")
        if candidate not in context.candidate_ids:
            issues.add(f"{path}.candidate_id", "is not admissible")


def _allocations(
    issues: _Issues,
    value: Any,
    path: str,
    context: DecisionContext,
) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= 32:
        issues.add(path, "must contain between 1 and 32 allocations")
        return
    total = 0.0
    seen: set[str] = set()
    for index, allocation in enumerate(value):
        item_path = f"{path}[{index}]"
        fields = {"lane_id", "expected_lane_version", "resource_share"}
        if not issues.exact_keys(allocation, item_path, fields):
            continue
        _lane_target(issues, allocation, item_path, context)
        lane_id = str(allocation["lane_id"])
        if lane_id in seen:
            issues.add(f"{item_path}.lane_id", "is duplicated")
        seen.add(lane_id)
        share = _number(
            issues,
            allocation["resource_share"],
            f"{item_path}.resource_share",
            0,
            1,
        )
        if share is not None:
            total += share
    if total > 1.0 + 1e-9:
        issues.add(path, "resource shares exceed 1.0")


def _parameters(
    issues: _Issues,
    value: Any,
    path: str,
    algorithm: str | None,
    *,
    partial: bool = False,
) -> None:
    if not isinstance(value, dict):
        issues.add(path, "must be an object")
        return
    if partial and not value:
        issues.add(path, "must not be empty")
    allowed = ALGORITHM_PARAMETERS.get(algorithm, set(PARAMETER_DOMAINS))
    for name in value:
        if name not in allowed:
            issues.add(f"{path}.{name}", "is not valid for this algorithm")
            continue
        domain = PARAMETER_DOMAINS[name]
        if domain["type"] == "integer":
            _integer(
                issues,
                value[name],
                f"{path}.{name}",
                domain["minimum"],
                domain["maximum"],
            )
        else:
            _number(
                issues,
                value[name],
                f"{path}.{name}",
                domain["minimum"],
                domain["maximum"],
            )
    if not partial:
        for required in ("order", "batch_candidates", "witness_cap"):
            if required not in value:
                issues.add(f"{path}.{required}", "is required")


def _evaluation_window(issues: _Issues, value: Any, path: str) -> None:
    fields = {"max_wall_seconds", "max_candidate_delta"}
    if not issues.exact_keys(value, path, fields):
        return
    _integer(issues, value["max_wall_seconds"], f"{path}.max_wall_seconds", 10, 7200)
    _integer(
        issues,
        value["max_candidate_delta"],
        f"{path}.max_candidate_delta",
        1,
        100_000_000,
    )


def _review(issues: _Issues, value: Any, path: str) -> None:
    fields = {"min_wall_seconds", "max_wall_seconds", "candidate_delta", "events"}
    if not issues.exact_keys(value, path, fields):
        return
    minimum = _integer(
        issues, value["min_wall_seconds"], f"{path}.min_wall_seconds", 10, 3600
    )
    maximum = _integer(
        issues, value["max_wall_seconds"], f"{path}.max_wall_seconds", 30, 7200
    )
    if minimum is not None and maximum is not None and minimum > maximum:
        issues.add(path, "minimum review time exceeds maximum")
    _integer(
        issues, value["candidate_delta"], f"{path}.candidate_delta", 1, 100_000_000
    )
    events = value["events"]
    if not isinstance(events, list) or len(events) > 16:
        issues.add(f"{path}.events", "must be an array of at most 16 events")
    else:
        if len(set(map(str, events))) != len(events):
            issues.add(f"{path}.events", "must be unique")
        for index, event in enumerate(events):
            if event not in REVIEW_EVENTS:
                issues.add(f"{path}.events[{index}]", "is not a reviewed event")


def _candidate(
    issues: _Issues,
    value: Any,
    path: str,
    context: DecisionContext,
) -> None:
    identifier = _identifier(issues, value, path)
    if identifier not in context.candidate_ids:
        issues.add(path, "is not an admissible retained candidate")


def _candidate_list(
    issues: _Issues,
    value: Any,
    path: str,
    context: DecisionContext,
) -> None:
    if not isinstance(value, list) or not 1 <= len(value) <= 32:
        issues.add(path, "must contain between 1 and 32 candidates")
        return
    if len(set(map(str, value))) != len(value):
        issues.add(path, "must be unique")
    for index, candidate in enumerate(value):
        _candidate(issues, candidate, f"{path}[{index}]", context)


def _id_list(
    issues: _Issues,
    value: Any,
    path: str,
    *,
    minimum: int = 0,
    maximum: int,
    allowlist: Iterable[str],
) -> None:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        issues.add(path, f"must contain between {minimum} and {maximum} identifiers")
        return
    allowed = set(allowlist)
    if len(set(map(str, value))) != len(value):
        issues.add(path, "must be unique")
    for index, identifier in enumerate(value):
        checked = _identifier(issues, identifier, f"{path}[{index}]")
        if checked not in allowed:
            issues.add(f"{path}[{index}]", "is not admissible in this snapshot")


def _identifier(
    issues: _Issues,
    value: Any,
    path: str,
    *,
    minimum: int = 1,
) -> str:
    if (
        not isinstance(value, str)
        or not minimum <= len(value) <= 128
        or IDENTIFIER.fullmatch(value) is None
    ):
        issues.add(path, "must be a bounded identifier")
        return ""
    return value


def _bounded_text(
    issues: _Issues,
    value: Any,
    path: str,
    minimum: int,
    maximum: int,
) -> None:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        issues.add(path, f"must be text of length {minimum}..{maximum}")


def _integer(
    issues: _Issues,
    value: Any,
    path: str,
    minimum: int,
    maximum: int,
) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        issues.add(path, "must be an integer")
        return None
    if not minimum <= value <= maximum:
        issues.add(path, f"must be between {minimum} and {maximum}")
    return value


def _number(
    issues: _Issues,
    value: Any,
    path: str,
    minimum: float,
    maximum: float,
    *,
    exclusive_min: bool = False,
) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        issues.add(path, "must be a number")
        return None
    number = float(value)
    if not math.isfinite(number):
        issues.add(path, "must be finite")
    elif (number <= minimum if exclusive_min else number < minimum) or number > maximum:
        qualifier = "greater than" if exclusive_min else "at least"
        issues.add(path, f"must be {qualifier} {minimum} and at most {maximum}")
    return number
