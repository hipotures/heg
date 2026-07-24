from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sglab.research.lanes import LaneManager
from sglab.research.snapshot import SnapshotBuilder
from sglab.research.store import ResearchStore
from sglab.research.triggers import TriggerEngine


class TriggerEngineTests(unittest.TestCase):
    def test_debounce_coalescing_critical_and_maximum_interval(self) -> None:
        engine = TriggerEngine(
            debounce_seconds=5,
            min_review_seconds=0,
            max_review_seconds=100,
            candidate_delta=100,
        )
        engine._last_review_monotonic = 0
        engine.offer("stagnation", at="2026-07-24T00:00:00Z", now=10)
        engine.offer("diversity_collapse", now=11)
        self.assertFalse(engine.due(total_candidates=0, now=14))
        self.assertTrue(engine.due(total_candidates=0, now=15))
        batch = engine.consume(total_candidates=0, now=15)
        self.assertEqual(
            batch.reasons, ("diversity_collapse", "stagnation")
        )
        self.assertEqual(batch.first_event_at, "2026-07-24T00:00:00Z")

        engine.configure(
            {
                "min_wall_seconds": 30,
                "max_wall_seconds": 60,
                "candidate_delta": 500,
                "events": ["stagnation"],
            }
        )
        self.assertFalse(engine.offer("diversity_collapse", now=20))
        engine.offer("lane_failure", now=21)
        self.assertTrue(engine.due(total_candidates=0, now=21))
        engine.consume(total_candidates=0, now=21)
        self.assertTrue(engine.due(total_candidates=0, now=82))
        maximum = engine.consume(total_candidates=0, now=82)
        self.assertEqual(maximum.reasons, ("maximum_review_interval",))


class SnapshotBuilderTests(unittest.TestCase):
    def test_bounded_snapshot_has_exact_context_and_hashed_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            manager = LaneManager(root)
            try:
                store.create_campaign(
                    campaign_id="campaign-1",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="time_limit",
                    deadline_at="2026-07-25T00:00:00Z",
                )
                builder = SnapshotBuilder(
                    store=store,
                    manager=manager,
                    campaign_id="campaign-1",
                    campaign_dir=root,
                )
                snapshot, context = builder.publish()
                self.assertEqual(snapshot["schema_version"], "3.0")
                self.assertEqual(
                    snapshot["target"]["success_authority"],
                    "M4_independent_verifier",
                )
                self.assertEqual(context.snapshot_id, snapshot["snapshot_id"])
                self.assertEqual(context.lane_versions, {})
                row = store.connection.execute(
                    "SELECT * FROM director_snapshots"
                ).fetchone()
                artifact = root / row["artifact_ref"]
                payload = artifact.read_bytes()
                self.assertEqual(row["payload_bytes"], len(payload))
                import hashlib

                self.assertEqual(
                    row["artifact_sha256"],
                    hashlib.sha256(payload).hexdigest(),
                )
                self.assertEqual(
                    json.loads(payload)["snapshot_id"],
                    snapshot["snapshot_id"],
                )
            finally:
                manager.shutdown()
                store.close()
