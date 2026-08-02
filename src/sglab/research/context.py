from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from math import ceil
from typing import Any
import hashlib
import json

from .catalog import (
    PROPOSAL_RANKING_MUTATION_ALGORITHMS,
    RANDOM_RESTART_UNRANKED_INSTRUCTION,
    REVIEWED_PROPOSAL_RANKING_CATALOG_ID,
    action_catalog,
    normalize_proposal_ranking_catalog_id,
)
from .continuity import (
    ScientificMemoryCompactor,
    ScientificMemoryPolicy,
    ScientificStateOverflow,
)
from .protocol import canonical_json


DIRECTOR_STATE_VERSION = "2.0"
DIRECTOR_STATE_MAX_BYTES = 32 * 1024
ANCESTRY_MAX_BYTES = 8 * 1024
HISTORICAL_OUTCOMES_MAX_BYTES = 12 * 1024
CLIENT_ESTIMATED_TOKENS_MAX = 32_000
MAX_OUTCOMES = 3
MAX_GLOBAL_RECORD_SUMMARIES = 8
MAX_FINAL_BEST_ANCESTORS = 8
EVIDENCE_REGISTRY_VERSION = "1.0"
REFERENCE_REGISTRY_VERSION = "2.0"
REFERENCE_SOURCE_MAX_BYTES = 4 * 1024 * 1024
ACTIVE_LANE_STATES = frozenset(
    {"starting", "running", "paused", "stopping"}
)
MODEL_ALIAS_VERSION = "1.0"
MODEL_ALIAS_LIMITS = {
    "lane": 16,
    "candidate": 16,
    "checkpoint": 16,
    "hypothesis": 16,
    "evidence": 32,
    "outcome": 16,
    "action": 16,
}


class DirectorContextMode(StrEnum):
    PERSISTENT_THREAD = "persistent_thread"
    COMPACTED_THREAD = "compacted_thread"
    STATELESS_TURNS = "stateless_turns"


DEFAULT_DIRECTOR_CONTEXT_MODE = DirectorContextMode.STATELESS_TURNS
CONTEXT_RECOMMENDATION_BASIS = "single controlled S2/P2 pair"


class DirectorContextBudgetExceeded(RuntimeError):
    def __init__(
        self, message: str, *, size_report: dict[str, Any] | None = None
    ):
        super().__init__(message)
        self.size_report = size_report


@dataclass(frozen=True, slots=True)
class PreparedDirectorState:
    state: dict[str, Any]
    model_state: dict[str, Any]
    alias_registry: dict[str, Any]
    alias_registry_sha256: str
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
            "continuity": {"type": "object"},
        },
    }


def prepare_director_state_v2(
    snapshot: dict[str, Any],
    *,
    hard_limit_bytes: int = DIRECTOR_STATE_MAX_BYTES,
) -> PreparedDirectorState:
    """Build and deterministically compact model-facing scientific state."""

    pre, state = _director_state_before_total_compaction(snapshot)
    authoritative_state = json.loads(json.dumps(state))
    ancestry = state["ancestry"]
    while _json_size(state) > hard_limit_bytes:
        if ancestry["final_best_accepted_ancestors"]:
            ancestry["final_best_accepted_ancestors"].pop(0)
        elif ancestry["global_record_summaries"]:
            ancestry["global_record_summaries"].pop(0)
        elif state["previous_outcomes"]:
            state["previous_outcomes"].pop()
        else:
            break
    if _json_size(state) > hard_limit_bytes:
        try:
            state = ScientificMemoryCompactor(
                ScientificMemoryPolicy(
                    soft_limit_bytes=min(24 * 1024, hard_limit_bytes),
                    hard_limit_bytes=hard_limit_bytes,
                )
            ).project(state)
        except ScientificStateOverflow:
            pass
    if _json_size(state) > hard_limit_bytes:
        _bound_state_targets_for_transport(state)
    within_state_limits = (
        _json_size(state) <= hard_limit_bytes
        and _json_size(ancestry) <= ANCESTRY_MAX_BYTES
        and _json_size(state["previous_outcomes"])
        <= HISTORICAL_OUTCOMES_MAX_BYTES
    )
    if not within_state_limits:
        report = {
            "schema_version": "1.0",
            "limits": {
                "director_state_bytes": hard_limit_bytes,
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
    payload = canonical_json(state, max_bytes=hard_limit_bytes)
    report = {
        "schema_version": "1.0",
        "limits": {
            "director_state_bytes": hard_limit_bytes,
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
    registries = build_reference_registries(authoritative_state)
    model_state, alias_registry = _model_alias_projection(
        authoritative_state, registries
    )
    alias_bytes = canonical_json(alias_registry, max_bytes=128 * 1024)
    evidence_registry = registries["evidence_ids"]
    advisory_registry = registries["advisory_target_ids"]
    executable_registry = registries["executable_target_ids"]
    evidence_bytes = canonical_json(
        evidence_registry, max_bytes=REFERENCE_SOURCE_MAX_BYTES
    )
    advisory_bytes = canonical_json(
        advisory_registry, max_bytes=REFERENCE_SOURCE_MAX_BYTES
    )
    executable_bytes = canonical_json(
        executable_registry, max_bytes=REFERENCE_SOURCE_MAX_BYTES
    )
    return PreparedDirectorState(
        state=state,
        model_state=model_state,
        alias_registry=alias_registry,
        alias_registry_sha256=hashlib.sha256(alias_bytes).hexdigest(),
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


def _bound_state_targets_for_transport(state: dict[str, Any]) -> None:
    """Keep the durable prompt-side state bounded after registry growth.

    Full target identity remains in the committed snapshot and the private
    reference/alias artifacts.  This transport copy only needs enough IDs to
    describe the current bounded model projection; validation uses the
    authoritative registries built before this reduction.
    """

    action_space = state.get("allowed_action_space")
    if isinstance(action_space, dict):
        for key, limit in (
            ("active_executable_lane_ids", MODEL_ALIAS_LIMITS["lane"]),
            ("candidate_target_ids", MODEL_ALIAS_LIMITS["candidate"]),
            ("diagnostic_subject_ids", MODEL_ALIAS_LIMITS["evidence"]),
            ("checkpoint_target_ids", MODEL_ALIAS_LIMITS["checkpoint"]),
            ("historical_lane_ids", MODEL_ALIAS_LIMITS["lane"]),
        ):
            values = action_space.get(key)
            if isinstance(values, list) and len(values) > limit:
                action_space[key] = values[:limit]
        for key in ("active_lane_versions", "lane_lifecycle_states"):
            values = action_space.get(key)
            if isinstance(values, dict) and len(values) > MODEL_ALIAS_LIMITS["lane"]:
                action_space[key] = dict(
                    list(sorted(values.items()))[: MODEL_ALIAS_LIMITS["lane"]]
                )
    continuity = state.get("continuity")
    if not isinstance(continuity, dict):
        return
    for key, limit in (
        ("current_executable_candidate_ids", MODEL_ALIAS_LIMITS["candidate"]),
        ("current_executable_checkpoint_ids", MODEL_ALIAS_LIMITS["checkpoint"]),
        ("candidate_ledger", MODEL_ALIAS_LIMITS["candidate"]),
        ("lane_and_checkpoint_ledger", MODEL_ALIAS_LIMITS["lane"]),
        ("hypothesis_ledger", MODEL_ALIAS_LIMITS["hypothesis"]),
        ("exact_verifier_outcomes", 8),
        ("validation_feedback", MODEL_ALIAS_LIMITS["action"]),
    ):
        values = continuity.get(key)
        if isinstance(values, list) and len(values) > limit:
            continuity[key] = values[:limit]
    artifacts = state.get("artifact_references")
    if isinstance(artifacts, list) and len(artifacts) > 8:
        state["artifact_references"] = artifacts[:8]


def director_state_v2_memory_input(
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Build section-bounded state before scientific-memory compaction."""

    _, state = _director_state_before_total_compaction(snapshot)
    return state


def _director_state_before_total_compaction(
    snapshot: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    projected = snapshot.get("scientific_memory_projection")
    if isinstance(projected, dict):
        pre = json.loads(json.dumps(projected))
        state = json.loads(json.dumps(projected))
        # The scientific-memory projection is a bounded model summary, not
        # the authority for current executable targets.  Overlay the
        # explicitly persisted continuity fields from this committed
        # snapshot so a stale projection cannot resurrect lanes or candidates
        # in a fresh zero-lane campaign.
        snapshot_continuity = snapshot.get("continuity")
        if isinstance(snapshot_continuity, dict):
            state_continuity = state.get("continuity")
            if not isinstance(state_continuity, dict):
                state_continuity = {}
                state["continuity"] = state_continuity
            for key in (
                "current_executable_candidate_ids",
                "current_executable_checkpoint_ids",
                "candidate_ledger",
                "lane_and_checkpoint_ledger",
                "exact_verifier_outcomes",
                "hypothesis_ledger",
            ):
                if key in snapshot_continuity:
                    state_continuity[key] = json.loads(
                        json.dumps(snapshot_continuity[key])
                    )
        # A newly committed campaign can legitimately have an old memory
        # projection from a prior failed attempt.  When the authoritative
        # snapshot has no lanes and no recent actions, clear projected
        # outcome/best-result summaries as well; otherwise the model would be
        # told to continue a portfolio that does not exist.
        if (
            isinstance(snapshot.get("lanes"), list)
            and not snapshot["lanes"]
            and isinstance(snapshot.get("recent_actions"), list)
            and not snapshot["recent_actions"]
        ):
            state["best_ever_result"] = None
            state["latest_batch_outcome"] = None
            state["previous_outcomes"] = []
            state["plateau"] = None
            state["operator_aggregates"] = {}
            state["stage_timing_percentages"] = {}
            state["exact_verifier"] = None
            state["parameter_effects"] = {}
            state["previous_hypothesis"] = None
    else:
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
    return pre, state


def build_evidence_registry(
    director_state_v2: dict[str, Any],
) -> dict[str, Any]:
    """Build the evidence role from the exact model-facing state."""

    return build_reference_registries(director_state_v2)["evidence_ids"]


def model_alias_ids(
    registry: dict[str, Any], *, kind: str | None = None
) -> frozenset[str]:
    """Return only short aliases exposed to the model for one role/kind."""

    values: set[str] = set()
    for entry in registry.get("aliases", []):
        if not isinstance(entry, dict):
            continue
        if kind is not None and entry.get("kind") != kind:
            continue
        alias = entry.get("alias")
        if isinstance(alias, str) and alias:
            values.add(alias)
    return frozenset(values)


def _model_alias_projection(
    state: dict[str, Any],
    registries: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a bounded model projection and its private durable-ID registry.

    The durable state remains unchanged for host validation.  This projection
    deliberately exposes only semantic summaries and short per-turn aliases;
    the alias-to-durable mapping is written to a private artifact by the
    Director turn boundary.
    """

    raw = json.loads(
        canonical_json(state, max_bytes=REFERENCE_SOURCE_MAX_BYTES)
    )
    continuity = raw.get("continuity")
    continuity = continuity if isinstance(continuity, dict) else {}
    action_space = raw.get("allowed_action_space")
    action_space = action_space if isinstance(action_space, dict) else {}
    prefixes = {
        "snapshot": "S",
        "lane": "L",
        "candidate": "C",
        "checkpoint": "K",
        "hypothesis": "H",
        "evidence": "E",
        "outcome": "O",
        "action": "A",
    }
    counters: Counter[str] = Counter()
    durable_to_alias: dict[tuple[str, str], str] = {}
    aliases: list[dict[str, str]] = []

    def add(kind: str, value: Any) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        key = (kind, value)
        existing = durable_to_alias.get(key)
        if existing is not None:
            return existing
        limit = MODEL_ALIAS_LIMITS.get(kind, 16)
        if counters[kind] >= limit:
            return None
        counters[kind] += 1
        alias = f"{prefixes.get(kind, 'R')}{counters[kind]}"
        durable_to_alias[key] = alias
        aliases.append(
            {"alias": alias, "durable_id": value, "kind": kind}
        )
        return alias

    snapshot_alias = add("snapshot", raw.get("source_snapshot_id"))

    lane_states = action_space.get("lane_lifecycle_states", {})
    lane_states = lane_states if isinstance(lane_states, dict) else {}
    active_lane_ids = sorted(
        {
            str(value)
            for value in action_space.get("active_executable_lane_ids", [])
            if isinstance(value, str) and value
        }
    )
    active_lane_ids = active_lane_ids[: MODEL_ALIAS_LIMITS["lane"]]
    for value in active_lane_ids:
        add("lane", value)

    candidate_rows = {
        str(item.get("candidate_id")): item
        for item in continuity.get("candidate_ledger", [])
        if isinstance(item, dict)
        and isinstance(item.get("candidate_id"), str)
    }
    raw_candidate_ids = {
        str(value)
        for value in (
            list(action_space.get("candidate_target_ids", []))
            + list(continuity.get("current_executable_candidate_ids", []))
        )
        if isinstance(value, str) and value
    }
    explicit_candidate_targets = (
        "current_executable_candidate_ids" in continuity
        or "candidate_target_ids" in action_space
    )
    best_result = raw.get("best_ever_result")
    if isinstance(best_result, dict) and isinstance(
        best_result.get("candidate_id"), str
    ) and (
        not explicit_candidate_targets
        or str(best_result["candidate_id"]) in raw_candidate_ids
    ):
        raw_candidate_ids.add(str(best_result["candidate_id"]))
    verifier_candidates = {
        str(item.get("candidate_id"))
        for item in continuity.get("exact_verifier_outcomes", [])
        if isinstance(item, dict)
        and isinstance(item.get("candidate_id"), str)
        and item.get("certification_status") not in {
            "INVALID_CANDIDATE",
            "rejected",
        }
    }
    if not explicit_candidate_targets:
        raw_candidate_ids.update(verifier_candidates)
    else:
        raw_candidate_ids.update(
            value for value in verifier_candidates if value in raw_candidate_ids
        )

    def candidate_key(value: str) -> tuple[Any, ...]:
        item = candidate_rows.get(value, {})
        status = str(item.get("state") or "")
        status_rank = {"promoted": 0, "retained": 1}.get(status, 2)
        score = item.get("score")
        ordering = (
            tuple(score.get("ordering_key", []))
            if isinstance(score, dict)
            else (10**18,)
        )
        return (status_rank, ordering, value)

    ordered_candidates = sorted(raw_candidate_ids, key=candidate_key)
    selected_candidate_ids: list[str] = []
    priority_candidates: list[str] = []
    if isinstance(best_result, dict) and isinstance(
        best_result.get("candidate_id"), str
    ):
        best_candidate_id = str(best_result["candidate_id"])
        if best_candidate_id in raw_candidate_ids:
            priority_candidates.append(best_candidate_id)
    priority_candidates.extend(
        value for value in sorted(verifier_candidates) if value in raw_candidate_ids
    )
    priority_candidates.extend(ordered_candidates)
    for value in priority_candidates:
        if not isinstance(value, str) or value in selected_candidate_ids:
            continue
        if len(selected_candidate_ids) >= MODEL_ALIAS_LIMITS["candidate"]:
            break
        selected_candidate_ids.append(value)
        add("candidate", value)

    raw_checkpoint_ids = {
        str(value)
        for value in (
            list(action_space.get("checkpoint_target_ids", []))
            + list(continuity.get("current_executable_checkpoint_ids", []))
        )
        if isinstance(value, str) and value
    }
    lane_ledger = continuity.get("lane_and_checkpoint_ledger", [])
    checkpoint_priority: list[str] = []
    if isinstance(lane_ledger, list):
        for lane_id in active_lane_ids:
            lane_checkpoints = [
                item
                for item in lane_ledger
                if isinstance(item, dict)
                and item.get("lane_id") == lane_id
                and isinstance(item.get("checkpoint_id"), str)
                and item.get("checkpoint_id")
            ]
            lane_checkpoints.sort(
                key=lambda item: (
                    -(
                        float(item.get("telemetry_high_water", 0))
                        if isinstance(
                            item.get("telemetry_high_water"), (int, float)
                        )
                        else 0.0
                    ),
                    str(item.get("checkpoint_id")),
                )
            )
            for item in lane_checkpoints[:2]:
                checkpoint_priority.append(str(item["checkpoint_id"]))
                raw_checkpoint_ids.add(str(item["checkpoint_id"]))
    checkpoint_priority.extend(
        value for value in sorted(raw_checkpoint_ids) if value not in checkpoint_priority
    )
    for value in checkpoint_priority[: MODEL_ALIAS_LIMITS["checkpoint"]]:
        add("checkpoint", value)

    raw_hypotheses = [
        str(item.get("hypothesis_id"))
        for item in continuity.get("hypothesis_ledger", [])
        if isinstance(item, dict)
        and isinstance(item.get("hypothesis_id"), str)
    ]
    for value in sorted(set(raw_hypotheses))[: MODEL_ALIAS_LIMITS["hypothesis"]]:
        add("hypothesis", value)

    for node in (raw.get("previous_outcomes", []), raw.get("artifact_references", [])):
        if not isinstance(node, list):
            continue
        for item in node:
            if not isinstance(item, dict):
                continue
            action_id = item.get("action_id")
            batch_id = item.get("decision_batch_id")
            if isinstance(action_id, str):
                add("action", action_id)
            if isinstance(batch_id, str):
                add("outcome", batch_id)

    selected_target_ids = (
        set(active_lane_ids)
        | set(selected_candidate_ids)
        | raw_checkpoint_ids
        | set(raw_hypotheses)
    )
    evidence_refs = registries.get("evidence_ids", {}).get("references", [])
    evidence_candidates: list[str] = []
    for reference in evidence_refs:
        if not isinstance(reference, dict):
            continue
        identifier = reference.get("id")
        kinds = set(reference.get("object_kinds", []))
        if not isinstance(identifier, str) or not identifier:
            continue
        relevant = identifier in selected_target_ids or bool(
            kinds.intersection({"hypothesis", "verification", "outcome"})
        )
        if not relevant and identifier.startswith("candidate-summary:"):
            relevant = identifier.removeprefix("candidate-summary:") in set(
                selected_candidate_ids
            )
        if relevant:
            evidence_candidates.append(identifier)
    for value in sorted(set(evidence_candidates))[: MODEL_ALIAS_LIMITS["evidence"]]:
        add("evidence", value)

    def alias_for(kind: str, value: Any) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        return durable_to_alias.get((kind, value))

    id_keys = {
        "source_snapshot_id": "snapshot",
        "snapshot_id": "snapshot",
        "lane_id": "lane",
        "parent_lane_id": "lane",
        "candidate_id": "candidate",
        "best_candidate_identifier": "candidate",
        "parent_candidate_id": "candidate",
        "checkpoint_id": "checkpoint",
        "checkpoint_ref": "checkpoint",
        "decision_batch_id": "outcome",
        "metric_window_id": "outcome",
        "outcome_id": "outcome",
        "action_id": "action",
        "hypothesis_id": "hypothesis",
        "evidence_id": "evidence",
        "lane_ref": "lane",
        "candidate_ref": "candidate",
    }
    list_keys = {
        "candidate_ids": "candidate",
        "current_executable_candidate_ids": "candidate",
        "checkpoint_ids": "checkpoint",
        "current_executable_checkpoint_ids": "checkpoint",
        "hypothesis_ids": "hypothesis",
        "evidence_ids": "evidence",
    }

    def looks_durable(value: str) -> bool:
        return value.startswith(
            (
                "candidate-",
                "checkpoint-",
                "lane-",
                "hyp-",
                "action-",
                "decision-batch-",
                "app-turn-",
                "execution-attempt-",
                "campaign-",
                "snapshot-",
                "thread-",
            )
        ) or (len(value) == 64 and all(c in "0123456789abcdef" for c in value))

    def sanitize(value: Any, key: str = "") -> Any:
        if key in {"sha256", "artifact_sha256", "definition_sha256"} or key.endswith(
            "_sha256"
        ):
            return "bound"
        if key in {"artifact_ref", "certification_artifact_ref"}:
            return "stored-artifact"
        if key in {"thread_id", "attempt_id", "campaign_id"}:
            return "current"
        if key in id_keys:
            return alias_for(id_keys[key], value) or "unavailable"
        if key == "id" and isinstance(value, str):
            for kind in (
                "evidence",
                "candidate",
                "checkpoint",
                "lane",
                "hypothesis",
                "outcome",
                "action",
            ):
                alias = alias_for(kind, value)
                if alias is not None:
                    return alias
            if looks_durable(value) or value.startswith(
                ("candidate-summary:", "checkpoint-summary:")
            ):
                return "opaque"
        if key in list_keys and isinstance(value, list):
            kind = list_keys[key]
            return [
                alias
                for item in value
                if (alias := alias_for(kind, item)) is not None
            ]
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for child_key, child in value.items():
                if child_key in {"active_lane_versions", "lane_lifecycle_states"} and isinstance(child, dict):
                    result[child_key] = {
                        alias: sanitize(item, child_key)
                        for durable, item in child.items()
                        if (alias := alias_for("lane", durable)) is not None
                    }
                    continue
                result[child_key] = sanitize(child, str(child_key))
            return result
        if isinstance(value, list):
            return [sanitize(item, key) for item in value]
        if isinstance(value, str):
            if looks_durable(value):
                return "opaque"
            return value
        return value

    model = sanitize(raw)
    if not isinstance(model, dict):
        model = {}
    if snapshot_alias is not None:
        model["source_snapshot_id"] = snapshot_alias
    target = model.get("target")
    if isinstance(target, dict):
        target["definition_sha256"] = "bound"

    model_continuity = model.get("continuity")
    if not isinstance(model_continuity, dict):
        model_continuity = {}
        model["continuity"] = model_continuity
    model_continuity["candidate_ledger"] = [
        sanitize(item)
        for item in continuity.get("candidate_ledger", [])
        if isinstance(item, dict)
        and item.get("candidate_id") in selected_candidate_ids
    ][: MODEL_ALIAS_LIMITS["candidate"]]
    model_continuity["hypothesis_ledger"] = [
        sanitize(item)
        for item in continuity.get("hypothesis_ledger", [])
        if isinstance(item, dict)
        and item.get("hypothesis_id") in raw_hypotheses
        and alias_for("hypothesis", item.get("hypothesis_id")) is not None
    ][: MODEL_ALIAS_LIMITS["hypothesis"]]
    model_continuity["lane_and_checkpoint_ledger"] = [
        sanitize(item)
        for item in lane_ledger
        if isinstance(item, dict)
        and item.get("lane_id") in active_lane_ids
    ][: MODEL_ALIAS_LIMITS["lane"]]
    verifier_items = [
        item
        for item in continuity.get("exact_verifier_outcomes", [])
        if isinstance(item, dict)
        and item.get("candidate_id") in selected_candidate_ids
    ][:8]
    model_continuity["exact_verifier_outcomes"] = [
        sanitize(item) for item in verifier_items
    ]
    model_continuity["exact_verifier_status_counts"] = dict(
        Counter(
            str(item.get("certification_status") or item.get("state") or "unknown")
            for item in continuity.get("exact_verifier_outcomes", [])
            if isinstance(item, dict)
        )
    )
    model_continuity["current_executable_candidate_ids"] = [
        alias
        for value in selected_candidate_ids
        if (alias := alias_for("candidate", value)) is not None
    ]
    model_continuity["current_executable_checkpoint_ids"] = [
        alias
        for value in checkpoint_priority[: MODEL_ALIAS_LIMITS["checkpoint"]]
        if (alias := alias_for("checkpoint", value)) is not None
    ]

    model_action_space = model.get("allowed_action_space")
    if not isinstance(model_action_space, dict):
        model_action_space = {}
        model["allowed_action_space"] = model_action_space
    model_action_space["active_executable_lane_ids"] = [
        alias
        for value in active_lane_ids
        if (alias := alias_for("lane", value)) is not None
    ]
    model_action_space["active_lane_versions"] = {
        alias: int(version)
        for value, version in action_space.get("active_lane_versions", {}).items()
        if isinstance(version, int)
        and (alias := alias_for("lane", value)) is not None
    }
    model_action_space["candidate_target_ids"] = [
        alias
        for value in selected_candidate_ids
        if (alias := alias_for("candidate", value)) is not None
    ]
    model_action_space["diagnostic_subject_ids"] = [
        alias
        for value in sorted(
            set(active_lane_ids) | set(selected_candidate_ids)
        )
        if (alias := alias_for("lane", value) or alias_for("candidate", value))
        is not None
    ]
    model_action_space["checkpoint_target_ids"] = [
        alias
        for value in checkpoint_priority[: MODEL_ALIAS_LIMITS["checkpoint"]]
        if (alias := alias_for("checkpoint", value)) is not None
    ]
    historical = action_space.get("historical_lane_ids", [])
    model_action_space.pop("historical_lane_ids", None)
    model_action_space["historical_lane_count"] = (
        len(historical) if isinstance(historical, list) else 0
    )
    model_action_space["lane_lifecycle_states"] = {
        alias: lane_states.get(value, "unknown")
        for value in active_lane_ids
        if (alias := alias_for("lane", value)) is not None
    }
    model_action_space["omitted_target_counts"] = {
        "lanes": max(0, len(action_space.get("active_executable_lane_ids", [])) - len(active_lane_ids)),
        "candidates": max(0, len(raw_candidate_ids) - len(selected_candidate_ids)),
        "checkpoints": max(0, len(raw_checkpoint_ids) - min(len(raw_checkpoint_ids), MODEL_ALIAS_LIMITS["checkpoint"])),
        "evidence": max(0, len(evidence_refs) - len(evidence_candidates)),
    }

    model["artifact_references"] = [
        sanitize(item)
        for item in raw.get("artifact_references", [])[:8]
        if isinstance(item, dict)
    ]
    registry = {
        "schema_version": MODEL_ALIAS_VERSION,
        "role": "model_aliases",
        "snapshot_alias": snapshot_alias,
        "aliases": aliases,
        "omitted_target_counts": model_action_space["omitted_target_counts"],
    }
    return model, registry


def build_reference_registries(
    director_state_v2: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Build separate evidence, advisory and executable reference roles."""

    state = json.loads(
        canonical_json(
            director_state_v2, max_bytes=REFERENCE_SOURCE_MAX_BYTES
        )
    )
    state_sha256 = hashlib.sha256(
        canonical_json(state, max_bytes=REFERENCE_SOURCE_MAX_BYTES)
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
    if isinstance(action_space, dict):
        lane_states = action_space.get("lane_lifecycle_states", {})
        if not isinstance(lane_states, dict):
            lane_states = {}
        role_lists = (
            (
                "active_executable_lane_ids",
                "lane",
                "active",
                True,
            ),
            (
                "historical_lane_ids",
                "lane",
                "historical",
                False,
            ),
            (
                "candidate_target_ids",
                "candidate",
                "retained",
                True,
            ),
            (
                "checkpoint_target_ids",
                "checkpoint",
                "retained",
                bool(action_space.get("active_executable_lane_ids")),
            ),
        )
        for key, kind, status, executable in role_lists:
            values = action_space.get(key, [])
            if not isinstance(values, list):
                continue
            for index, identifier in enumerate(values):
                current_status = (
                    str(lane_states.get(identifier, status))
                    if kind == "lane"
                    else status
                )
                add(
                    identifier,
                    kind,
                    f"$.allowed_action_space.{key}[{index}]",
                    status=current_status,
                    evidence_allowed=True,
                    advisory_allowed=True,
                    executable_allowed=executable,
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
        "continuity": dict(snapshot.get("continuity") or {}),
    }
    # Older persisted snapshots and compact snapshots may keep the exact
    # executable checkpoint IDs only in the bounded scientific-memory
    # projection.  Rehydrate that field before deriving the action space so
    # fork-target validation remains exact and fail-closed.
    continuity = state["continuity"]
    if (
        isinstance(continuity, dict)
        and "current_executable_checkpoint_ids" not in continuity
    ):
        projection = snapshot.get("scientific_memory_projection")
        projected_continuity = (
            projection.get("continuity")
            if isinstance(projection, dict)
            else None
        )
        if isinstance(projected_continuity, dict):
            ids = projected_continuity.get(
                "current_executable_checkpoint_ids"
            )
            if isinstance(ids, list):
                continuity["current_executable_checkpoint_ids"] = list(
                    ids
                )
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
    # A prepared campaign always has a positive lane capacity.  Keep the
    # projection fail-closed for malformed historical snapshots, but never
    # let a stale/empty action list erase the zero-lane bootstrap contract.
    if maximum_lanes < 0:
        maximum_lanes = 0
    active_lane_count = len(active_lanes)
    available_lane_slots = max(0, maximum_lanes - active_lane_count)
    active_lane_versions = {
        str(lane["lane_id"]): int(lane.get("lane_version", 0))
        for lane in sorted(
            active_lanes,
            key=lambda value: str(value["lane_id"]),
        )
    }
    best_result = state.get("best_ever_result")
    retained_candidate = (
        best_result.get("candidate_id")
        if isinstance(best_result, dict)
        else None
    )
    continuity = state.get("continuity")
    current_candidates = (
        continuity.get("current_executable_candidate_ids", [])
        if isinstance(continuity, dict)
        else []
    )
    candidate_ids = sorted(
        {
            str(value)
            for value in current_candidates
            if isinstance(value, str) and value
        }
        | (
            {str(retained_candidate)}
            if (
                not isinstance(continuity, dict)
                or "current_executable_candidate_ids" not in continuity
            )
            and isinstance(retained_candidate, str)
            and retained_candidate
            else set()
        )
    )
    checkpoint_ids = sorted(
        {
            str(lane["checkpoint_id"])
            for lane in active_lanes
            if isinstance(lane.get("checkpoint_id"), str)
            and lane["checkpoint_id"]
        }
        | {
            str(value)
            for value in (
                continuity.get(
                    "current_executable_checkpoint_ids", []
                )
                if isinstance(continuity, dict)
                else []
            )
            if isinstance(value, str) and value
        }
    )
    actions: list[str] = []
    explanations: dict[str, str] = {}
    try:
        proposal_ranking = normalize_proposal_ranking_catalog_id(
            (snapshot.get("campaign") or {}).get("proposal_ranking")
        )
    except ValueError as error:
        raise ValueError(str(error)) from error

    def expose(action: str, reason: str) -> None:
        actions.append(action)
        explanations[action] = reason

    if available_lane_slots > 0:
        expose(
            "start_lane",
            "capacity exists for one reviewed new search lane",
        )
    if active_lane_ids:
        expose(
            "patch_lane",
            "at least one active lane has implemented patchable controls",
        )
        if checkpoint_ids and available_lane_slots > 0:
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
    diagnostic_subject_ids = sorted(
        set(active_lane_ids)
        | {str(value["lane_id"]) for value in lanes}
        | set(candidate_ids)
    )
    if diagnostic_subject_ids:
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

    # This assertion is deliberately local to the projection: a fresh
    # campaign with no lanes must always expose a constructive action.  It
    # protects against regressions in memory carry-forward code that might
    # otherwise publish an apparently valid but unexecutable empty space.
    if not active_lanes and maximum_lanes > 0 and "start_lane" not in actions:
        actions.insert(0, "start_lane")
        explanations["start_lane"] = (
            "zero-lane bootstrap has capacity for the first reviewed search lane"
        )

    active_by_id = {str(value["lane_id"]): value for value in active_lanes}
    result = {
        "catalog_version": catalog["catalog_version"],
        "actions": actions,
        "action_applicability": explanations,
        "active_executable_lane_ids": active_lane_ids,
        "active_lane_versions": active_lane_versions,
        "active_lane_count": active_lane_count,
        "max_active_lanes": maximum_lanes,
        "available_lane_slots": available_lane_slots,
        "bootstrap": {
            "zero_lane": not active_lanes,
            "start_lane_required": (
                not active_lanes and maximum_lanes > 0
            ),
        },
        "historical_lane_ids": sorted(
            str(value["lane_id"])
            for value in lanes
            if str(value["lane_id"]) not in active_by_id
        ),
        "lane_lifecycle_states": {
            str(value["lane_id"]): str(value.get("state") or "unknown")
            for value in lanes
        },
        "candidate_target_ids": candidate_ids,
        "diagnostic_subject_ids": diagnostic_subject_ids,
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
        "proposal_ranking": {
            "enabled": proposal_ranking is not None,
            "catalog_id": proposal_ranking,
            "reviewed_catalog_id": (
                proposal_ranking
                if proposal_ranking is not None
                else REVIEWED_PROPOSAL_RANKING_CATALOG_ID
            ),
            "mutation_algorithms": list(PROPOSAL_RANKING_MUTATION_ALGORITHMS),
            "random_restart_unranked": True,
            "patchable": False,
            "instruction": (
                "When enabled, every newly started reviewed mutation lane must "
                "include the exact catalog_id. Omit it when disabled; "
                "random_restart is always unranked."
            ),
            "random_restart_rule": RANDOM_RESTART_UNRANKED_INSTRUCTION,
        },
    }
    if checkpoint_ids:
        result["checkpoint_target_ids"] = checkpoint_ids
    return result

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
