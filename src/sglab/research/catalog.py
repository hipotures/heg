from __future__ import annotations

from typing import Any


REVIEWED_PROPOSAL_RANKING_CATALOG_ID = "mutation_forge_stage4r_v1"


EXPERIMENT_ALGORITHMS = (
    "random_restart",
    "simulated_annealing",
    "iterated_local_search_tabu",
)
ALGORITHMS = (*EXPERIMENT_ALGORITHMS, "iterated_local_search")
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
    "seed_generation_efficiency",
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
    "proposal_ranking": {
        "type": "string",
        "enum": [REVIEWED_PROPOSAL_RANKING_CATALOG_ID],
    },
}

MUTATION_OPERATORS = (
    "uniform_two_edge_switch",
    "forbidden_cycle_break_switch",
)
MUTATION_WEIGHTS_PARAMETER = "mutation_weights"
CAMPAIGN_METADATA_FIELDS = {
    "promotion_penalty": (
        "Campaign-ranking metadata only; it is never passed to a search lane."
    )
}

ALGORITHM_PARAMETERS = {
    "random_restart": {
        "order",
        "batch_candidates",
        "witness_cap",
        "proposal_ranking",
    },
    "simulated_annealing": {
        "order",
        "batch_candidates",
        "witness_cap",
        "temperature",
        "cooling",
        "restart_threshold",
        MUTATION_WEIGHTS_PARAMETER,
        "proposal_ranking",
    },
    "iterated_local_search": {
        "order",
        "batch_candidates",
        "witness_cap",
        "tabu_tenure",
        "perturbation_interval",
        MUTATION_WEIGHTS_PARAMETER,
        "proposal_ranking",
    },
    "iterated_local_search_tabu": {
        "order",
        "batch_candidates",
        "witness_cap",
        "tabu_tenure",
        "perturbation_interval",
        MUTATION_WEIGHTS_PARAMETER,
        "proposal_ranking",
    },
}

PATCHABLE_PARAMETERS = {
    algorithm: parameters - {"order", "proposal_ranking"}
    for algorithm, parameters in ALGORITHM_PARAMETERS.items()
}


def action_catalog() -> dict[str, Any]:
    parameter_effects = {
        "order": "Graph order used for seed generation.",
        "batch_candidates": "Maximum candidate evaluations in one lane batch.",
        "witness_cap": (
            "Per-forbidden-length witness-count cap; capped counts are not exact."
        ),
        "temperature": "Initial simulated-annealing acceptance temperature.",
        "cooling": "Multiplicative simulated-annealing cooling factor.",
        "restart_threshold": (
            "Simulated annealing reseeds after this many evaluations."
        ),
        "tabu_tenure": "Maximum recent candidate hashes retained by tabu search.",
        "perturbation_interval": (
            "ILS-tabu permits a perturbation acceptance at this cadence."
        ),
        MUTATION_WEIGHTS_PARAMETER: (
            "Normalized selection probabilities over reviewed safe mutations."
        ),
        "proposal_ranking": (
            "Explicit reviewed proposal-ranking catalog ID; omitted means disabled."
        ),
    }
    return {
        "catalog_version": "1.3",
        "algorithms": list(ALGORITHMS),
        "graph_families": [
            {"id": family, "engine_mode": mode}
            for family, mode in GRAPH_FAMILIES.items()
        ],
        "actions": list(ACTION_TYPES),
        "diagnostics": list(DIAGNOSTICS),
        "review_events": list(REVIEW_EVENTS),
        "parameter_domains": PARAMETER_DOMAINS,
        "mutation_operators": list(MUTATION_OPERATORS),
        "mutation_weights_contract": {
            "known_operators_only": True,
            "minimum_weight": 0.0,
            "positive_sum_required": True,
            "normalized_before_execution": True,
        },
        "parameter_effects": parameter_effects,
        "campaign_metadata_fields": CAMPAIGN_METADATA_FIELDS,
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
