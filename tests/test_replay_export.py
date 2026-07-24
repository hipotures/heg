from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from sglab.research.export import export_campaign
from sglab.research.lanes import LaneManager, LaneSpec, replay_micro_batches
from sglab.research.replay import audit_campaign_artifacts
from sglab.research.snapshot import SnapshotBuilder
from sglab.research.store import ResearchStore


def lane_spec() -> LaneSpec:
    return LaneSpec(
        lane_id="lane-replay",
        campaign_id="campaign-1",
        target="erdos_gyarfas",
        algorithm="iterated_local_search",
        graph_family="connected_cubic",
        seed=91,
        parameters={
            "order": 8,
            "batch_candidates": 100,
            "witness_cap": 4,
            "tabu_tenure": 16,
            "perturbation_interval": 8,
        },
        resource_share=1,
        seed_lineage=(91,),
    )


class ReplayAndExportTests(unittest.TestCase):
    def test_export_uses_consistent_sqlite_backup_and_excludes_auth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign-live.sqlite3")
            manager = LaneManager(root)
            try:
                store.create_campaign(
                    campaign_id="campaign-1",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="until_success",
                    deadline_at=None,
                )
                snapshot, _ = SnapshotBuilder(
                    store=store,
                    manager=manager,
                    campaign_id="campaign-1",
                    campaign_dir=root,
                ).publish()
                (root / "auth.json").write_text(
                    '{"secret":"must-not-export"}', encoding="utf-8"
                )
                output = root / "exports" / "campaign.zip"
                report = export_campaign(
                    store=store,
                    campaign_id="campaign-1",
                    campaign_dir=root,
                    output=output,
                )
                self.assertFalse(report["authentication_included"])
                with zipfile.ZipFile(output) as archive:
                    names = set(archive.namelist())
                    self.assertIn("campaign.sqlite3", names)
                    self.assertIn("manifest.json", names)
                    self.assertNotIn("auth.json", names)
                    extracted = root / "exported.sqlite3"
                    extracted.write_bytes(archive.read("campaign.sqlite3"))
                    manifest = json.loads(archive.read("manifest.json"))
                database = sqlite3.connect(extracted)
                self.assertEqual(
                    database.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )
                self.assertEqual(
                    database.execute(
                        "SELECT count(*) FROM research_campaigns"
                    ).fetchone()[0],
                    1,
                )
                database.close()
                self.assertFalse(manifest["authentication_included"])
                audit = audit_campaign_artifacts(
                    store=store,
                    campaign_id="campaign-1",
                    campaign_dir=root,
                )
                self.assertTrue(audit["valid"])
                snapshot_path = (
                    root / "snapshots" / f"{snapshot['snapshot_id']}.json"
                )
                snapshot_path.write_text("{}\n", encoding="utf-8")
                self.assertFalse(
                    audit_campaign_artifacts(
                        store=store,
                        campaign_id="campaign-1",
                        campaign_dir=root,
                    )["valid"]
                )
            finally:
                manager.shutdown()
                store.close()

    def test_scientific_micro_batch_replay_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = LaneManager(Path(directory))
            runtime = manager.start_lane(lane_spec())
            try:
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    event = manager.poll(timeout=0.05)
                    if (
                        event is not None
                        and event["kind"] == "checkpoint"
                        and event["checkpoint"]["high_water"] >= 100
                    ):
                        break
                else:
                    raise AssertionError("checkpoint not produced")
                checkpoint = dict(event["checkpoint"])
            finally:
                manager.shutdown()
            first = replay_micro_batches(lane_spec(), checkpoint, batches=2)
            second = replay_micro_batches(lane_spec(), checkpoint, batches=2)
            self.assertEqual(
                first["checkpoint"]["checkpoint_id"],
                second["checkpoint"]["checkpoint_id"],
            )
            self.assertEqual(
                first["checkpoint"]["rng_state"],
                second["checkpoint"]["rng_state"],
            )
            deterministic_keys = {
                "evaluated",
                "accepted",
                "legal",
                "improvements",
                "duplicates",
                "best_score",
                "best_scalar",
                "end_high_water",
            }
            self.assertEqual(
                [
                    {key: row[key] for key in deterministic_keys}
                    for row in first["metrics"]
                ],
                [
                    {key: row[key] for key in deterministic_keys}
                    for row in second["metrics"]
                ],
            )
