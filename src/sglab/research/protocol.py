from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import hashlib
import json

from .catalog import (
    ACTION_TYPES,
    ALGORITHM_PARAMETERS,
    ALGORITHMS,
    DIAGNOSTICS,
    GRAPH_FAMILIES,
    MUTATION_OPERATORS,
    MUTATION_WEIGHTS_PARAMETER,
    PARAMETER_DOMAINS,
    PROPOSAL_RANKING_MUTATION_ALGORITHMS,
    REVIEW_EVENTS,
)

MAX_SNAPSHOT_BYTES = 256 * 1024
MAX_DECISION_BYTES = 128 * 1024
HYPOTHESIS_CREATE_OPERATION = "create"
HYPOTHESIS_EXISTING_OPERATIONS = (
    "confirm",
    "weaken",
    "reject",
    "retain",
    "revise",
)
HYPOTHESIS_OPERATIONS = (
    HYPOTHESIS_CREATE_OPERATION,
    *HYPOTHESIS_EXISTING_OPERATIONS,
)
HYPOTHESIS_UPDATE_FIELDS = (
    "hypothesis_id",
    "operation",
    "statement",
    "confidence",
    "evidence_for",
    "evidence_against",
)


def action_identity_contract(
    snapshot_id: str,
    *,
    recent_reserved_action_ids: Any = (),
) -> dict[str, Any]:
    prefix = (
        f"action-{hashlib.sha256(snapshot_id.encode('utf-8')).hexdigest()[:12]}-"
    )
    recent = sorted(
        {
            value
            for value in recent_reserved_action_ids
            if isinstance(value, str) and value
        }
    )[-64:]
    return {
        "scope": "durable_workspace",
        "rule": (
            "Every action_id must be new and must never reuse an action_id "
            "already persisted in this workspace."
        ),
        "recommended_prefix": prefix,
        "recent_reserved_action_ids": recent,
        "collision_policy": "one_fresh_stateless_replan_then_fail_closed",
    }


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class DecisionValidation:
    accepted: bool
    issues: tuple[ValidationIssue, ...]
    normalized: dict[str, Any] | None = None


def canonical_json(value: Any, *, max_bytes: int) -> bytes:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    if len(payload) > max_bytes:
        raise ValueError(f"JSON payload exceeds {max_bytes} bytes")
    return payload


def payload_sha256(value: Any, *, max_bytes: int) -> str:
    return hashlib.sha256(canonical_json(value, max_bytes=max_bytes)).hexdigest()


def hypothesis_update_contract(
    existing_hypothesis_ids: Any,
) -> dict[str, Any]:
    existing = sorted(
        {
            value
            for value in existing_hypothesis_ids
            if isinstance(value, str) and value
        }
    )
    return {
        "existing_submitted_hypothesis_ids": existing,
        "create": {
            "operation": HYPOTHESIS_CREATE_OPERATION,
            "hypothesis_id_rule": (
                "must be new and unique within this response"
            ),
        },
        "existing_operations": list(HYPOTHESIS_EXISTING_OPERATIONS),
        "existing_hypothesis_id_rule": (
            "must reference an existing submitted hypothesis ID"
        ),
        "evidence_reference_rule": (
            "evidence_for and evidence_against must contain only exact IDs "
            "from the submitted evidence registry, never prose"
        ),
        "existing_operations_available": bool(existing),
    }


def hypothesis_updates_match_schema_contract(
    value: Any,
    existing_hypothesis_ids: Any,
) -> bool:
    if not isinstance(value, list) or len(value) > 32:
        return False
    existing = {
        item
        for item in existing_hypothesis_ids
        if isinstance(item, str) and item
    }
    for item in value:
        if not isinstance(item, dict):
            return False
        operation = item.get("operation")
        identifier = item.get("hypothesis_id")
        if operation == HYPOTHESIS_CREATE_OPERATION:
            if not isinstance(identifier, str):
                return False
            continue
        if (
            operation not in HYPOTHESIS_EXISTING_OPERATIONS
            or identifier not in existing
        ):
            return False
    return True


def _hypothesis_update_schema(
    existing_hypothesis_ids: Any,
    *,
    evidence_item_schema: dict[str, Any],
    evidence_max_items: int,
) -> dict[str, Any]:
    existing = sorted(
        {
            value
            for value in existing_hypothesis_ids
            if isinstance(value, str) and value
        }
    )
    common_properties = {
        "statement": {
            "type": "string",
            "minLength": 1,
            "maxLength": 4000,
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
        "evidence_for": {
            "type": "array",
            "maxItems": evidence_max_items,
            "items": evidence_item_schema,
        },
        "evidence_against": {
            "type": "array",
            "maxItems": evidence_max_items,
            "items": evidence_item_schema,
        },
    }

    def branch(
        operation: dict[str, Any],
        hypothesis_id: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": list(HYPOTHESIS_UPDATE_FIELDS),
            "properties": {
                "hypothesis_id": hypothesis_id,
                "operation": operation,
                **common_properties,
            },
        }

    branches = [
        branch(
            {
                "type": "string",
                "const": HYPOTHESIS_CREATE_OPERATION,
            },
            {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "description": (
                    "A new hypothesis ID, unique within this response."
                ),
            },
        )
    ]
    if existing:
        branches.append(
            branch(
                {
                    "type": "string",
                    "enum": list(HYPOTHESIS_EXISTING_OPERATIONS),
                },
                {
                    "type": "string",
                    "enum": existing,
                },
            )
        )
    return {"anyOf": branches}


def _common_action_properties(
    action_id_prefix: str | None = None,
    *,
    evidence_item_schema: dict[str, Any],
    evidence_max_items: int,
) -> dict[str, Any]:
    action_id: dict[str, Any] = {
        "type": "string",
        "minLength": 1,
        "maxLength": 128,
    }
    if action_id_prefix:
        action_id["description"] = (
            "Must be new across the durable workspace. Use prefix "
            f"{action_id_prefix}"
        )
    return {
        "action_id": action_id,
        "type": {"type": "string", "enum": list(ACTION_TYPES)},
        "priority": {"type": "integer", "minimum": 0, "maximum": 100},
        "hypothesis_ids": {
            "type": "array",
            "maxItems": 16,
            "items": {"type": "string"},
        },
        "evidence_ids": {
            "type": "array",
            "maxItems": evidence_max_items,
            "items": evidence_item_schema,
        },
        "rationale": {"type": "string", "minLength": 1, "maxLength": 4000},
        "expected_effect": {
            "type": "string",
            "minLength": 1,
            "maxLength": 2000,
        },
        "evaluation_window": {
            "type": "object",
            "additionalProperties": False,
            "required": ["max_wall_seconds", "max_candidate_delta"],
            "properties": {
                "max_wall_seconds": {
                    "type": "integer",
                    "minimum": 10,
                    "maximum": 7200,
                },
                "max_candidate_delta": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100_000_000,
                },
            },
        },
        "idempotency_key": {
            "type": "string",
            "minLength": 8,
            "maxLength": 128,
        },
        "lease_seconds": {
            "type": "integer",
            "minimum": 30,
            "maximum": 7200,
        },
        "fallback": {
            "type": "object",
            "additionalProperties": False,
            "required": ["on_precondition_failure"],
            "properties": {
                "on_precondition_failure": {
                    "type": "string",
                    "enum": ["reject", "replan"],
                }
            },
        },
    }


def _mutation_weights_schema() -> dict[str, Any]:
    """Return the optional, host-normalized mutation-weight object schema."""

    return {
        "additionalProperties": False,
        "type": ["object", "null"],
        # Strict Structured Outputs requires every declared object property
        # to be present. Nullable transport placeholders are removed by
        # _normalize_transport_nulls before validate_decision, where the
        # host enforces the non-empty/positive-weight semantic contract.
        "required": list(MUTATION_OPERATORS),
        "properties": {
            name: {"type": "number", "minimum": 0}
            for name in MUTATION_OPERATORS
        },
    }


def _lane_parameter_schema(
    algorithm: str,
    *,
    proposal_ranking_catalog_id: str | None,
) -> dict[str, Any]:
    """Build the exact parameter object accepted for one lane algorithm.

    The previous model-facing schema exposed the union of every algorithm's
    parameters and made most of them nullable.  That permitted a structured
    response such as ``random_restart`` with ``proposal_ranking`` (or a large
    set of unrelated null fields), leaving semantic validation to reject the
    entire turn.  Keep semantic validation authoritative, but make the output
    contract express the same algorithm-specific shape so the model cannot be
    asked to choose an invalid combination in the first place.
    """

    allowed = ALGORITHM_PARAMETERS[algorithm]
    properties: dict[str, Any] = {}
    # Strict Structured Outputs requires every declared property to be
    # required. Algorithm controls are nullable transport placeholders;
    # _normalize_transport_nulls removes nulls before _parameters() applies
    # its semantic optional-field rules. Proposal ranking is required only
    # for an explicitly ranked mutation branch.
    required = ["order", "batch_candidates", "witness_cap"]
    for name in sorted(allowed):
        if name == "proposal_ranking":
            if proposal_ranking_catalog_id is None:
                continue
            properties[name] = {
                "type": "string",
                "const": proposal_ranking_catalog_id,
            }
            required.append(name)
            continue
        if name == MUTATION_WEIGHTS_PARAMETER:
            properties[name] = _mutation_weights_schema()
        else:
            domain = PARAMETER_DOMAINS[name]
            properties[name] = {
                **domain,
                "type": [domain["type"], "null"]
                if name not in {"order", "batch_candidates", "witness_cap"}
                else domain["type"],
            }
        if name not in required:
            required.append(name)
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _start_lane_spec_schema(
    *,
    proposal_ranking_catalog_id: str | None,
) -> dict[str, Any]:
    """Build algorithm-discriminated start-lane specifications."""

    common = {
        "graph_family": {
            "type": "string",
            "enum": list(GRAPH_FAMILIES),
        },
        "seed": {
            "type": "integer",
            "minimum": 0,
            "maximum": 2**63 - 1,
        },
        "resource_share": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
        },
    }
    branches: list[dict[str, Any]] = []
    for algorithm in ALGORITHMS:
        branches.append(
            {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "algorithm",
                    "graph_family",
                    "seed",
                    "parameters",
                    "resource_share",
                ],
                "properties": {
                    "algorithm": {"type": "string", "const": algorithm},
                    **common,
                    "parameters": _lane_parameter_schema(
                        algorithm,
                        proposal_ranking_catalog_id=(
                            proposal_ranking_catalog_id
                            if algorithm in PROPOSAL_RANKING_MUTATION_ALGORITHMS
                            else None
                        ),
                    ),
                },
            }
        )
    return {"anyOf": branches}


def director_decision_schema(
    allowed_action_space: dict[str, Any] | None = None,
    *,
    existing_hypothesis_ids: Any = (),
    submitted_evidence_ids: Any | None = None,
    action_id_prefix: str | None = None,
) -> dict[str, Any]:
    """Return the structured schema for the submitted applicable actions."""

    applicable_actions = set(
        (
            allowed_action_space.get("actions", ACTION_TYPES)
            if isinstance(allowed_action_space, dict)
            else ACTION_TYPES
        )
    )
    available_lane_slots = (
        allowed_action_space.get("available_lane_slots")
        if isinstance(allowed_action_space, dict)
        else None
    )
    if available_lane_slots is not None:
        available_lane_slots = max(0, int(available_lane_slots))
        if available_lane_slots == 0:
            applicable_actions.discard("fork_lane")
    if isinstance(allowed_action_space, dict):
        active_ids = allowed_action_space.get(
            "active_executable_lane_ids", []
        )
        declared_actions = allowed_action_space.get("actions")
        # Reconcile a stale/empty projection at the schema boundary.  A
        # zero-lane campaign with capacity must be able to emit start_lane;
        # set_review_trigger remains the lane-independent escape hatch for a
        # genuinely full or otherwise non-constructive state.
        if (
            not active_ids
            and (declared_actions is None or not declared_actions)
            and (available_lane_slots is None or available_lane_slots > 0)
        ):
            applicable_actions.add("start_lane")
        if not applicable_actions:
            applicable_actions.add("set_review_trigger")
    fork_variant_max_items = min(
        4,
        available_lane_slots,
    ) if available_lane_slots is not None and available_lane_slots > 0 else 4
    active_lane_ids = (
        list(allowed_action_space.get("active_executable_lane_ids", []))
        if isinstance(allowed_action_space, dict)
        else []
    )
    candidate_target_ids = (
        list(allowed_action_space.get("candidate_target_ids", []))
        if isinstance(allowed_action_space, dict)
        else []
    )
    diagnostic_subject_ids = (
        list(allowed_action_space.get("diagnostic_subject_ids", []))
        if isinstance(allowed_action_space, dict)
        else []
    )
    checkpoint_target_ids = (
        list(allowed_action_space.get("checkpoint_target_ids", []))
        if isinstance(allowed_action_space, dict)
        else []
    )
    exact_evidence_ids = (
        sorted(
            {
                value
                for value in submitted_evidence_ids
                if isinstance(value, str) and value
            }
        )
        if submitted_evidence_ids is not None
        else None
    )
    evidence_item_schema: dict[str, Any] = {
        "type": "string",
        "description": "Exact submitted evidence-registry ID; never prose.",
    }
    evidence_max_items = 32
    schema_defs: dict[str, Any] = {}
    if exact_evidence_ids:
        schema_defs["submittedEvidenceId"] = {
            "type": "string",
            "enum": exact_evidence_ids,
        }
        evidence_item_schema = {"$ref": "#/$defs/submittedEvidenceId"}
    elif exact_evidence_ids == []:
        evidence_max_items = 0
    common = _common_action_properties(
        action_id_prefix,
        evidence_item_schema=evidence_item_schema,
        evidence_max_items=evidence_max_items,
    )
    common_required = [
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
    ]
    proposal_ranking_catalog_id: str | None = None
    if isinstance(allowed_action_space, dict):
        proposal_contract = allowed_action_space.get("proposal_ranking")
        if isinstance(proposal_contract, dict):
            value = proposal_contract.get("catalog_id")
            if isinstance(value, str) and value:
                proposal_ranking_catalog_id = value

    def variant(
        action_type: str,
        required: list[str],
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": [*common_required, *required],
            "properties": {
                **common,
                "type": {"type": "string", "const": action_type},
                **properties,
            },
        }

    lane_id_schema: dict[str, Any] = {
        "type": "string",
        "minLength": 1,
        "maxLength": 128,
    }
    if allowed_action_space is not None:
        lane_id_schema["enum"] = active_lane_ids
    lane_target = {
        "lane_id": lane_id_schema,
        "expected_lane_version": {"type": "integer", "minimum": 0},
    }
    patch_parameter_properties: dict[str, Any] = {}
    for name, domain in PARAMETER_DOMAINS.items():
        if name in {"order", "proposal_ranking"}:
            continue
        if name == MUTATION_WEIGHTS_PARAMETER:
            patch_parameter_properties[name] = _mutation_weights_schema()
            continue
        patch_parameter_properties[name] = {
            **domain,
            "type": [domain["type"], "null"],
        }
    patch_parameter_schema = {
        "additionalProperties": False,
        "type": "object",
        "properties": patch_parameter_properties,
        "required": list(patch_parameter_properties),
    }
    action_variants = [
        variant(
            "start_lane",
            ["spec"],
            {
                "spec": _start_lane_spec_schema(
                    proposal_ranking_catalog_id=proposal_ranking_catalog_id
                )
            },
        ),
        variant(
            "patch_lane",
            ["lane_id", "expected_lane_version", "patch"],
            {
                **lane_target,
                "patch": patch_parameter_schema,
            },
        ),
        variant(
            "fork_lane",
            ["lane_id", "expected_lane_version", "checkpoint_id", "variants"],
            {
                **lane_target,
                "checkpoint_id": {
                    "type": "string",
                    **(
                        {"enum": checkpoint_target_ids}
                        if allowed_action_space is not None
                        else {}
                    ),
                },
                "variants": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": fork_variant_max_items,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["name", "patch", "resource_share"],
                        "properties": {
                            "name": {"type": "string"},
                            "patch": patch_parameter_schema,
                            "resource_share": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                        },
                    },
                },
            },
        ),
        variant(
            "restart_lane",
            ["lane_id", "expected_lane_version", "restart_spec"],
            {
                **lane_target,
                "restart_spec": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "source",
                        "seed",
                        "checkpoint_id",
                        "candidate_id",
                    ],
                    "properties": {
                        "source": {
                            "type": "string",
                            "enum": ["new_seed", "checkpoint", "archive_elite"]
                        },
                        "seed": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 2**63 - 1,
                        },
                        "checkpoint_id": {"type": ["string", "null"]},
                        "candidate_id": {"type": ["string", "null"]},
                    },
                },
            },
        ),
        variant(
            "stop_lane",
            ["lane_id", "expected_lane_version"],
            lane_target,
        ),
        variant(
            "reallocate_resources",
            ["allocations"],
            {
                "allocations": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 32,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "lane_id",
                            "expected_lane_version",
                            "resource_share",
                        ],
                        "properties": {
                            **lane_target,
                            "resource_share": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 1,
                            },
                        },
                    },
                }
            },
        ),
        variant(
            "promote_candidate",
            ["candidate_id"],
            {
                "candidate_id": {
                    "type": "string",
                    **(
                        {"enum": candidate_target_ids}
                        if allowed_action_space is not None
                        else {}
                    ),
                }
            },
        ),
        variant(
            "request_diagnostic",
            ["diagnostic_type", "subject_ids"],
            {
                "diagnostic_type": {
                    "type": "string",
                    "enum": list(DIAGNOSTICS),
                },
                "subject_ids": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 32,
                    "items": {
                        "type": "string",
                        **(
                            {"enum": diagnostic_subject_ids}
                            if allowed_action_space is not None
                            else {}
                        ),
                    },
                },
            },
        ),
        variant(
            "schedule_verification",
            ["candidate_ids", "verification_priority"],
            {
                "candidate_ids": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 32,
                    "items": {
                        "type": "string",
                        **(
                            {"enum": candidate_target_ids}
                            if allowed_action_space is not None
                            else {}
                        ),
                    },
                },
                "verification_priority": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                },
            },
        ),
        variant(
            "set_review_trigger",
            ["review_trigger"],
            {"review_trigger": _review_schema()},
        ),
    ]
    action_variants = [
        value
        for value in action_variants
        if value["properties"]["type"]["const"] in applicable_actions
    ]
    if not action_variants:
        # The action-space producer always includes set_review_trigger.  Keep
        # the generated schema total for legacy/malformed snapshots rather
        # than returning an impossible `anyOf: []` contract.
        raise ValueError(
            "applicable action space produced no schema-supported actions"
        )
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "SglabDirectorDecisionBatchV1",
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "snapshot_id",
            "campaign_assessment",
            "hypothesis_updates",
            "actions",
            "next_review",
        ],
        "properties": {
            "schema_version": {"type": "string", "const": "1.0"},
            "snapshot_id": {"type": "string"},
            "campaign_assessment": {
                "type": "string",
                "minLength": 1,
                "maxLength": 6000,
            },
            "hypothesis_updates": {
                "type": "array",
                "maxItems": 32,
                "items": _hypothesis_update_schema(
                    existing_hypothesis_ids,
                    evidence_item_schema=evidence_item_schema,
                    evidence_max_items=evidence_max_items,
                ),
            },
            "actions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 12,
                "items": {"anyOf": action_variants},
            },
            "next_review": _review_schema(),
        },
    }
    if schema_defs:
        schema["$defs"] = schema_defs
    return schema


def _review_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "min_wall_seconds",
            "max_wall_seconds",
            "candidate_delta",
            "events",
        ],
        "properties": {
            "min_wall_seconds": {
                "type": "integer",
                "minimum": 10,
                "maximum": 3600,
            },
            "max_wall_seconds": {
                "type": "integer",
                "minimum": 30,
                "maximum": 7200,
            },
            "candidate_delta": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100_000_000,
            },
            "events": {
                "type": "array",
                "maxItems": 16,
                "items": {
                    "type": "string",
                    "enum": list(REVIEW_EVENTS),
                },
            },
        },
    }
