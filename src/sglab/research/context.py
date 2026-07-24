from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from math import ceil
from typing import Any
import hashlib
import json

from .catalog import action_catalog
from .protocol import canonical_json


DIRECTOR_STATE_VERSION = "2.0"
DIRECTOR_STATE_MAX_BYTES = 32 * 1024
ANCESTRY_MAX_BYTES = 8 * 1024
HISTORICAL_OUTCOMES_MAX_BYTES = 12 * 1024
CLIENT_ESTIMATED_TOKENS_MAX = 12_000
MAX_OUTCOMES = 3
MAX_GLOBAL_RECORD_SUMMARIES = 8
MAX_FINAL_BEST_ANCESTORS = 8
EVIDENCE_REGISTRY_VERSION = "1.0"
REFERENCE_REGISTRY_VERSION = "2.0"
ACTIVE_LANE_STATES = frozenset(
    {"starting", "running", "paused", "stopping"}
)


class DirectorContextMode(StrEnum):
    PERSISTENT_THREAD = "persistent_thread"
    COMPACTED_THREAD = "compacted_thread"
    STATELESS_TURNS = "stateless_turns"


class DirectorContextBudgetExceeded(RuntimeError):
    def __init__(
        self, message: str, *, size_report: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.size_report = size_report


@dataclass(frozen=True, slots=True)
class PreparedDirectorState:
    state: dict[str, Any]
    pre_compaction: dict[str, Any]
    size_report: dict[str, Any]
    evidence_registry: dict[str, Any]
    evidence_registry_sha256: str
    advisory_target_registry: dict[str, Any]
    advisory_target_registry_sha256: str
    executable_target_registry: dict[str, Any]
    executable_target_registry_sha256: str
    applicable_action_space_sha256: str


def director_state_v2_schema() -> dict[str, Any]:
    """Strict transport schema for compact scientific decision state."""

    identifier = {"type": ["string", "null"]}
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://sglab.local/schemas/director-state-v2.json",
        "title": "DirectorStateV2",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "source_snapshot_id",
            "target",
            "campaign_budget",
            "allowed_action_space",
            "best_ever_result",
            "latest_batch_outcome",
            "previous_outcomes",
            "plateau",
            "operator_aggregates",
            "stage_timing_percentages",
            "exact_verifier",
            "parameter_effects",
            "previous_hypothesis",
            "ancestry",
            "artifact_references",
        ],
        "properties": {
            "schema_version": {"const": DIRECTOR_STATE_VERSION},
            "source_snapshot_id": {"type": "string"},
            "target": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "statement_id",
                    "definition_sha256",
                    "status",
                    "status_timestamp",
                    "success_authority",
                ],
                "properties": {
                    "statement_id": {"type": "string"},
                    "definition_sha256": {"type": "string"},
                    "status": {"type": "string"},
                    "status_timestamp": {"type": "string"},
                    "success_authority": {"type": "string"},
                },
            },
            "campaign_budget": {"type": "object"},
            "allowed_action_space": {"type": "object"},
            "best_ever_result": {"type": ["object", "null"]},
            "latest_batch_outcome": {"type": ["object", "null"]},
            "previous_outcomes": {
                "type": "array",
                "maxItems": 2,
                "items": {"type": "object"},
            },
            "plateau": {"type": ["object", "null"]},
            "operator_aggregates": {"type": "object"},
            "stage_timing_percentages": {"type": "object"},
            "exact_verifier": {"type": ["object", "null"]},
            "parameter_effects": {"type": "object"},
            "previous_hypothesis": {
                "type": ["object", "null"],
                "properties": {
                    "hypothesis_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "expected_signal": identifier,
                    "expected_signal_occurred": {
                        "type": ["boolean", "null"]
                    },
                },
            },
            "ancestry": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "global_record_summaries",
                    "final_best_accepted_ancestors",
                ],
                "properties": {
                    "global_record_summaries": {
                        "type": "array",
                        "maxItems": MAX_GLOBAL_RECORD_SUMMARIES,
                        "items": {"type": "object"},
                    },
                    "final_best_accepted_ancestors": {
                        "type": "array",
                        "maxItems": MAX_FINAL_BEST_ANCESTORS,
                        "items": {"type": "object"},
                    },
                },
            },
            "artifact_references": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "id", "artifact_ref", "sha256"],
                    "properties": {
                        "kind": {"type": "string"},
                        "id": identifier,
                        "artifact_ref": identifier,
                        "sha256": identifier,
                    },
                },
            },
        },
    }


def prepare_director_state_v2(
    snapshot: dict[str, Any],
) -> PreparedDirectorState:
    """Build and deterministically compact model-facing scientific state."""

    pre = _unbounded_state(snapshot)
    state = json.loads(json.dumps(pre))
    outcomes = list(state.pop("_all_outcomes", []))
    state["latest_batch_outcome"] = outcomes[0] if outcomes else None
    state["previous_outcomes"] = outcomes[1:MAX_OUTCOMES]
    ancestry = state["ancestry"]
    ancestry["global_record_summaries"] = ancestry[
        "global_record_summaries"
    ][-MAX_GLOBAL_RECORD_SUMMARIES:]
    ancestry["final_best_accepted_ancestors"] = ancestry[
        "final_best_accepted_ancestors"
    ][-MAX_FINAL_BEST_ANCESTORS:]

    while _json_size(ancestry) > ANCESTRY_MAX_BYTES:
        if ancestry["final_best_accepted_ancestors"]:
            ancestry["final_best_accepted_ancestors"].pop(0)
        elif ancestry["global_record_summaries"]:
            ancestry["global_record_summaries"].pop(0)
        else:
            break
    while _json_size(state["previous_outcomes"]) > HISTORICAL_OUTCOMES_MAX_BYTES:
        if state["previous_outcomes"]:
            state["previous_outcomes"].pop()
        else:
            break
    state["allowed_action_space"] = _applicable_action_space(
        snapshot, state, action_catalog()
    )
    while _json_size(state) > DIRECTOR_STATE_MAX_BYTES:
        if ancestry["final_best_accepted_ancestors"]:
            ancestry["final_best_accepted_ancestors"].pop(0)
        elif ancestry["global_record_summaries"]:
            ancestry["global_record_summaries"].pop(0)
        elif state["previous_outcomes"]:
            state["previous_outcomes"].pop()
        else:
            break
    within_state_limits = (
        _json_size(state) <= DIRECTOR_STATE_MAX_BYTES
        and _json_size(ancestry) <= ANCESTRY_MAX_BYTES
        and _json_size(state["previous_outcomes"])
        <= HISTORICAL_OUTCOMES_MAX_BYTES
    )
    if not within_state_limits:
        report = {
            "schema_version": "1.0",
            "limits": {
                "director_state_bytes": DIRECTOR_STATE_MAX_BYTES,
                "ancestry_bytes": ANCESTRY_MAX_BYTES,
                "historical_outcomes_bytes": HISTORICAL_OUTCOMES_MAX_BYTES,
                "client_owned_estimated_tokens": (
                    CLIENT_ESTIMATED_TOKENS_MAX
                ),
            },
            "pre_compaction": _measure_state(pre),
            "post_compaction": _measure_state(state),
            "compaction_applied": True,
            "within_state_limits": False,
        }
        raise DirectorContextBudgetExceeded(
            "DirectorStateV2 remains oversized after deterministic compaction",
            size_report=report,
        )
    payload = canonical_json(state, max_bytes=DIRECTOR_STATE_MAX_BYTES)
    report = {
        "schema_version": "1.0",
        "limits": {
            "director_state_bytes": DIRECTOR_STATE_MAX_BYTES,
            "ancestry_bytes": ANCESTRY_MAX_BYTES,
            "historical_outcomes_bytes": HISTORICAL_OUTCOMES_MAX_BYTES,
            "client_owned_estimated_tokens": CLIENT_ESTIMATED_TOKENS_MAX,
        },
        "pre_compaction": _measure_state(pre),
        "post_compaction": _measure_state(state),
        "compaction_applied": canonical_json(
            pre, max_bytes=4 * 1024 * 1024
        )
        != payload,
        "within_state_limits": within_state_limits,
    }
    registries = build_reference_registries(state)
    evidence_registry = registries["evidence_ids"]
    advisory_registry = registries["advisory_target_ids"]
    executable_registry = registries["executable_target_ids"]
    evidence_bytes = canonical_json(
        evidence_registry, max_bytes=128 * 1024
    )
    advisory_bytes = canonical_json(
        advisory_registry, max_bytes=128 * 1024
    )
    executable_bytes = canonical_json(
        executable_registry, max_bytes=128 * 1024
    )
    return PreparedDirectorState(
        state=state,
        pre_compaction=pre,
        size_report=report,
        evidence_registry=evidence_registry,
        evidence_registry_sha256=hashlib.sha256(evidence_bytes).hexdigest(),
        advisory_target_registry=advisory_registry,
        advisory_target_registry_sha256=hashlib.sha256(
            advisory_bytes
        ).hexdigest(),
        executable_target_registry=executable_registry,
        executable_target_registry_sha256=hashlib.sha256(
            executable_bytes
        ).hexdigest(),
        applicable_action_space_sha256=hashlib.sha256(
            canonical_json(
                state["allowed_action_space"], max_bytes=128 * 1024
            )
        ).hexdigest(),
    )


def build_evidence_registry(
    director_state_v2: dict[str, Any],
) -> dict[str, Any]:
    """Build the evidence role from the exact model-facing state."""

    return build_reference_registries(director_state_v2)["evidence_ids"]


def build_reference_registries(
    director_state_v2: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Build separate evidence, advisory and executable reference roles."""

    state = json.loads(
        canonical_json(
            director_state_v2, max_bytes=DIRECTOR_STATE_MAX_BYTES
        )
    )
    state_sha256 = hashlib.sha256(
        canonical_json(state, max_bytes=DIRECTOR_STATE_MAX_BYTES)
    ).hexdigest()
    references: dict[str, dict[str, Any]] = {}

    def add(
        value: Any,
        kind: str,
        path: str,
        *,
        status: str | None = None,
        evidence_allowed: bool = True,
        advisory_allowed: bool = False,
        executable_allowed: bool = False,
    ) -> None:
        if not isinstance(value, str) or not value:
            return
        entry = references.setdefault(
            value,
            {
                "kinds": set(),
                "statuses": set(),
                "json_paths": set(),
                "evidence_allowed": False,
                "advisory_allowed": False,
                "executable_allowed": False,
            },
        )
        entry["kinds"].add(kind)
        entry["json_paths"].add(path)
        if status:
            entry["statuses"].add(status)
        entry["evidence_allowed"] = bool(
            entry["evidence_allowed"] or evidence_allowed
        )
        entry["advisory_allowed"] = bool(
            entry["advisory_allowed"] or advisory_allowed
        )
        entry["executable_allowed"] = bool(
            entry["executable_allowed"] or executable_allowed
        )

    add(
        state.get("source_snapshot_id"),
        "source_snapshot",
        "$.source_snapshot_id",
    )
    artifact_references = state.get("artifact_references")
    if isinstance(artifact_references, list):
        for index, value in enumerate(artifact_references):
            if not isinstance(value, dict):
                continue
            add(
                value.get("id"),
                str(value.get("kind") or "artifact"),
                f"$.artifact_references[{index}].id",
            )
            add(
                value.get("sha256"),
                "artifact_hash",
                f"$.artifact_references[{index}].sha256",
            )

    identifier_kinds = {
        "action_id": "action",
        "candidate_id": "candidate",
        "best_candidate_identifier": "candidate",
        "parent_candidate_id": "candidate",
        "checkpoint_id": "checkpoint",
        "decision_batch_id": "outcome",
        "evidence_id": "evidence",
        "hypothesis_id": "hypothesis",
        "metric_window_id": "outcome",
        "outcome_id": "outcome",
        "outcome_artifact_sha256": "artifact_hash",
        "lane_id": "lane",
    }

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}"
                kind = identifier_kinds.get(str(key))
                if kind is not None:
                    add(child, kind, child_path)
                elif key == "hypothesis_ids" and isinstance(child, list):
                    for index, identifier in enumerate(child):
                        add(
                            identifier,
                            "hypothesis",
                            f"{child_path}[{index}]",
                        )
                visit(child, child_path)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")

    visit(state, "$")
    action_space = state.get("allowed_action_space")
    reference_objects = (
        action_space.get("reference_objects", [])
        if isinstance(action_space, dict)
        else []
    )
    for index, value in enumerate(reference_objects):
        if not isinstance(value, dict):
            continue
        add(
            value.get("id"),
            str(value.get("object_kind") or "reference"),
            f"$.allowed_action_space.reference_objects[{index}].id",
            status=str(value.get("status") or "unknown"),
            evidence_allowed=bool(value.get("evidence_allowed")),
            advisory_allowed=bool(value.get("advisory_allowed")),
            executable_allowed=bool(value.get("executable_allowed")),
        )

    entries = [
        {
            "id": identifier,
            "object_kind": sorted(entry["kinds"])[0],
            "object_kinds": sorted(entry["kinds"]),
            "current_lifecycle_status": (
                sorted(entry["statuses"])[0]
                if entry["statuses"]
                else "visible_evidence"
            ),
            "director_state_json_paths": sorted(entry["json_paths"]),
            "evidence_allowed": bool(entry["evidence_allowed"]),
            "advisory_allowed": bool(entry["advisory_allowed"]),
            "executable_allowed": bool(entry["executable_allowed"]),
        }
        for identifier, entry in sorted(references.items())
    ]

    def registry(role: str, flag: str) -> dict[str, Any]:
        return {
            "schema_version": REFERENCE_REGISTRY_VERSION,
            "role": role,
            "director_state_sha256": state_sha256,
            "references": [
                entry for entry in entries if bool(entry[flag])
            ],
        }

    return {
        "evidence_ids": registry("evidence_ids", "evidence_allowed"),
        "advisory_target_ids": registry(
            "advisory_target_ids", "advisory_allowed"
        ),
        "executable_target_ids": registry(
            "executable_target_ids", "executable_allowed"
        ),
    }


def evidence_registry_ids(
    registry: dict[str, Any],
    *,
    kinds: frozenset[str] | None = None,
) -> frozenset[str]:
    """Return registry IDs, optionally restricted to reference kinds."""

    identifiers: set[str] = set()
    for reference in registry.get("references", []):
        if not isinstance(reference, dict):
            continue
        identifier = reference.get("id")
        reference_kinds = reference.get(
            "object_kinds", reference.get("kinds")
        )
        if not isinstance(identifier, str) or not isinstance(
            reference_kinds, list
        ):
            continue
        if kinds is None or kinds.intersection(
            str(value) for value in reference_kinds
        ):
            identifiers.add(identifier)
    return frozenset(identifiers)


def complete_context_size_report(
    prepared: PreparedDirectorState,
    *,
    prompt: str,
    base_instructions: str,
    output_schema: dict[str, Any],
    mode: DirectorContextMode,
) -> dict[str, Any]:
    """Measure the exact client-owned bytes and enforce the pre-turn gate."""

    prompt_bytes = len(prompt.encode("utf-8"))
    base_bytes = len(base_instructions.encode("utf-8"))
    schema_bytes = len(
        canonical_json(output_schema, max_bytes=1024 * 1024)
    )
    total_bytes = prompt_bytes + base_bytes + schema_bytes
    approximate_tokens = ceil(total_bytes / 4)
    report = json.loads(json.dumps(prepared.size_report))
    report.update(
        {
            "context_mode": mode.value,
            "prompt_bytes": prompt_bytes,
            "base_instructions_bytes": base_bytes,
            "output_schema_bytes": schema_bytes,
            "client_owned_input_bytes": total_bytes,
            "client_owned_estimated_tokens": approximate_tokens,
            "token_estimate_method": (
                "ceil(client-owned UTF-8 bytes / 4); estimate only"
            ),
            "within_client_token_limit": (
                approximate_tokens <= CLIENT_ESTIMATED_TOKENS_MAX
            ),
        }
    )
    return report


def _unbounded_state(snapshot: dict[str, Any]) -> dict[str, Any]:
    campaign = dict(snapshot.get("campaign") or {})
    target = dict(snapshot.get("target") or {})
    actions = [
        value
        for value in snapshot.get("recent_actions", [])
        if isinstance(value, dict)
    ]
    batch_actions = [
        value
        for value in actions
        if isinstance(value.get("observed_effect"), dict)
        and "evaluation_count" in value["observed_effect"]
    ]
    outcomes = [
        _outcome_summary(value, historical=index > 0)
        for index, value in enumerate(batch_actions)
    ]
    latest_action = batch_actions[0] if batch_actions else None
    latest_effect = (
        dict(latest_action["observed_effect"])
        if latest_action is not None
        else {}
    )
    all_effects = [
        dict(value["observed_effect"]) for value in batch_actions
    ]
    ancestry = dict(latest_effect.get("mutation_ancestry") or {})
    global_records = list(
        ancestry.get("global_record_improvements")
        or ancestry.get("global_record_samples")
        or []
    )
    final_ancestors = [
        value
        for value in ancestry.get("final_best_ancestry", [])
        if isinstance(value, dict) and value.get("accepted") is not False
    ]
    catalog = action_catalog()
    used_evaluations = sum(
        int(value.get("evaluation_count", 0)) for value in all_effects
    )
    remaining_evaluations = _remaining_evaluations(all_effects)
    limit_evaluations = (
        used_evaluations + remaining_evaluations
        if remaining_evaluations is not None
        else None
    )
    state = {
        "schema_version": DIRECTOR_STATE_VERSION,
        "source_snapshot_id": str(snapshot.get("snapshot_id", "")),
        "target": {
            "statement_id": str(target.get("target_id", "")),
            "definition_sha256": str(
                target.get("immutable_definition_hash", "")
            ),
            "status": str(campaign.get("state", "unknown")),
            "status_timestamp": str(snapshot.get("created_at", "")),
            "success_authority": str(
                target.get("success_authority", "M4_independent_verifier")
            ),
        },
        "campaign_budget": {
            "stop_mode": campaign.get("stop_mode"),
            "wall_seconds": {
                "elapsed": campaign.get("elapsed_seconds"),
                "remaining": campaign.get("remaining_seconds"),
            },
            "evaluations": {
                "limit": limit_evaluations,
                "used": used_evaluations,
                "remaining": remaining_evaluations,
            },
        },
        "best_ever_result": _best_result(snapshot, outcomes),
        "_all_outcomes": outcomes,
        "plateau": latest_effect.get("plateau_signal"),
        "operator_aggregates": _operator_aggregates(all_effects),
        "stage_timing_percentages": _timing_percentages(latest_effect),
        "exact_verifier": _verifier_summary(
            latest_effect.get("verifier_result")
        ),
        "parameter_effects": (
            dict(latest_action.get("parameter_effects") or {})
            if latest_action is not None
            else {}
        ),
        "previous_hypothesis": (
            {
                "hypothesis_ids": list(
                    latest_action.get(
                        "previous_director_hypothesis_ids", []
                    )
                ),
                "expected_signal": latest_action.get("expected_effect"),
                "expected_signal_occurred": latest_action.get(
                    "expectation_met"
                ),
            }
            if latest_action is not None
            else None
        ),
        "ancestry": {
            "global_record_summaries": [
                _ancestry_summary(value) for value in global_records
            ],
            "final_best_accepted_ancestors": [
                _ancestry_summary(value) for value in final_ancestors
            ],
        },
        "artifact_references": _artifact_references(
            snapshot, batch_actions[:MAX_OUTCOMES]
        ),
    }
    state["allowed_action_space"] = _applicable_action_space(
        snapshot, state, catalog
    )
    return state


def _applicable_action_space(
    snapshot: dict[str, Any],
    state: dict[str, Any],
    catalog: dict[str, Any],
) -> dict[str, Any]:
    """Return only actions with at least one legal target or construction."""

    lanes = [
        value
        for value in snapshot.get("lanes", [])
        if isinstance(value, dict) and isinstance(value.get("lane_id"), str)
    ]
    active_lanes = [
        value for value in lanes if value.get("state") in ACTIVE_LANE_STATES
    ]
    active_lane_ids = sorted(str(value["lane_id"]) for value in active_lanes)
    maximum_lanes = int(
        (snapshot.get("resources") or {}).get("max_active_lanes", 1)
    )
    best_result = state.get("best_ever_result")
    retained_candidate = (
        best_result.get("candidate_id")
        if isinstance(best_result, dict)
        else None
    )
    candidate_ids = (
        [str(retained_candidate)]
        if isinstance(retained_candidate, str) and retained_candidate
        else []
    )
    checkpoint_ids = sorted(
        {
            str(value)
            for value in _values_for_keys(state, {"checkpoint_id"})
            if isinstance(value, str) and value
        }
    )
    visible_ids = sorted(
        {
            str(value)
            for value in _values_for_keys(
                state,
                {
                    "action_id",
                    "candidate_id",
                    "best_candidate_identifier",
                    "checkpoint_id",
                    "decision_batch_id",
                    "evidence_id",
                    "hypothesis_id",
                    "lane_id",
                    "metric_window_id",
                    "outcome_id",
                },
            )
            if isinstance(value, str) and value
        }
        | {str(state.get("source_snapshot_id", ""))}
    )

    actions: list[str] = []
    explanations: dict[str, str] = {}

    def expose(action: str, reason: str) -> None:
        actions.append(action)
        explanations[action] = reason

    if len(active_lanes) < maximum_lanes:
        expose(
            "start_lane",
            "capacity exists for one reviewed new search lane",
        )
    if active_lane_ids:
        expose(
            "patch_lane",
            "at least one active lane has implemented patchable controls",
        )
        if checkpoint_ids:
            expose(
                "fork_lane",
                "an active lane and a retained checkpoint are available",
            )
        expose(
            "restart_lane",
            "at least one active lane can be restarted from a reviewed source",
        )
        expose(
            "stop_lane",
            "at least one active lane is an executable stop target",
        )
        expose(
            "reallocate_resources",
            "at least one active lane can receive a resource allocation",
        )
    if candidate_ids:
        expose(
            "promote_candidate",
            "at least one retained candidate is available",
        )
    if visible_ids:
        expose(
            "request_diagnostic",
            "at least one submitted evidence subject is available",
        )
    if candidate_ids:
        expose(
            "schedule_verification",
            "at least one retained candidate is available for M4 verification",
        )
    expose(
        "set_review_trigger",
        "review scheduling is lane-independent",
    )

    active_by_id = {str(value["lane_id"]): value for value in active_lanes}
    reference_objects: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add_reference(
        identifier: str,
        kind: str,
        status: str,
        *,
        advisory: bool,
        executable: bool,
    ) -> None:
        key = (identifier, kind)
        if not identifier or key in seen:
            return
        seen.add(key)
        reference_objects.append(
            {
                "id": identifier,
                "object_kind": kind,
                "status": status,
                "evidence_allowed": True,
                "advisory_allowed": advisory,
                "executable_allowed": executable,
            }
        )

    for lane in lanes:
        lane_id = str(lane["lane_id"])
        status = str(lane.get("state") or "unknown")
        add_reference(
            lane_id,
            "lane",
            status,
            advisory=True,
            executable=lane_id in active_by_id,
        )
    for lane_id in sorted(
        {
            str(value)
            for value in _values_for_keys(state, {"lane_id"})
            if isinstance(value, str) and value
        }
    ):
        if lane_id not in {str(value["lane_id"]) for value in lanes}:
            add_reference(
                lane_id,
                "lane",
                "historical",
                advisory=True,
                executable=False,
            )
    for candidate_id in candidate_ids:
        add_reference(
            candidate_id,
            "candidate",
            "retained",
            advisory=True,
            executable=True,
        )
    for checkpoint_id in checkpoint_ids:
        add_reference(
            checkpoint_id,
            "checkpoint",
            "retained",
            advisory=True,
            executable=bool(active_lane_ids),
        )

    result = {
        "catalog_version": catalog["catalog_version"],
        "actions": actions,
        "action_applicability": explanations,
        "active_executable_lane_ids": active_lane_ids,
        "historical_lane_ids": sorted(
            str(value["lane_id"])
            for value in lanes
            if str(value["lane_id"]) not in active_by_id
        ),
        "candidate_target_ids": candidate_ids,
        "reference_objects": reference_objects,
        "algorithms": catalog["algorithms"],
        "graph_families": [
            value["id"] for value in catalog["graph_families"]
        ],
        "diagnostics": catalog["diagnostics"],
        "review_events": catalog["review_events"],
        "parameter_domains": catalog["parameter_domains"],
        "algorithm_parameters": catalog["algorithm_parameters"],
        "mutation_operators": catalog["mutation_operators"],
        "mutation_weights_contract": catalog["mutation_weights_contract"],
    }
    if checkpoint_ids:
        result["checkpoint_target_ids"] = checkpoint_ids
    return result


def _values_for_keys(value: Any, keys: set[str]) -> list[Any]:
    values: list[Any] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in keys:
                values.append(child)
            values.extend(_values_for_keys(child, keys))
    elif isinstance(value, list):
        for child in value:
            values.extend(_values_for_keys(child, keys))
    return values


def _outcome_summary(
    action: dict[str, Any], *, historical: bool
) -> dict[str, Any]:
    effect = dict(action["observed_effect"])
    keys = (
        "action_id",
        "decision_batch_id",
        "lane_id",
        "metric_window_id",
        "algorithm",
        "graph_family",
        "graph_order",
        "seed",
        "evaluation_count",
        "elapsed_seconds",
        "throughput",
        "peak_rss_bytes",
        "best_evaluation",
        "plateau_evaluations",
        "accepted",
        "duplicates",
        "global_record_count",
        "diversity",
        "actual_restart_count",
        "actual_restart_occurred",
        "score_counts_truncated_by_witness_cap",
        "termination_reason",
        "best_candidate_identifier",
        "outcome_artifact_ref",
        "outcome_artifact_sha256",
    )
    result = {key: effect[key] for key in keys if key in effect}
    for key in ("initial_score", "best_score"):
        value = effect.get(key)
        if isinstance(value, dict):
            result[key] = {
                item: value[item]
                for item in ("ordering_key", "witness_counts", "complete")
                if item in value
            }
    result["operator_statistics"] = effect.get("operator_statistics", {})
    result["verifier"] = _verifier_summary(effect.get("verifier_result"))
    result["historical_summary"] = historical
    return result


def _best_result(
    snapshot: dict[str, Any], outcomes: list[dict[str, Any]]
) -> dict[str, Any] | None:
    global_best = snapshot.get("global_best")
    if isinstance(global_best, dict):
        return {
            key: global_best[key]
            for key in (
                "candidate_id",
                "evidence_id",
                "lane_id",
                "checkpoint_id",
                "score",
                "order",
                "size",
                "minimum_degree",
                "certification_status",
            )
            if key in global_best
        }
    candidates = [
        value for value in outcomes if isinstance(value.get("best_score"), dict)
    ]
    return (
        min(
            candidates,
            key=lambda value: tuple(
                value["best_score"].get("ordering_key", [10**18])
            ),
        )
        if candidates
        else None
    )


def _remaining_evaluations(
    effects: list[dict[str, Any]],
) -> int | None:
    if not effects:
        return None
    plateau = effects[0].get("plateau_signal")
    if not isinstance(plateau, dict):
        return None
    value = plateau.get("remaining_evaluation_budget")
    return int(value) if isinstance(value, int) else None


def _operator_aggregates(
    effects: list[dict[str, Any]],
) -> dict[str, Any]:
    result: dict[str, dict[str, int | float]] = {}
    for effect in effects:
        operators = (
            effect.get("operator_statistics", {})
            .get("mutation_operators", {})
        )
        for name, values in operators.items():
            target = result.setdefault(
                str(name),
                {"uses": 0, "accepted": 0, "global_records": 0},
            )
            for key in ("uses", "accepted", "global_records"):
                target[key] = int(target[key]) + int(values.get(key, 0))
    for values in result.values():
        uses = int(values["uses"])
        values["yield"] = (
            float(values["global_records"]) / uses if uses else 0.0
        )
        values["acceptance_rate"] = (
            float(values["accepted"]) / uses if uses else 0.0
        )
    return result


def _timing_percentages(effect: dict[str, Any]) -> dict[str, float]:
    timing = effect.get("timing")
    if not isinstance(timing, dict):
        return {}
    total = float(timing.get("search_loop_seconds") or 0.0)
    counters = timing.get("counters_seconds")
    if total <= 0 or not isinstance(counters, dict):
        return {}
    return {
        str(key): round(100.0 * float(value) / total, 6)
        for key, value in counters.items()
    }


def _verifier_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {
        key: value[key]
        for key in (
            "status",
            "complete",
            "implementation",
            "message",
            "elapsed_seconds",
            "error",
        )
        if key in value
    }


def _ancestry_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: value[key]
        for key in (
            "candidate_id",
            "parent_candidate_id",
            "mutation_operator",
            "evaluation",
            "global_record",
            "score_before",
            "score_after",
            "witness_counts_before",
            "witness_counts_after",
        )
        if key in value
    }


def _artifact_references(
    snapshot: dict[str, Any], actions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    references = [
        {
            "kind": "snapshot",
            "id": str(snapshot.get("snapshot_id", "")),
            "artifact_ref": None,
            "sha256": _unbounded_json_sha256(snapshot),
        }
    ]
    seen: set[str] = set()
    for action in actions:
        effect = action["observed_effect"]
        digest = effect.get("outcome_artifact_sha256")
        if not isinstance(digest, str) or digest in seen:
            continue
        seen.add(digest)
        references.append(
            {
                "kind": "batch_outcome",
                "id": str(action.get("action_id", "")),
                "artifact_ref": effect.get("outcome_artifact_ref"),
                "sha256": digest,
            }
        )
    best = snapshot.get("global_best")
    if isinstance(best, dict):
        references.append(
            {
                "kind": "best_candidate",
                "id": best.get("candidate_id"),
                "artifact_ref": None,
                "sha256": None,
            }
        )
    return references


def _measure_state(state: dict[str, Any]) -> dict[str, Any]:
    outcomes = state.get("_all_outcomes")
    if not isinstance(outcomes, list):
        outcomes = [
            value
            for value in [
                state.get("latest_batch_outcome"),
                *state.get("previous_outcomes", []),
            ]
            if isinstance(value, dict)
        ]
    ancestry = dict(state.get("ancestry") or {})
    historical = state.get("previous_outcomes")
    if not isinstance(historical, list):
        historical = outcomes[1:]
    return {
        "director_state_bytes": _json_size(state),
        "ancestry_bytes": _json_size(ancestry),
        "historical_outcomes_bytes": _json_size(historical),
        "outcome_count": len(outcomes),
        "global_record_ancestry_count": len(
            ancestry.get("global_record_summaries", [])
        ),
        "final_best_ancestry_count": len(
            ancestry.get("final_best_accepted_ancestors", [])
        ),
        "duplicated_key_estimate": duplicated_key_estimate(state),
    }


def duplicated_key_estimate(value: Any) -> dict[str, int]:
    counts: dict[str, int] = {}

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                counts[str(key)] = counts.get(str(key), 0) + 1
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    repeated = {key: count for key, count in counts.items() if count > 1}
    return {
        "repeated_key_names": len(repeated),
        "duplicate_key_occurrences": sum(
            count - 1 for count in repeated.values()
        ),
        "duplicate_key_bytes": sum(
            (count - 1)
            * len(
                json.dumps(
                    key, ensure_ascii=True, separators=(",", ":")
                ).encode("ascii")
            )
            for key, count in repeated.items()
        ),
    }


def _json_size(value: Any) -> int:
    return len(canonical_json(value, max_bytes=4 * 1024 * 1024))


def _unbounded_json_sha256(value: Any) -> str:
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    for chunk in encoder.iterencode(value):
        digest.update(chunk.encode("ascii"))
    return digest.hexdigest()
