from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sglab.research.lanes import LaneManager
from sglab.research.protocol import MAX_SNAPSHOT_BYTES, canonical_json
from sglab.research.snapshot import SnapshotBuilder, _compact_observed_effect
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
    def test_missing_checkpoint_is_history_not_an_executable_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            manager = LaneManager(root)
            try:
                store.create_campaign(
                    campaign_id="campaign-missing-checkpoint",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="until_success",
                    deadline_at=None,
                )
                store.create_lane(
                    lane_id="lane-missing-checkpoint",
                    campaign_id="campaign-missing-checkpoint",
                    target="erdos_gyarfas",
                    parent_lane_id=None,
                    parent_checkpoint_ref=None,
                    action_id="bootstrap-missing-checkpoint",
                    algorithm="simulated_annealing",
                    graph_family="connected_cubic",
                    parameters={"order": 8},
                    seed_lineage=[7],
                    resource_share=1.0,
                    lease_expires_at=None,
                )
                checkpoint_ref = (
                    "lane-checkpoints/checkpoint-missing.json"
                )
                with store.connection:
                    store.connection.execute(
                        """
                        UPDATE research_lanes
                        SET state='paused', checkpoint_ref=?
                        WHERE lane_id='lane-missing-checkpoint'
                        """,
                        (checkpoint_ref,),
                    )
                snapshot, context = SnapshotBuilder(
                    store=store,
                    manager=manager,
                    campaign_id="campaign-missing-checkpoint",
                    campaign_dir=root,
                ).publish()

                lane = next(
                    item
                    for item in snapshot["lanes"]
                    if item["lane_id"] == "lane-missing-checkpoint"
                )
                self.assertIsNone(lane["checkpoint_id"])
                self.assertNotIn(
                    "checkpoint-missing",
                    context.executable_target_ids,
                )
                ledger = next(
                    item
                    for item in snapshot["continuity"][
                        "lane_and_checkpoint_ledger"
                    ]
                    if item["lane_id"] == "lane-missing-checkpoint"
                )
                self.assertEqual(
                    ledger["checkpoint_id"], "checkpoint-missing"
                )
            finally:
                manager.shutdown()
                store.close()

    def test_snapshot_ancestry_is_bounded_without_changing_full_outcome(
        self,
    ) -> None:
        records = [
            {"evaluation": index, "candidate_id": f"candidate-{index}"}
            for index in range(200)
        ]
        source = {
            "outcome_artifact_ref": "experiment/outcome.json",
            "outcome_artifact_sha256": "a" * 64,
            "mutation_ancestry": {
                "global_record_improvements": records,
                "final_best_ancestry": records,
                "limit_per_retained_candidate": 64,
                "rejected_non_record_candidates_stored": 0,
            },
        }
        compact = _compact_observed_effect(source)
        ancestry = compact["mutation_ancestry"]
        self.assertEqual(ancestry["global_record_count"], 200)
        self.assertEqual(len(ancestry["global_record_samples"]), 16)
        self.assertEqual(len(ancestry["final_best_ancestry"]), 64)
        self.assertTrue(ancestry["global_record_samples_truncated"])
        self.assertEqual(
            len(
                source["mutation_ancestry"][
                    "global_record_improvements"
                ]
            ),
            200,
        )
        historical = _compact_observed_effect(
            source, full_ancestry=False
        )["mutation_ancestry"]
        self.assertEqual(len(historical["global_record_samples"]), 4)
        self.assertEqual(len(historical["final_best_ancestry"]), 8)
        self.assertEqual(
            historical["ancestry_detail"], "historical_summary"
        )

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

    def test_scientific_memory_compacts_before_total_director_limit(self) -> None:
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
                oversized_questions = [
                    f"question-{index}-" + ("x" * 900)
                    for index in range(40)
                ]
                builder._continuity = lambda campaign: {
                    "hypothesis_ledger": [],
                    "latest_valid_assessment": None,
                    "exact_verifier_outcomes": [
                        {
                            "candidate_id": "candidate-exact",
                            "state": "completed",
                            "certification_status": "INVALID_CANDIDATE",
                            "certification_artifact_ref": (
                                "verifications/exact/manifest.json"
                            ),
                        }
                    ],
                    "candidate_ledger": [],
                    "current_executable_candidate_ids": [],
                    "current_executable_checkpoint_ids": [],
                    "lane_and_checkpoint_ledger": [],
                    "explored_regions": [],
                    "unresolved_scientific_questions": oversized_questions,
                    "validation_feedback": [],
                    "infrastructure_fault": None,
                    "execution_attempt": {
                        "attempt_id": None,
                        "effective_resources": {},
                    },
                }

                snapshot, _ = builder.publish()

                projection = snapshot["scientific_memory_projection"]
                self.assertLessEqual(
                    snapshot["scientific_memory"]["byte_size"],
                    32 * 1024,
                )
                self.assertLess(
                    len(
                        projection["continuity"][
                            "unresolved_scientific_questions"
                        ]
                    ),
                    len(oversized_questions),
                )
                self.assertEqual(
                    projection["continuity"]["exact_verifier_outcomes"][0][
                        "candidate_id"
                    ],
                    "candidate-exact",
                )
            finally:
                manager.shutdown()
                store.close()

    def test_stored_lane_metrics_are_summarized_before_resume_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            manager = LaneManager(root)
            ancestry = [
                {
                    "evaluation": index,
                    "candidate_id": f"candidate-{index:04d}",
                    "graph_sha256": f"{index:064x}",
                }
                for index in range(800)
            ]
            try:
                store.create_campaign(
                    campaign_id="campaign-1",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="time_limit",
                    deadline_at="2026-07-25T00:00:00Z",
                )
                for index in range(6):
                    lane_id = f"lane-{index}"
                    store.create_lane(
                        lane_id=lane_id,
                        campaign_id="campaign-1",
                        target="erdos_gyarfas",
                        parent_lane_id=None,
                        parent_checkpoint_ref=None,
                        action_id=f"bootstrap-{index}",
                        algorithm="simulated_annealing",
                        graph_family="connected_cubic",
                        parameters={"order": 64},
                        seed_lineage=[index],
                        resource_share=1 / 6,
                        lease_expires_at=None,
                    )
                    store.record_lane_metric_window(
                        metric_window_id=f"window-{index}",
                        lane_id=lane_id,
                        campaign_id="campaign-1",
                        lane_version=0,
                        start_high_water=0,
                        end_high_water=1000 + index,
                        started_at="2026-07-24T00:00:00Z",
                        ended_at="2026-07-24T00:01:00Z",
                        metrics={
                            "best_scalar": 1.0,
                            "best_score": [0, 1, 2],
                            "candidates_per_second": 20.0,
                            "duplicate_rate": 0.01,
                            "diversity": 0.99,
                            "operator_yield": 0.02,
                            "end_high_water": 1000 + index,
                            "mutation_ancestry": {
                                "global_record_improvements": ancestry,
                                "final_best_ancestry": ancestry,
                            },
                        },
                    )
                snapshot, _ = SnapshotBuilder(
                    store=store,
                    manager=manager,
                    campaign_id="campaign-1",
                    campaign_dir=root,
                ).publish(memory_trigger="resume")
                self.assertLessEqual(
                    len(canonical_json(snapshot, max_bytes=MAX_SNAPSHOT_BYTES)),
                    MAX_SNAPSHOT_BYTES,
                )
                self.assertTrue(
                    all(
                        "mutation_ancestry" not in lane["metrics"]
                        for lane in snapshot["lanes"]
                    )
                )
                raw = json.loads(
                    store.connection.execute(
                        """
                        SELECT metrics_json FROM lane_metric_windows
                        WHERE metric_window_id='window-0'
                        """
                    ).fetchone()[0]
                )
                self.assertEqual(
                    len(
                        raw["mutation_ancestry"][
                            "global_record_improvements"
                        ]
                    ),
                    800,
                )
            finally:
                manager.shutdown()
                store.close()
