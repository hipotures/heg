from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import hashlib
import json
import os

from ..model import BitGraph
from .protocol import canonical_json
from .store import ResearchStore


class ScientificActionDispatcher:
    """Execute reviewed deterministic diagnostics and review contracts."""

    def __init__(
        self,
        *,
        store: ResearchStore,
        campaign_id: str,
        campaign_dir: Path,
    ):
        self.store = store
        self.campaign_id = campaign_id
        self.campaign_dir = campaign_dir.resolve()
        self.diagnostic_dir = self.campaign_dir / "diagnostics"
        self.diagnostic_dir.mkdir(parents=True, exist_ok=True)
        self._review_contracts: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []

    def dispatch_pending(self) -> list[str]:
        applied: list[str] = []
        for action in self.store.pending_auxiliary_actions(self.campaign_id):
            action_id = str(action["action_id"])
            if _expired(str(action["lease_expires_at"])):
                self.store.record_action_outcome(
                    action_id=action_id,
                    status="rejected_lease_expired",
                    failure_kind="action_lease_expired",
                    failure_detail="auxiliary action lease expired",
                )
                self.events.append({"reason": "action_lease_expired"})
                continue
            parameters = json.loads(str(action["parameters_json"]))
            try:
                if action["action_type"] == "set_review_trigger":
                    contract = dict(parameters["review_trigger"])
                    self._review_contracts.append(contract)
                    observed = {"review_trigger": contract}
                else:
                    observed = self._diagnostic(
                        action_id=action_id,
                        diagnostic_type=str(parameters["diagnostic_type"]),
                        subject_ids=[
                            str(value) for value in parameters["subject_ids"]
                        ],
                    )
                self.store.record_action_outcome(
                    action_id=action_id,
                    status="applied",
                    observed_effect=observed,
                )
                applied.append(action_id)
            except Exception as error:
                self.store.record_action_outcome(
                    action_id=action_id,
                    status="failed",
                    failure_kind=type(error).__name__,
                    failure_detail=str(error)[:2000],
                )
                self.events.append({"reason": "regression"})
        return applied

    def drain_review_contracts(self) -> list[dict[str, Any]]:
        values = list(self._review_contracts)
        self._review_contracts.clear()
        return values

    def drain_events(self) -> list[dict[str, Any]]:
        values = list(self.events)
        self.events.clear()
        return values

    def _diagnostic(
        self,
        *,
        action_id: str,
        diagnostic_type: str,
        subject_ids: list[str],
    ) -> dict[str, Any]:
        candidates = self._candidates(subject_ids)
        lanes = self._lanes(subject_ids)
        if diagnostic_type == "graph_invariants":
            result = {
                "graphs": [
                    _graph_invariants(candidate) for candidate in candidates
                ]
            }
        elif diagnostic_type == "cycle_length_profile":
            result = {
                "profiles": [
                    {
                        "candidate_id": candidate["candidate_id"],
                        "heuristic_score_profile": json.loads(
                            candidate["score_json"]
                        ).get("witness_counts", {}),
                        "complete": False,
                        "note": "exact authority remains the M4 broker",
                    }
                    for candidate in candidates
                ]
            }
        elif diagnostic_type == "mutation_ancestry":
            candidate_lanes = self._lanes(
                [str(candidate["lane_id"]) for candidate in candidates]
            )
            selected_lanes = {
                str(lane["lane_id"]): lane
                for lane in (*lanes, *candidate_lanes)
            }
            result = {
                "lanes": [
                    self._mutation_ancestry(lane)
                    for lane in selected_lanes.values()
                ]
            }
        elif diagnostic_type == "operator_yield":
            result = {"lanes": [self._operator_yield(lane) for lane in lanes]}
        elif diagnostic_type == "seed_generation_efficiency":
            result = self._seed_generation_efficiency(lanes)
        elif diagnostic_type == "candidate_structural_diff":
            result = _candidate_diff(candidates[:2])
        elif diagnostic_type == "canonical_duplicate_analysis":
            result = {
                "candidate_count": len(candidates),
                "unique_graph_hashes": len(
                    {candidate["graph_sha256"] for candidate in candidates}
                ),
                "duplicate_count": len(candidates)
                - len({candidate["graph_sha256"] for candidate in candidates}),
            }
        elif diagnostic_type == "archive_cluster_comparison":
            result = _archive_summary(candidates)
        else:
            raise ValueError(f"unsupported diagnostic: {diagnostic_type}")
        payload = {
            "schema_version": "1.0",
            "action_id": action_id,
            "diagnostic_type": diagnostic_type,
            "subject_ids": subject_ids,
            "result": result,
        }
        encoded = canonical_json(payload, max_bytes=64 * 1024) + b"\n"
        relative = Path("diagnostics") / f"{action_id}.json"
        _atomic_write(self.campaign_dir / relative, encoded)
        return {
            "diagnostic_type": diagnostic_type,
            "artifact_ref": str(relative),
            "artifact_sha256": hashlib.sha256(encoded).hexdigest(),
            "summary": result,
        }

    def _candidates(self, subject_ids: list[str]) -> list[dict[str, Any]]:
        identifiers = {
            value.removeprefix("candidate-summary:")
            for value in subject_ids
            if value.startswith("candidate-")
            or value.startswith("candidate-summary:candidate-")
        }
        if not identifiers:
            return []
        placeholders = ",".join("?" for _ in identifiers)
        rows = self.store.connection.execute(
            f"""
            SELECT * FROM campaign_candidates
            WHERE campaign_id=? AND candidate_id IN ({placeholders})
            """,
            (self.campaign_id, *sorted(identifiers)),
        ).fetchall()
        return [dict(row) for row in rows]

    def _lanes(self, subject_ids: list[str]) -> list[dict[str, Any]]:
        identifiers = {
            value.split(":", 2)[1]
            if value.startswith("lane-metrics:")
            else value
            for value in subject_ids
            if value.startswith("lane-") or value.startswith("lane-metrics:")
        }
        if not identifiers:
            return []
        placeholders = ",".join("?" for _ in identifiers)
        rows = self.store.connection.execute(
            f"""
            SELECT * FROM research_lanes
            WHERE campaign_id=? AND lane_id IN ({placeholders})
            """,
            (self.campaign_id, *sorted(identifiers)),
        ).fetchall()
        return [dict(row) for row in rows]

    def _operator_yield(self, lane: dict[str, Any]) -> dict[str, Any]:
        rows = self.store.connection.execute(
            """
            SELECT metrics_json FROM lane_metric_windows
            WHERE lane_id=? ORDER BY end_high_water DESC LIMIT 16
            """,
            (lane["lane_id"],),
        ).fetchall()
        yields = [
            float(json.loads(row["metrics_json"]).get("operator_yield", 0))
            for row in rows
        ]
        return {
            "lane_id": lane["lane_id"],
            "windows": len(yields),
            "mean_operator_yield": (
                sum(yields) / len(yields) if yields else 0.0
            ),
        }

    def _seed_generation_efficiency(
        self, lanes: list[dict[str, Any]]
    ) -> dict[str, Any]:
        comparisons: list[dict[str, Any]] = []
        for lane in lanes:
            row = self.store.connection.execute(
                """
                SELECT metrics_json FROM lane_metric_windows
                WHERE lane_id=? ORDER BY end_high_water DESC LIMIT 1
                """,
                (lane["lane_id"],),
            ).fetchone()
            metrics = json.loads(row["metrics_json"]) if row else {}
            seed_generation = metrics.get("seed_generation", {})
            cumulative = (
                seed_generation.get("cumulative", {})
                if isinstance(seed_generation, dict)
                else {}
            )
            total = cumulative.get("total", {})
            sources = cumulative.get("sources", {})
            random_restart = (
                sources.get("random_restart_candidate", {})
                if isinstance(sources, dict)
                else {}
            )
            parameters = json.loads(lane["current_parameters_json"])
            measured_search_loop_ns = int(
                cumulative.get("measured_search_loop_ns", 0)
            )
            random_restart_share = (
                int(random_restart.get("search_loop_elapsed_ns", 0))
                / measured_search_loop_ns
                if measured_search_loop_ns
                else 0.0
            )
            attempt_percentiles = total.get("attempt_percentiles", {})
            comparison = {
                "lane_id": lane["lane_id"],
                "graph_family": lane["graph_family"],
                "graph_order": int(parameters["order"]),
                "generator_mode": cumulative.get("generator_mode"),
                "calls": int(total.get("calls", 0)),
                "successes": int(total.get("successes", 0)),
                "failures": int(total.get("failures", 0)),
                "p95_attempts": int(
                    attempt_percentiles.get("p95", 0)
                ),
                "p99_attempts": int(
                    attempt_percentiles.get("p99", 0)
                ),
                "maximum_attempts": int(total.get("attempts_max", 0)),
                "retry_budget": int(total.get("retry_budget_max", 0)),
                "maximum_retry_budget_fraction": float(
                    total.get("maximum_retry_budget_fraction", 0.0)
                ),
                "retry_budget_exhaustions": int(
                    total.get("retry_budget_exhaustions", 0)
                ),
                "generation_elapsed_seconds": (
                    int(total.get("elapsed_ns_total", 0))
                    / 1_000_000_000
                ),
                "generator_time_share": float(
                    cumulative.get("generator_time_share", 0.0)
                ),
                "random_restart_generator_time_share": (
                    random_restart_share
                ),
                "random_restart_seed_construction_dominated": (
                    random_restart_share >= 0.5
                ),
                "failure_categories": dict(
                    total.get("failure_categories", {})
                ),
            }
            comparisons.append(comparison)
        comparisons.sort(
            key=lambda value: (
                str(value["graph_family"]),
                int(value["graph_order"]),
                str(value["lane_id"]),
            )
        )
        highest_p95 = max(
            comparisons,
            key=lambda value: (
                int(value["p95_attempts"]),
                int(value["maximum_attempts"]),
                str(value["lane_id"]),
            ),
            default=None,
        )
        highest_runtime_share = max(
            comparisons,
            key=lambda value: (
                float(value["generator_time_share"]),
                str(value["lane_id"]),
            ),
            default=None,
        )
        return {
            "lanes": comparisons,
            "highest_p95_attempts": highest_p95,
            "near_retry_budget": [
                value
                for value in comparisons
                if value["maximum_retry_budget_fraction"] >= 0.8
                or value["retry_budget_exhaustions"] > 0
            ],
            "highest_generator_time_share": highest_runtime_share,
            "random_restart_seed_construction_dominated": [
                value
                for value in comparisons
                if value["random_restart_seed_construction_dominated"]
            ],
        }

    def _mutation_ancestry(self, lane: dict[str, Any]) -> dict[str, Any]:
        rows = self.store.connection.execute(
            """
            SELECT metrics_json FROM lane_metric_windows
            WHERE lane_id=? ORDER BY end_high_water DESC LIMIT 16
            """,
            (lane["lane_id"],),
        ).fetchall()
        global_records: list[dict[str, Any]] = []
        final_best: list[dict[str, Any]] = []
        for row in reversed(rows):
            metrics = json.loads(row["metrics_json"])
            ancestry = metrics.get("mutation_ancestry", {})
            global_records.extend(
                ancestry.get("global_record_improvements", [])
            )
            if ancestry.get("final_best_ancestry"):
                final_best = list(ancestry["final_best_ancestry"])[-64:]
        truncated = len(global_records) > 64
        return {
            "lane_id": lane["lane_id"],
            "parent_lane_id": lane["parent_lane_id"],
            "parent_checkpoint_ref": lane["parent_checkpoint_ref"],
            "seed_lineage": json.loads(lane["seed_lineage_json"]),
            "global_record_improvements": global_records[-64:],
            "global_records_truncated": truncated,
            "final_best_ancestry": final_best,
            "maximum_accepted_ancestors": 64,
        }


def _graph_invariants(candidate: dict[str, Any]) -> dict[str, Any]:
    graph = BitGraph.from_graph6(str(candidate["graph6"]))
    return {
        "candidate_id": candidate["candidate_id"],
        "order": graph.n,
        "size": graph.size(),
        "minimum_degree": graph.minimum_degree(),
        "maximum_degree": max(graph.degree_sequence(), default=0),
        "connected": graph.is_connected(),
        "degree_sequence": list(graph.degree_sequence()),
    }


def _candidate_diff(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if len(candidates) != 2:
        return {"available": False, "reason": "exactly two candidates required"}
    first = BitGraph.from_graph6(str(candidates[0]["graph6"]))
    second = BitGraph.from_graph6(str(candidates[1]["graph6"]))
    if first.n != second.n:
        return {
            "available": True,
            "same_order": False,
            "order_delta": second.n - first.n,
        }
    return {
        "available": True,
        "same_order": True,
        "edge_symmetric_difference": len(
            set(first.edges()) ^ set(second.edges())
        ),
        "degree_l1": sum(
            abs(left - right)
            for left, right in zip(
                first.degree_sequence(),
                second.degree_sequence(),
                strict=True,
            )
        ),
    }


def _archive_summary(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    orders: dict[int, int] = {}
    for candidate in candidates:
        order = BitGraph.from_graph6(str(candidate["graph6"])).n
        orders[order] = orders.get(order, 0) + 1
    return {
        "candidate_count": len(candidates),
        "counts_by_order": {str(key): value for key, value in sorted(orders.items())},
    }


def _expired(value: str) -> bool:
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        <= datetime.now(UTC)
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
