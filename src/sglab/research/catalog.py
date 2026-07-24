from __future__ import annotations

from typing import Any


ALGORITHMS = ("simulated_annealing", "iterated_local_search")
GRAPH_FAMILIES = {
    "connected_cubic": "cubic_first",
    "predominantly_cubic": "minimal_structure_mixed_degree",
    "unrestricted_min_degree_3": "unrestricted_min_degree_3",
}
ACTION_TYPES = (
    "start_lane",
    "patch_lane",
    "fork_lane",
    "restart_lane",
    "stop_lane",
    "reallocate_resources",
    "promote_candidate",
    "request_diagnostic",
    "schedule_verification",
    "set_review_trigger",
)
DIAGNOSTICS = (
    "cycle_length_profile",
    "graph_invariants",
    "mutation_ancestry",
    "archive_cluster_comparison",
    "operator_yield",
    "candidate_structural_diff",
    "canonical_duplicate_analysis",
)
REVIEW_EVENTS = (
    "new_global_best",
    "meaningful_improvement",
    "regression",
    "stagnation",
    "diversity_collapse",
    "operator_yield_shift",
    "verification_result",
    "verifier_disagreement",
    "lane_failure",
    "resource_pressure",
    "action_lease_expired",
)

PARAMETER_DOMAINS: dict[str, dict[str, Any]] = {
    "order": {"type": "integer", "minimum": 4, "maximum": 128},
    "batch_candidates": {"type": "integer", "minimum": 100, "maximum": 1_000_000},
    "witness_cap": {"type": "integer", "minimum": 1, "maximum": 10_000},
    "temperature": {"type": "number", "minimum": 0.001, "maximum": 100.0},
    "cooling": {"type": "number", "minimum": 0.9, "maximum": 1.0},
    "restart_threshold": {
        "type": "integer",
        "minimum": 100,
        "maximum": 10_000_000,
    },
    "tabu_tenure": {"type": "integer", "minimum": 1, "maximum": 4096},
    "perturbation_interval": {
        "type": "integer",
        "minimum": 1,
        "maximum": 1_000_000,
    },
    "promotion_penalty": {
        "type": "integer",
        "minimum": 0,
        "maximum": 1_000_000_000,
    },
}

ALGORITHM_PARAMETERS = {
    "simulated_annealing": {
        "order",
        "batch_candidates",
        "witness_cap",
        "temperature",
        "cooling",
        "restart_threshold",
        "promotion_penalty",
    },
    "iterated_local_search": {
        "order",
        "batch_candidates",
        "witness_cap",
        "tabu_tenure",
        "perturbation_interval",
        "restart_threshold",
        "promotion_penalty",
    },
}

PATCHABLE_PARAMETERS = {
    algorithm: parameters - {"order"}
    for algorithm, parameters in ALGORITHM_PARAMETERS.items()
}


def action_catalog() -> dict[str, Any]:
    return {
        "catalog_version": "1.0",
        "algorithms": list(ALGORITHMS),
        "graph_families": [
            {"id": family, "engine_mode": mode}
            for family, mode in GRAPH_FAMILIES.items()
        ],
        "actions": list(ACTION_TYPES),
        "diagnostics": list(DIAGNOSTICS),
        "review_events": list(REVIEW_EVENTS),
        "parameter_domains": PARAMETER_DOMAINS,
        "algorithm_parameters": {
            algorithm: sorted(parameters)
            for algorithm, parameters in ALGORITHM_PARAMETERS.items()
        },
        "patchable_parameters": {
            algorithm: sorted(parameters)
            for algorithm, parameters in PATCHABLE_PARAMETERS.items()
        },
        "forbidden_model_fields": [
            "shell",
            "command",
            "python",
            "sql",
            "path",
            "executable",
            "url",
            "network",
            "verifier_definition",
            "target_definition",
        ],
    }
