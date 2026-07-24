from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import hashlib
import json

from .catalog import (
    ACTION_TYPES,
    ALGORITHMS,
    DIAGNOSTICS,
    GRAPH_FAMILIES,
    PARAMETER_DOMAINS,
    REVIEW_EVENTS,
)

MAX_SNAPSHOT_BYTES = 256 * 1024
MAX_DECISION_BYTES = 128 * 1024


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


def _common_action_properties() -> dict[str, Any]:
    return {
        "action_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "type": {"enum": list(ACTION_TYPES)},
        "priority": {"type": "integer", "minimum": 0, "maximum": 100},
        "hypothesis_ids": {
            "type": "array",
            "maxItems": 16,
            "items": {"type": "string"},
            "uniqueItems": True,
        },
        "evidence_ids": {
            "type": "array",
            "maxItems": 32,
            "items": {"type": "string"},
            "uniqueItems": True,
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
                    "enum": ["reject", "replan"],
                }
            },
        },
    }


def director_decision_schema() -> dict[str, Any]:
    common = _common_action_properties()
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
    parameter_schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": PARAMETER_DOMAINS,
        "required": ["order", "batch_candidates", "witness_cap"],
    }

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
                "type": {"const": action_type},
                **properties,
            },
        }

    lane_target = {
        "lane_id": {"type": "string", "minLength": 1, "maxLength": 128},
        "expected_lane_version": {"type": "integer", "minimum": 0},
    }
    patch_parameter_schema = {
        **parameter_schema,
        "properties": {
            name: domain
            for name, domain in PARAMETER_DOMAINS.items()
            if name != "order"
        },
        "required": [],
        "minProperties": 1,
    }
    action_variants = [
        variant(
            "start_lane",
            ["spec"],
            {
                "spec": {
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
                        "algorithm": {"enum": list(ALGORITHMS)},
                        "graph_family": {"enum": list(GRAPH_FAMILIES)},
                        "seed": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 2**63 - 1,
                        },
                        "parameters": parameter_schema,
                        "resource_share": {
                            "type": "number",
                            "exclusiveMinimum": 0,
                            "maximum": 1,
                        },
                    },
                }
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
                "checkpoint_id": {"type": "string"},
                "variants": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 4,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["name", "patch", "resource_share"],
                        "properties": {
                            "name": {"type": "string"},
                            "patch": patch_parameter_schema,
                            "resource_share": {
                                "type": "number",
                                "exclusiveMinimum": 0,
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
                    "required": ["source", "seed"],
                    "properties": {
                        "source": {
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
            {"candidate_id": {"type": "string"}},
        ),
        variant(
            "request_diagnostic",
            ["diagnostic_type", "subject_ids"],
            {
                "diagnostic_type": {"enum": list(DIAGNOSTICS)},
                "subject_ids": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 32,
                    "items": {"type": "string"},
                    "uniqueItems": True,
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
                    "items": {"type": "string"},
                    "uniqueItems": True,
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
    return {
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
            "schema_version": {"const": "1.0"},
            "snapshot_id": {"type": "string"},
            "campaign_assessment": {
                "type": "string",
                "minLength": 1,
                "maxLength": 6000,
            },
            "hypothesis_updates": {
                "type": "array",
                "maxItems": 32,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "hypothesis_id",
                        "operation",
                        "statement",
                        "confidence",
                        "evidence_for",
                        "evidence_against",
                    ],
                    "properties": {
                        "hypothesis_id": {"type": "string"},
                        "operation": {
                            "enum": [
                                "create",
                                "confirm",
                                "weaken",
                                "reject",
                                "revise",
                            ]
                        },
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
                            "maxItems": 32,
                            "items": {"type": "string"},
                            "uniqueItems": True,
                        },
                        "evidence_against": {
                            "type": "array",
                            "maxItems": 32,
                            "items": {"type": "string"},
                            "uniqueItems": True,
                        },
                    },
                },
            },
            "actions": {
                "type": "array",
                "minItems": 1,
                "maxItems": 12,
                "items": {"oneOf": action_variants},
            },
            "next_review": _review_schema(),
        },
    }


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
                "items": {"enum": list(REVIEW_EVENTS)},
                "uniqueItems": True,
            },
        },
    }
