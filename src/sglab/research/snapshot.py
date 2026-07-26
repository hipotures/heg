from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import hashlib
import json
import os

from ..resources import current_rss_bytes, process_tree_rss_bytes
from ..model import BitGraph
from ..state import utc_now
from ..targets import target_summary
from .lanes import LaneManager
from .catalog import action_catalog
from .context import (
    director_state_v2_memory_input,
    evidence_registry_ids,
    prepare_director_state_v2,
)
from .continuity import (
    ScientificMemoryCompactor,
    ScientificMemoryPolicy,
    memory_snapshot_record,
)
from .protocol import MAX_SNAPSHOT_BYTES, canonical_json
from .store import ResearchStore, new_id
from .telemetry import TelemetrySeries
from .validation import DecisionContext


class SnapshotBuilder:
    """Build and durably publish one bounded authoritative snapshot v3."""

    def __init__(
        self,
        *,
        store: ResearchStore,
        manager: LaneManager,
        campaign_id: str,
        campaign_dir: Path,
        maximum_lanes: int = 32,
        maximum_actions: int = 64,
        maximum_hypotheses: int = 64,
        memory_policy: ScientificMemoryPolicy | None = None,
    ):
        self.store = store
        self.manager = manager
        self.campaign_id = campaign_id
        self.campaign_dir = campaign_dir.resolve()
        self.maximum_lanes = maximum_lanes
        self.maximum_actions = maximum_actions
        self.maximum_hypotheses = maximum_hypotheses
        self.memory_policy = memory_policy or ScientificMemoryPolicy()
        self.memory = ScientificMemoryCompactor(self.memory_policy)
        self.snapshot_dir = self.campaign_dir / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def publish(
        self, *, memory_trigger: str = "pre_inference"
    ) -> tuple[dict[str, Any], DecisionContext]:
        campaign = self.store.campaign(self.campaign_id)
        snapshot_id = new_id("snapshot")
        evidence: set[str] = set()
        lanes = self._lanes(evidence)
        recent_actions = self._recent_actions(evidence)
        hypotheses = self._hypotheses(evidence)
        global_best, _ = self._global_best(evidence)
        verification = self._verification(evidence)
        created_at = utc_now()
        created = _parse_time(str(campaign["created_at"]))
        now = datetime.now(UTC)
        elapsed = max(0.0, (now - created).total_seconds())
        deadline = (
            _parse_time(str(campaign["deadline_at"]))
            if campaign["deadline_at"]
            else None
        )
        remaining = (
            max(0.0, (deadline - now).total_seconds())
            if deadline is not None
            else None
        )
        snapshot = {
            "schema_version": "3.0",
            "snapshot_id": snapshot_id,
            "created_at": created_at,
            "campaign": {
                "campaign_id": self.campaign_id,
                "state": campaign["state"],
                "state_version": int(campaign["state_version"]),
                "stop_mode": campaign["stop_mode"],
                "elapsed_seconds": elapsed,
                "remaining_seconds": remaining,
            },
            "target": {
                **target_summary(str(campaign["target"])),
                "immutable_definition_hash": campaign[
                    "target_definition_sha256"
                ],
            },
            "resources": self._resources(verification),
            "lanes": lanes,
            "global_best": global_best,
            "verification": verification,
            "recent_actions": recent_actions,
            "hypotheses": hypotheses,
            "implemented_director_controls": action_catalog(),
            "available_evidence_ids": sorted(evidence)[:512],
            "continuity": self._continuity(campaign),
        }
        high_water = {
            lane["lane_id"]: lane["metrics"].get("end_high_water", 0)
            for lane in lanes
        }
        previous = self.store.latest_memory_snapshot(self.campaign_id)
        previous_projection = (
            json.loads(str(previous["canonical_json"]))
            if previous is not None
            else None
        )
        projection = self.memory.project(
            director_state_v2_memory_input(snapshot),
            previous=previous_projection,
        )
        projection_bytes = self.memory.encode(projection)
        completed_cycles = int(
            self.store.connection.execute(
                """
                SELECT count(*) FROM director_action_batches
                WHERE campaign_id=? AND validation_status IN (
                    'accepted','partial_rejected'
                )
                """,
                (self.campaign_id,),
            ).fetchone()[0]
        )
        if memory_trigger == "pre_inference":
            if len(projection_bytes) >= self.memory_policy.soft_limit_bytes:
                creation_trigger = "soft_limit_before_inference"
            elif (
                completed_cycles > 0
                and completed_cycles
                % self.memory_policy.snapshot_interval_cycles
                == 0
            ):
                creation_trigger = "periodic_completed_cycles"
            else:
                creation_trigger = "pre_inference"
        else:
            creation_trigger = memory_trigger
        memory_snapshot_id = new_id("scientific-memory")
        memory_version = int(previous["version"]) + 1 if previous else 1
        source_counts = {
            table: int(
                self.store.connection.execute(
                    f"SELECT count(*) FROM {table} WHERE campaign_id=?",
                    (self.campaign_id,),
                ).fetchone()[0]
            )
            for table in (
                "director_action_batches",
                "director_actions",
                "research_hypotheses_v2",
                "research_lanes",
                "lane_metric_windows",
                "campaign_candidates",
                "campaign_verification_jobs",
            )
        }
        memory_record = memory_snapshot_record(
            memory_snapshot_id=memory_snapshot_id,
            campaign_id=self.campaign_id,
            version=memory_version,
            parent_snapshot_id=(
                str(previous["memory_snapshot_id"]) if previous else None
            ),
            director_snapshot_id=snapshot_id,
            projection=projection,
            source_high_water=high_water,
            source_record_counts=source_counts,
            creation_trigger=creation_trigger,
            hard_limit_bytes=self.memory_policy.hard_limit_bytes,
        )
        snapshot["scientific_memory_snapshot_id"] = memory_snapshot_id
        snapshot["scientific_memory_projection"] = projection
        snapshot["scientific_memory"] = {
            "version": memory_version,
            "sha256": memory_record["sha256"],
            "byte_size": memory_record["byte_size"],
            "estimated_token_count": memory_record[
                "estimated_token_count"
            ],
            "creation_trigger": creation_trigger,
        }
        canonical_json(snapshot, max_bytes=MAX_SNAPSHOT_BYTES)
        relative = Path("snapshots") / f"{snapshot_id}.json"
        path = self.campaign_dir / relative
        payload = canonical_json(snapshot, max_bytes=MAX_SNAPSHOT_BYTES) + b"\n"
        _atomic_write(path, payload)
        self.store.record_snapshot(
            snapshot_id=snapshot_id,
            campaign_id=self.campaign_id,
            campaign_state_version=int(campaign["state_version"]),
            high_water=high_water,
            artifact_ref=str(relative),
            artifact_sha256=hashlib.sha256(payload).hexdigest(),
            payload_bytes=len(payload),
            memory_snapshot_id=memory_snapshot_id,
        )
        self.store.record_memory_snapshot(memory_record)
        active = [
            lane
            for lane in lanes
            if lane["state"] in {"starting", "running", "paused", "stopping"}
        ]
        prepared = prepare_director_state_v2(
            snapshot,
            hard_limit_bytes=self.memory_policy.hard_limit_bytes,
        )
        registry = prepared.evidence_registry
        context = DecisionContext(
            snapshot_id=str(prepared.state["source_snapshot_id"]),
            evidence_ids=evidence_registry_ids(registry),
            lane_versions={
                str(lane["lane_id"]): int(lane["lane_version"])
                for lane in active
            },
            lane_algorithms={
                str(lane["lane_id"]): str(lane["algorithm"])
                for lane in active
            },
            checkpoint_ids=evidence_registry_ids(
                registry, kinds=frozenset({"checkpoint"})
            ),
            candidate_ids=evidence_registry_ids(
                registry, kinds=frozenset({"candidate"})
            ),
            hypothesis_ids=evidence_registry_ids(
                registry, kinds=frozenset({"hypothesis"})
            ),
            max_active_lanes=self.manager.max_active_lanes,
            advisory_target_ids=evidence_registry_ids(
                prepared.advisory_target_registry
            ),
            executable_target_ids=evidence_registry_ids(
                prepared.executable_target_registry
            ),
            applicable_action_types=frozenset(
                prepared.state["allowed_action_space"]["actions"]
            ),
            reserved_action_ids=frozenset(
                str(row["action_id"])
                for row in self.store.connection.execute(
                    "SELECT action_id FROM director_actions"
                )
            ),
        )
        return snapshot, context

    def _lanes(self, evidence: set[str]) -> list[dict[str, Any]]:
        rows = self.store.connection.execute(
            """
            SELECT * FROM research_lanes WHERE campaign_id=?
            ORDER BY CASE state
                WHEN 'running' THEN 0 WHEN 'starting' THEN 1
                WHEN 'paused' THEN 2 ELSE 3 END, updated_at DESC
            LIMIT ?
            """,
            (self.campaign_id, self.maximum_lanes),
        ).fetchall()
        values: list[dict[str, Any]] = []
        for row in rows:
            lane_id = str(row["lane_id"])
            runtime = self.manager.lanes.get(lane_id)
            metrics = (
                runtime.telemetry.recent()
                if runtime is not None
                else self._stored_metrics(lane_id)
            )
            metric_evidence = (
                f"lane-metrics:{lane_id}:"
                f"{int(metrics.get('end_high_water', 0))}"
            )
            evidence.add(metric_evidence)
            active_state = row["state"] in {
                "starting",
                "running",
                "paused",
                "stopping",
            }
            checkpoint_id = (
                runtime.latest_checkpoint_id
                if runtime is not None and active_state
                else (
                    _checkpoint_id_from_ref(row["checkpoint_ref"])
                    if active_state
                    else None
                )
            )
            if checkpoint_id is not None:
                evidence.add(f"checkpoint:{checkpoint_id}")
            values.append(
                {
                    "lane_id": lane_id,
                    "lane_version": int(row["lane_version"]),
                    "state": row["state"],
                    "target": row["target"],
                    "algorithm": row["algorithm"],
                    "graph_family": row["graph_family"],
                    "parameters": json.loads(row["current_parameters_json"]),
                    "checkpoint_id": checkpoint_id,
                    "parent_lane_id": row["parent_lane_id"],
                    "parent_checkpoint_id": row["parent_checkpoint_ref"],
                    "metrics": metrics,
                    "metric_evidence_id": metric_evidence,
                    "resource_share": float(row["resource_share"]),
                    "lease": {"expires_at": row["lease_expires_at"]},
                }
            )
        return values

    def _stored_metrics(self, lane_id: str) -> dict[str, Any]:
        rows = self.store.connection.execute(
            """
            SELECT metrics_json FROM lane_metric_windows
            WHERE lane_id=? ORDER BY end_high_water DESC LIMIT 8
            """,
            (lane_id,),
        ).fetchall()
        telemetry = TelemetrySeries(maximum=8)
        for row in reversed(rows):
            telemetry.append(json.loads(row[0]))
        return telemetry.recent()

    def _recent_actions(self, evidence: set[str]) -> list[dict[str, Any]]:
        rows = self.store.connection.execute(
            """
            SELECT a.action_id, a.action_type, a.target_lane_id,
                   a.expected_lane_version, a.expected_effect,
                   a.parameters_json, a.hypothesis_ids_json,
                   a.evaluation_window_json, a.validation_status,
                   a.validation_detail,
                   o.application_status, o.resulting_lane_id,
                   o.resulting_lane_version, o.observed_effect_json,
                   o.expectation_met, o.failure_kind, o.failure_detail,
                   o.applied_at, o.evaluated_at
            FROM director_actions a
            LEFT JOIN director_action_outcomes o ON o.action_id=a.action_id
            WHERE a.campaign_id=?
            ORDER BY a.created_at DESC, a.rowid DESC LIMIT ?
            """,
            (self.campaign_id, self.maximum_actions),
        ).fetchall()
        values = []
        full_ancestry_retained = False
        for row in rows:
            evidence_id = f"action:{row['action_id']}"
            evidence.add(evidence_id)
            observed_effect = None
            if row["observed_effect_json"]:
                raw_effect = json.loads(row["observed_effect_json"])
                is_batch = "evaluation_count" in raw_effect
                observed_effect = _compact_observed_effect(
                    raw_effect,
                    full_ancestry=not full_ancestry_retained,
                )
                full_ancestry_retained = full_ancestry_retained or is_batch
            values.append(
                {
                    "evidence_id": evidence_id,
                    "action_id": row["action_id"],
                    "type": row["action_type"],
                    "target_lane_id": row["target_lane_id"],
                    "expected_lane_version": row["expected_lane_version"],
                    "expected_effect": row["expected_effect"],
                    "previous_director_hypothesis_ids": json.loads(
                        row["hypothesis_ids_json"]
                    ),
                    "effective_parameters": json.loads(
                        row["parameters_json"]
                    ).get("effective_parameters", {}),
                    "ignored_parameters": json.loads(
                        row["parameters_json"]
                    ).get("ignored_parameters", {}),
                    "rejected_parameters": json.loads(
                        row["parameters_json"]
                    ).get("rejected_parameters", {}),
                    "parameter_effects": json.loads(
                        row["parameters_json"]
                    ).get("parameter_effects", {}),
                    "evaluation_window": json.loads(
                        row["evaluation_window_json"]
                    ),
                    "validation_status": row["validation_status"],
                    "validation_detail": row["validation_detail"],
                    "application_status": row["application_status"],
                    "resulting_lane_id": row["resulting_lane_id"],
                    "resulting_lane_version": row["resulting_lane_version"],
                    "observed_effect": (
                        observed_effect
                    ),
                    "expectation_met": (
                        bool(row["expectation_met"])
                        if row["expectation_met"] is not None
                        else None
                    ),
                    "measured_outcome_against_expected_signal": {
                        "expected_signal": row["expected_effect"],
                        "measured_outcome": (
                            {
                                key: observed_effect[key]
                                for key in (
                                    "outcome_artifact_sha256",
                                    "evaluation_count",
                                    "best_score",
                                    "termination_reason",
                                )
                                if observed_effect is not None
                                and key in observed_effect
                            }
                            if observed_effect is not None
                            else None
                        ),
                        "expectation_met": (
                            bool(row["expectation_met"])
                            if row["expectation_met"] is not None
                            else None
                        ),
                    },
                    "failure_kind": row["failure_kind"],
                    "failure_detail": row["failure_detail"],
                    "applied_at": row["applied_at"],
                    "evaluated_at": row["evaluated_at"],
                }
            )
        return values

    def _continuity(self, campaign: dict[str, Any]) -> dict[str, Any]:
        """Bounded current ledger plus recent deltas for stateless continuity."""

        hypotheses = [
            {
                "hypothesis_id": row["hypothesis_id"],
                "statement": row["statement"],
                "confidence": float(row["confidence"]),
                "status": row["status"],
            }
            for row in self.store.connection.execute(
                """
                SELECT h.* FROM research_hypotheses_v2 h
                JOIN (
                    SELECT hypothesis_id, max(rowid) AS latest
                    FROM research_hypotheses_v2 WHERE campaign_id=?
                    GROUP BY hypothesis_id
                ) current ON current.latest=h.rowid
                ORDER BY h.created_at DESC, h.rowid DESC LIMIT 64
                """,
                (self.campaign_id,),
            )
        ]
        assessments = self.store.connection.execute(
            """
            SELECT campaign_assessment, created_at, decision_batch_id
            FROM director_action_batches
            WHERE campaign_id=? AND validation_status IN (
                'accepted','partial_rejected'
            )
            ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (self.campaign_id,),
        ).fetchone()
        verifier = [
            _exact_verifier_continuity_fact(row)
            for row in self.store.connection.execute(
                """
                SELECT candidate_id, state, certification_status,
                       certification_artifact_ref
                FROM campaign_verification_jobs WHERE campaign_id=?
                  AND state IN ('completed','unknown','failed')
                ORDER BY completed_at DESC, rowid DESC LIMIT 32
                """,
                (self.campaign_id,),
            )
        ]
        candidates = [
            {
                "candidate_id": row["candidate_id"],
                "state": row["state"],
                "score": json.loads(row["score_json"]),
                "lane_id": row["lane_id"],
                "checkpoint_ref": row["checkpoint_ref"],
                "certification_status": row["certification_status"],
            }
            for row in self.store.connection.execute(
                """
                SELECT candidate_id, state, score_json, lane_id,
                       checkpoint_ref, certification_status
                FROM campaign_candidates WHERE campaign_id=?
                ORDER BY created_at DESC, rowid DESC LIMIT 64
                """,
                (self.campaign_id,),
            )
        ]
        lanes = [
            {
                "lane_id": row["lane_id"],
                "state": row["state"],
                "algorithm": row["algorithm"],
                "graph_family": row["graph_family"],
                "parameters": json.loads(row["current_parameters_json"]),
                "checkpoint_id": _checkpoint_id_from_ref(
                    row["checkpoint_ref"]
                ),
                "telemetry_high_water": int(
                    row["telemetry_high_water"] or 0
                ),
            }
            for row in self.store.connection.execute(
                """
                SELECT lane_id, state, algorithm, graph_family,
                       current_parameters_json, checkpoint_ref,
                       checkpoint_sha256, telemetry_high_water
                FROM research_lanes WHERE campaign_id=?
                ORDER BY updated_at DESC, rowid DESC LIMIT 64
                """,
                (self.campaign_id,),
            )
        ]
        validation_feedback = []
        for row in self.store.connection.execute(
            """
            SELECT action_id, validation_detail FROM director_actions
            WHERE campaign_id=? AND validation_status='stale_target'
            ORDER BY created_at DESC, rowid DESC LIMIT 4
            """,
            (self.campaign_id,),
        ):
            try:
                detail = json.loads(str(row["validation_detail"]))
            except (TypeError, json.JSONDecodeError):
                detail = {"error": "stale_candidate_target"}
            validation_feedback.append(
                {"action_id": row["action_id"], **detail}
            )
        attempt = self.store.latest_execution_attempt(self.campaign_id)
        effective_resources = (
            json.loads(str(attempt["effective_resource_json"]))
            if attempt is not None
            else {}
        )
        executable_candidates = sorted(
            item["candidate_id"]
            for item in candidates
            if item["state"] in {"retained", "promoted"}
        )
        return {
            "hypothesis_ledger": hypotheses,
            "latest_valid_assessment": (
                dict(assessments) if assessments is not None else None
            ),
            "exact_verifier_outcomes": verifier,
            "candidate_ledger": candidates,
            "current_executable_candidate_ids": executable_candidates,
            "current_executable_checkpoint_ids": sorted(
                str(checkpoint_id)
                for checkpoint_id in self.manager.checkpoints
            ),
            "lane_and_checkpoint_ledger": lanes,
            "explored_regions": [
                {
                    "graph_family": lane["graph_family"],
                    "algorithm": lane["algorithm"],
                    "parameters": lane["parameters"],
                    "evaluations": lane["telemetry_high_water"],
                    "state": lane["state"],
                }
                for lane in lanes
            ],
            "unresolved_scientific_questions": [
                item["statement"]
                for item in hypotheses
                if item["status"] not in {"rejected", "resolved"}
            ],
            "validation_feedback": validation_feedback,
            "infrastructure_fault": (
                {
                    "kind": campaign["fault_kind"],
                    "detail": campaign["fault_detail"],
                    "is_scientific_negative_evidence": False,
                }
                if campaign.get("fault_kind")
                else None
            ),
            "execution_attempt": {
                "attempt_id": attempt["attempt_id"] if attempt else None,
                "effective_resources": effective_resources,
            },
        }

    def _hypotheses(self, evidence: set[str]) -> list[dict[str, Any]]:
        rows = self.store.connection.execute(
            """
            SELECT h.* FROM research_hypotheses_v2 h
            JOIN (
                SELECT hypothesis_id, MAX(rowid) AS latest
                FROM research_hypotheses_v2 WHERE campaign_id=?
                GROUP BY hypothesis_id
            ) current ON current.latest=h.rowid
            ORDER BY h.created_at DESC LIMIT ?
            """,
            (self.campaign_id, self.maximum_hypotheses),
        ).fetchall()
        values = []
        for row in rows:
            revision_evidence = f"hypothesis:{row['hypothesis_revision_id']}"
            evidence.add(revision_evidence)
            values.append(
                {
                    "evidence_id": revision_evidence,
                    "hypothesis_id": row["hypothesis_id"],
                    "revision_id": row["hypothesis_revision_id"],
                    "statement": row["statement"],
                    "confidence": float(row["confidence"]),
                    "status": row["status"],
                    "evidence_for": json.loads(row["evidence_for_json"]),
                    "evidence_against": json.loads(
                        row["evidence_against_json"]
                    ),
                }
            )
        return values

    def _global_best(
        self, evidence: set[str]
    ) -> tuple[dict[str, Any] | None, set[str]]:
        rows = self.store.connection.execute(
            """
            SELECT * FROM campaign_candidates
            WHERE campaign_id=? AND state!='rejected'
            ORDER BY created_at DESC LIMIT 256
            """,
            (self.campaign_id,),
        ).fetchall()
        if rows:
            candidates = [
                (row, json.loads(row["score_json"])) for row in rows
            ]
            best_row, best_score = min(
                candidates,
                key=lambda item: tuple(item[1]["ordering_key"]),
            )
            candidate_ids = {
                str(row["candidate_id"]) for row, _ in candidates
            }
            for candidate_id in candidate_ids:
                evidence.add(f"candidate-summary:{candidate_id}")
            candidate_id = str(best_row["candidate_id"])
            graph = BitGraph.from_graph6(str(best_row["graph6"]))
            return (
                {
                    "candidate_id": candidate_id,
                    "evidence_id": f"candidate-summary:{candidate_id}",
                    "lane_id": best_row["lane_id"],
                    "score": best_score,
                    "order": graph.n,
                    "size": graph.size(),
                    "minimum_degree": graph.minimum_degree(),
                    "checkpoint_id": best_row["checkpoint_ref"],
                    "certification_status": best_row[
                        "certification_status"
                    ]
                    or "not_submitted",
                },
                candidate_ids,
            )
        improvements = [
            item
            for runtime in self.manager.lanes.values()
            for item in runtime.improvements
        ]
        if not improvements:
            return None, set()
        best = min(
            improvements,
            key=lambda item: tuple(item["score"]["ordering_key"]),
        )
        candidate_hash = hashlib.sha256(
            str(best["graph6"]).encode("ascii")
        ).hexdigest()
        candidate_id = f"candidate-{candidate_hash[:24]}"
        evidence_id = f"candidate-summary:{candidate_id}"
        evidence.add(evidence_id)
        return (
            {
                "candidate_id": candidate_id,
                "evidence_id": evidence_id,
                "lane_id": best["lane_id"],
                "score": best["score"],
                "checkpoint_id": best["checkpoint_id"],
                "certification_status": "not_submitted",
            },
            {candidate_id},
        )

    def _verification(self, evidence: set[str]) -> dict[str, Any]:
        rows = self.store.connection.execute(
            """
            SELECT * FROM campaign_verification_jobs
            WHERE campaign_id=? ORDER BY created_at DESC LIMIT 32
            """,
            (self.campaign_id,),
        ).fetchall()
        jobs = []
        for row in rows:
            evidence_id = f"verification:{row['verification_job_id']}"
            evidence.add(evidence_id)
            jobs.append(
                {
                    "evidence_id": evidence_id,
                    "verification_job_id": row["verification_job_id"],
                    "candidate_id": row["candidate_id"],
                    "state": row["state"],
                    "certification_status": row["certification_status"],
                }
            )
        return {
            "authority": "M4_independent_verifier",
            "queue_depth": sum(job["state"] == "queued" for job in jobs),
            "jobs": jobs,
        }

    def _resources(self, verification: dict[str, Any]) -> dict[str, Any]:
        cpu_total = os.cpu_count() or 1
        active = len(self.manager.active_lanes())
        return {
            "cpu_total": cpu_total,
            "cpu_available": max(0, cpu_total - active),
            "max_active_lanes": self.manager.max_active_lanes,
            "memory_available_bytes": _memory_available_bytes(),
            "coordinator_rss_bytes": current_rss_bytes(),
            "lane_rss_bytes": sum(
                process_tree_rss_bytes(runtime.process.pid)
                for runtime in self.manager.active_lanes()
            ),
            "verifier_queue_depth": verification["queue_depth"],
        }


def _checkpoint_id_from_ref(value: Any) -> str | None:
    if not value:
        return None
    return Path(str(value)).stem


def _exact_verifier_continuity_fact(row: Any) -> dict[str, Any]:
    status = row["certification_status"]
    fact = {
        "candidate_id": row["candidate_id"],
        "certification_status": status,
    }
    if status is None:
        fact["state"] = row["state"]
    return fact


def _compact_observed_effect(
    value: dict[str, Any], *, full_ancestry: bool = True
) -> dict[str, Any]:
    """Remove graph bodies, checkpoints and duplicated raw metrics from prompts."""

    allowed = {
        "algorithm",
        "parameters",
        "seed",
        "graph_family",
        "graph_order",
        "evaluation_count",
        "throughput",
        "elapsed_seconds",
        "peak_rss_bytes",
        "initial_score",
        "best_score",
        "score_trajectory_summary",
        "operator_statistics",
        "mutation_ancestry",
        "timing",
        "best_candidate_identifier",
        "verifier_result",
        "termination_reason",
        "decision_before_search",
        "outcome_artifact_ref",
        "outcome_artifact_sha256",
        "lane_id",
        "decision_batch_id",
        "action_id",
        "metric_window_id",
        "checkpoint_id",
    }
    compact = {key: value[key] for key in allowed if key in value}
    ancestry = compact.get("mutation_ancestry")
    if isinstance(ancestry, dict):
        global_records = list(
            ancestry.get("global_record_improvements", [])
        )
        final_best = list(ancestry.get("final_best_ancestry", []))
        compact["mutation_ancestry"] = {
            "global_record_count": len(global_records),
            "global_record_samples": global_records[
                -16 if full_ancestry else -4:
            ],
            "global_record_samples_truncated": len(global_records)
            > (16 if full_ancestry else 4),
            "final_best_ancestry": final_best[
                -64 if full_ancestry else -8:
            ],
            "final_best_ancestry_truncated": len(final_best)
            > (64 if full_ancestry else 8),
            "ancestry_detail": (
                "latest_outcome" if full_ancestry else "historical_summary"
            ),
            "limit_per_retained_candidate": ancestry.get(
                "limit_per_retained_candidate", 64
            ),
            "rejected_non_record_candidates_stored": ancestry.get(
                "rejected_non_record_candidates_stored", 0
            ),
            "full_outcome_artifact_ref": value.get(
                "outcome_artifact_ref"
            ),
            "full_outcome_artifact_sha256": value.get(
                "outcome_artifact_sha256"
            ),
        }
    metrics = value.get("metrics")
    if isinstance(metrics, dict):
        for key in (
            "best_evaluation",
            "plateau_evaluations",
            "plateau_signal",
            "global_record_count",
            "accepted",
            "duplicates",
            "diversity",
            "actual_restart_occurred",
            "actual_restart_count",
            "score_counts_truncated_by_witness_cap",
        ):
            if key in metrics:
                compact[key] = metrics[key]
    return compact


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _memory_available_bytes() -> int:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (FileNotFoundError, PermissionError, ValueError):
        return 0
    return 0


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
