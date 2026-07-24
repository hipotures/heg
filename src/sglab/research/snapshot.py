from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import hashlib
import json
import os

from ..resources import current_rss_bytes
from ..model import BitGraph
from ..state import utc_now
from ..targets import target_summary
from .lanes import LaneManager
from .protocol import MAX_SNAPSHOT_BYTES, canonical_json
from .store import ResearchStore, new_id
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
    ):
        self.store = store
        self.manager = manager
        self.campaign_id = campaign_id
        self.campaign_dir = campaign_dir.resolve()
        self.maximum_lanes = maximum_lanes
        self.maximum_actions = maximum_actions
        self.maximum_hypotheses = maximum_hypotheses
        self.snapshot_dir = self.campaign_dir / "snapshots"
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)

    def publish(self) -> tuple[dict[str, Any], DecisionContext]:
        campaign = self.store.campaign(self.campaign_id)
        snapshot_id = new_id("snapshot")
        evidence: set[str] = set()
        lanes = self._lanes(evidence)
        recent_actions = self._recent_actions(evidence)
        hypotheses = self._hypotheses(evidence)
        global_best, candidate_ids = self._global_best(evidence)
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
            "available_evidence_ids": sorted(evidence)[:512],
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
            high_water={
                lane["lane_id"]: lane["metrics"].get("end_high_water", 0)
                for lane in lanes
            },
            artifact_ref=str(relative),
            artifact_sha256=hashlib.sha256(payload).hexdigest(),
            payload_bytes=len(payload),
        )
        active = [
            lane
            for lane in lanes
            if lane["state"] in {"starting", "running", "paused", "stopping"}
        ]
        context = DecisionContext(
            snapshot_id=snapshot_id,
            evidence_ids=frozenset(snapshot["available_evidence_ids"]),
            lane_versions={
                str(lane["lane_id"]): int(lane["lane_version"])
                for lane in active
            },
            lane_algorithms={
                str(lane["lane_id"]): str(lane["algorithm"])
                for lane in active
            },
            checkpoint_ids=frozenset(
                str(lane["checkpoint_id"])
                for lane in active
                if lane["checkpoint_id"] is not None
            ),
            candidate_ids=frozenset(candidate_ids),
            hypothesis_ids=frozenset(
                str(item["hypothesis_id"]) for item in hypotheses
            ),
            max_active_lanes=self.manager.max_active_lanes,
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
            checkpoint_id = (
                runtime.latest_checkpoint_id
                if runtime is not None
                else _checkpoint_id_from_ref(row["checkpoint_ref"])
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
        row = self.store.connection.execute(
            """
            SELECT metrics_json FROM lane_metric_windows
            WHERE lane_id=? ORDER BY end_high_water DESC LIMIT 1
            """,
            (lane_id,),
        ).fetchone()
        return json.loads(row[0]) if row is not None else {"windows": 0}

    def _recent_actions(self, evidence: set[str]) -> list[dict[str, Any]]:
        rows = self.store.connection.execute(
            """
            SELECT a.action_id, a.action_type, a.target_lane_id,
                   a.expected_lane_version, a.expected_effect,
                   a.evaluation_window_json, a.validation_status,
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
        for row in rows:
            evidence_id = f"action:{row['action_id']}"
            evidence.add(evidence_id)
            values.append(
                {
                    "evidence_id": evidence_id,
                    "action_id": row["action_id"],
                    "type": row["action_type"],
                    "target_lane_id": row["target_lane_id"],
                    "expected_lane_version": row["expected_lane_version"],
                    "expected_effect": row["expected_effect"],
                    "evaluation_window": json.loads(
                        row["evaluation_window_json"]
                    ),
                    "validation_status": row["validation_status"],
                    "application_status": row["application_status"],
                    "resulting_lane_id": row["resulting_lane_id"],
                    "resulting_lane_version": row["resulting_lane_version"],
                    "observed_effect": (
                        json.loads(row["observed_effect_json"])
                        if row["observed_effect_json"]
                        else None
                    ),
                    "expectation_met": (
                        bool(row["expectation_met"])
                        if row["expectation_met"] is not None
                        else None
                    ),
                    "failure_kind": row["failure_kind"],
                    "failure_detail": row["failure_detail"],
                    "applied_at": row["applied_at"],
                    "evaluated_at": row["evaluated_at"],
                }
            )
        return values

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
            "memory_available_bytes": _memory_available_bytes(),
            "coordinator_rss_bytes": current_rss_bytes(),
            "lane_rss_bytes": sum(
                current_rss_bytes(runtime.process.pid)
                for runtime in self.manager.active_lanes()
            ),
            "verifier_queue_depth": verification["queue_depth"],
        }


def _checkpoint_id_from_ref(value: Any) -> str | None:
    if not value:
        return None
    return Path(str(value)).stem


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
