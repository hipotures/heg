from __future__ import annotations

import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from sglab.research.actions import LaneActionDispatcher
from sglab.research.lanes import (
    LaneManager,
    LaneSpec,
    _LaneKernel,
)
from sglab.research.recovery import CampaignRecovery
from sglab.research.store import ResearchStore


def spec() -> LaneSpec:
    return LaneSpec(
        lane_id="lane-1",
        campaign_id="campaign-1",
        target="erdos_gyarfas",
        algorithm="simulated_annealing",
        graph_family="connected_cubic",
        seed=17,
        parameters={
            "order": 8,
            "batch_candidates": 100,
            "witness_cap": 4,
            "temperature": 1.0,
            "cooling": 0.999,
            "restart_threshold": 1000,
        },
        resource_share=1,
        created_by_action_id="bootstrap",
        seed_lineage=(17,),
    )


class CampaignRecoveryTests(unittest.TestCase):
    def test_seed_telemetry_envelope_is_verified_on_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            kernel = _LaneKernel(spec(), None, None)
            try:
                checkpoint = kernel.checkpoint(0)
            finally:
                kernel.close()
            checkpoint_path = root / "checkpoint.json"
            row = {
                "checkpoint_ref": checkpoint_path.name,
                "checkpoint_sha256": checkpoint["sha256"],
                "lane_id": checkpoint["lane_id"],
                "lane_version": checkpoint["lane_version"],
            }
            recovery = CampaignRecovery(
                store=SimpleNamespace(),
                manager=SimpleNamespace(),
                dispatcher=SimpleNamespace(),
                campaign_id="campaign-1",
                campaign_dir=root,
            )

            checkpoint_path.write_text(
                json.dumps(checkpoint), encoding="utf-8"
            )
            self.assertEqual(
                recovery._checkpoint(row)["checkpoint_id"],
                checkpoint["checkpoint_id"],
            )

            tampered = copy.deepcopy(checkpoint)
            tampered["seed_generation"]["total"]["calls"] += 1
            checkpoint_path.write_text(
                json.dumps(tampered), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                RuntimeError, "seed telemetry hash mismatch"
            ):
                recovery._checkpoint(row)

            incomplete = copy.deepcopy(checkpoint)
            incomplete.pop("seed_generation_sha256")
            checkpoint_path.write_text(
                json.dumps(incomplete), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                ValueError, "telemetry envelope is incomplete"
            ):
                recovery._checkpoint(row)

    def test_exact_checkpoint_state_resumes_without_restarting_high_water(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "campaign.sqlite3"
            store = ResearchStore(path)
            manager = LaneManager(root, checkpoints_per_lane=4)
            dispatcher = LaneActionDispatcher(
                store=store,
                manager=manager,
                campaign_id="campaign-1",
            )
            store.create_campaign(
                campaign_id="campaign-1",
                target="erdos_gyarfas",
                target_definition_sha256="a" * 64,
                stop_mode="until_success",
                deadline_at=None,
            )
            lane = spec()
            store.create_lane(
                lane_id=lane.lane_id,
                campaign_id=lane.campaign_id,
                target=lane.target,
                parent_lane_id=None,
                parent_checkpoint_ref=None,
                action_id="bootstrap",
                algorithm=lane.algorithm,
                graph_family=lane.graph_family,
                parameters=lane.parameters,
                seed_lineage=list(lane.seed_lineage),
                resource_share=lane.resource_share,
                lease_expires_at=None,
            )
            store.mark_lane_running(lane.lane_id)
            manager.start_lane(lane)
            self._poll_until(
                dispatcher,
                lambda: manager.lanes["lane-1"].high_water >= 500,
            )
            row = store.connection.execute(
                "SELECT * FROM research_lanes WHERE lane_id='lane-1'"
            ).fetchone()
            checkpoint_id = manager.lanes["lane-1"].latest_checkpoint_id
            high_water = int(row["telemetry_high_water"])
            checkpoint_sha = str(row["checkpoint_sha256"])
            manager.shutdown()
            store.close()

            recovered_store = ResearchStore(path)
            recovered_manager = LaneManager(root, checkpoints_per_lane=4)
            recovered_dispatcher = LaneActionDispatcher(
                store=recovered_store,
                manager=recovered_manager,
                campaign_id="campaign-1",
            )
            try:
                report = CampaignRecovery(
                    store=recovered_store,
                    manager=recovered_manager,
                    dispatcher=recovered_dispatcher,
                    campaign_id="campaign-1",
                    campaign_dir=root,
                ).recover()
                self.assertEqual(report.integrity, "ok")
                self.assertEqual(report.restored_lane_ids, ("lane-1",))
                first = recovered_dispatcher.poll_once(timeout=3)
                self.assertEqual(first["kind"], "checkpoint")
                self.assertEqual(
                    first["checkpoint"]["checkpoint_id"], checkpoint_id
                )
                self.assertEqual(first["checkpoint"]["sha256"], checkpoint_sha)
                self.assertEqual(
                    first["checkpoint"]["high_water"], high_water
                )
                self.assertEqual(
                    recovered_manager.lanes["lane-1"].high_water, high_water
                )
                self._poll_until(
                    recovered_dispatcher,
                    lambda: recovered_manager.lanes["lane-1"].high_water
                    > high_water,
                )
                generation = recovered_store.connection.execute(
                    """
                    SELECT process_generation FROM research_lanes
                    WHERE lane_id='lane-1'
                    """
                ).fetchone()[0]
                self.assertEqual(generation, 1)
            finally:
                recovered_manager.shutdown()
                recovered_store.close()

    def _poll_until(self, dispatcher, predicate, timeout: float = 8) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            dispatcher.poll_once(timeout=0.05)
            if predicate():
                return
        raise AssertionError("lane recovery condition timed out")
