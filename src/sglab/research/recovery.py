from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json

from .actions import LaneActionDispatcher
from .lanes import (
    LaneManager,
    LaneSpec,
    checkpoint_scientific_sha256,
    checkpoint_seed_generation_sha256,
)
from .store import ResearchStore


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    integrity: str
    restored_lane_ids: tuple[str, ...]
    failed_lane_ids: tuple[str, ...]
    interrupted_turns: int
    requeued_verifications: int
    interrupted_sessions: int
    resume_thread_id: str | None
    redispatched_action_ids: tuple[str, ...]


class CampaignRecovery:
    """Reconcile durable state and restore exact lane checkpoints."""

    def __init__(
        self,
        *,
        store: ResearchStore,
        manager: LaneManager,
        dispatcher: LaneActionDispatcher,
        campaign_id: str,
        campaign_dir: Path,
    ):
        self.store = store
        self.manager = manager
        self.dispatcher = dispatcher
        self.campaign_id = campaign_id
        self.campaign_dir = campaign_dir.resolve()

    def recover(self) -> RecoveryReport:
        integrity = str(
            self.store.connection.execute("PRAGMA integrity_check").fetchone()[0]
        )
        if integrity != "ok":
            raise RuntimeError(f"campaign database integrity failure: {integrity}")
        interrupted = self.store.recover_interrupted_records(self.campaign_id)
        restored: list[str] = []
        failed: list[str] = []
        rows = self.store.connection.execute(
            """
            SELECT * FROM research_lanes
            WHERE campaign_id=? AND state IN ('starting', 'running', 'paused')
            ORDER BY created_at, lane_id
            """,
            (self.campaign_id,),
        ).fetchall()
        for row in rows:
            lane_id = str(row["lane_id"])
            try:
                checkpoint = self._checkpoint(row)
                seed_lineage = tuple(json.loads(row["seed_lineage_json"]))
                seed = int(seed_lineage[-1]) if seed_lineage else 0
                spec = LaneSpec(
                    lane_id=lane_id,
                    campaign_id=self.campaign_id,
                    target=str(row["target"]),
                    algorithm=str(row["algorithm"]),
                    graph_family=str(row["graph_family"]),
                    seed=seed,
                    parameters=json.loads(row["current_parameters_json"]),
                    resource_share=float(row["resource_share"]),
                    lane_version=int(row["lane_version"]),
                    parent_lane_id=row["parent_lane_id"],
                    created_by_action_id=row["created_by_action_id"],
                    parent_checkpoint_id=row["parent_checkpoint_ref"],
                    seed_lineage=seed_lineage,
                )
                if not self.store.prepare_lane_recovery(
                    lane_id, int(row["lane_version"])
                ):
                    raise RuntimeError("lane changed during recovery")
                runtime = self.manager.start_lane(spec, checkpoint=checkpoint)
                self.manager.register_restored_checkpoint(
                    lane_id, checkpoint
                )
                if row["state"] == "paused":
                    runtime.pause_event.set()
                    runtime.state = "paused"
                restored.append(lane_id)
            except Exception:
                failed.append(lane_id)
                self.store.record_lane_exit(
                    lane_id=lane_id,
                    lane_version=int(row["lane_version"]),
                    failed=True,
                    detail="checkpoint recovery failed",
                )
        archived_rows = self.store.connection.execute(
            """
            SELECT * FROM research_lanes
            WHERE campaign_id=? AND checkpoint_ref IS NOT NULL
            ORDER BY updated_at DESC, lane_id
            """,
            (self.campaign_id,),
        ).fetchall()
        for row in archived_rows:
            try:
                checkpoint = self._checkpoint(row)
            except Exception:
                continue
            checkpoint_id = str(checkpoint["checkpoint_id"])
            if checkpoint_id not in self.manager.checkpoints:
                self.manager.register_archived_checkpoint(checkpoint)
        candidate_checkpoints = self.store.connection.execute(
            """
            SELECT c.checkpoint_ref, c.lane_id, c.lane_version,
                   l.checkpoint_sha256
            FROM campaign_candidates c
            JOIN research_lanes l ON l.lane_id=c.lane_id
            WHERE c.campaign_id=? AND c.checkpoint_ref IS NOT NULL
            ORDER BY c.created_at DESC, c.candidate_id
            """,
            (self.campaign_id,),
        ).fetchall()
        for row in candidate_checkpoints:
            path = (
                self.campaign_dir / str(row["checkpoint_ref"])
            ).resolve()
            try:
                path.relative_to(self.campaign_dir)
                checkpoint = json.loads(path.read_text(encoding="utf-8"))
                actual = checkpoint_scientific_sha256(checkpoint)
                seed_actual = checkpoint_seed_generation_sha256(
                    checkpoint
                )
                if (
                    checkpoint.get("sha256") != actual
                    or (
                        seed_actual is not None
                        and checkpoint.get("seed_generation_sha256")
                        != seed_actual
                    )
                    or checkpoint.get("lane_id") != row["lane_id"]
                    or int(checkpoint.get("lane_version", -1))
                    != int(row["lane_version"])
                ):
                    continue
                checkpoint_id = str(checkpoint["checkpoint_id"])
                if checkpoint_id not in self.manager.checkpoints:
                    self.manager.register_archived_checkpoint(checkpoint)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
        dispatched = self.dispatcher.dispatch_pending()
        return RecoveryReport(
            integrity=integrity,
            restored_lane_ids=tuple(restored),
            failed_lane_ids=tuple(failed),
            interrupted_turns=interrupted["interrupted_turns"],
            requeued_verifications=interrupted["requeued_verifications"],
            interrupted_sessions=interrupted["interrupted_sessions"],
            resume_thread_id=self.store.latest_app_server_thread(
                self.campaign_id
            ),
            redispatched_action_ids=tuple(dispatched),
        )

    def _checkpoint(self, row: Any) -> dict[str, Any]:
        reference = row["checkpoint_ref"]
        if not reference:
            raise RuntimeError("active lane has no checkpoint")
        path = (self.campaign_dir / str(reference)).resolve()
        try:
            path.relative_to(self.campaign_dir)
        except ValueError:
            raise RuntimeError("checkpoint escaped campaign directory") from None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError("checkpoint is not an object")
        claimed = str(payload.get("sha256", ""))
        actual = checkpoint_scientific_sha256(payload)
        seed_actual = checkpoint_seed_generation_sha256(payload)
        if claimed != actual or str(row["checkpoint_sha256"]) != actual:
            raise RuntimeError("checkpoint hash mismatch")
        if (
            seed_actual is not None
            and payload.get("seed_generation_sha256") != seed_actual
        ):
            raise RuntimeError("checkpoint seed telemetry hash mismatch")
        if payload.get("lane_id") != row["lane_id"]:
            raise RuntimeError("checkpoint lane mismatch")
        if int(payload.get("lane_version", -1)) != int(row["lane_version"]):
            raise RuntimeError("checkpoint lane version mismatch")
        return payload
