from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from sglab.certification import default_cyclecheck
from sglab.model import BitGraph
from sglab.research.candidates import CandidateArchive
from sglab.research.lanes import LaneManager
from sglab.research.store import ResearchStore
from sglab.research.verification_broker import (
    M4VerificationBroker,
    _valid_manifest,
)


@unittest.skipUnless(default_cyclecheck().is_file(), "C++ helper has not been built")
class M4VerificationBrokerTests(unittest.TestCase):
    def test_retained_id_is_promoted_to_real_two_path_m4(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            manager = LaneManager(root)
            broker = M4VerificationBroker(
                store=store,
                manager=manager,
                campaign_id="campaign-1",
                campaign_dir=root,
                timeout_seconds=5,
            )
            try:
                self._seed_campaign(store)
                graph = BitGraph.from_edges(
                    4,
                    (
                        (u, v)
                        for u in range(4)
                        for v in range(u + 1, 4)
                    ),
                )
                archive = CandidateArchive(
                    store=store,
                    campaign_id="campaign-1",
                    campaign_dir=root,
                    maximum_candidates=4,
                )
                candidate_id = archive.observe_improvement(
                    {
                        "lane_id": "lane-1",
                        "lane_version": 0,
                        "checkpoint_id": "checkpoint-1",
                        "graph6": graph.to_graph6(),
                        "score": {
                            "valid": True,
                            "ordering_key": [0, 1, 4, 0, 6],
                        },
                    }
                )
                self._seed_promote_action(store, candidate_id)
                self.assertEqual(
                    broker.dispatch_pending_actions(), ["promote-k4"]
                )
                job_id = broker.start_ready()
                self.assertIsNotNone(job_id)
                deadline = time.monotonic() + 15
                event = None
                while time.monotonic() < deadline and event is None:
                    event = broker.poll()
                    time.sleep(0.01)
                self.assertIsNotNone(event)
                self.assertEqual(event["status"], "INVALID_CANDIDATE")
                self.assertFalse(event["terminal"])
                manifest = json.loads(
                    (
                        root
                        / "verifications"
                        / str(job_id)
                        / "manifest.json"
                    ).read_text(encoding="utf-8")
                )
                self.assertTrue(_valid_manifest(manifest))
                self.assertEqual(len(manifest["verifiers"]), 2)
                self.assertEqual(
                    store.campaign("campaign-1")["state"], "running"
                )
                candidate = store.campaign_candidate(candidate_id)
                self.assertEqual(candidate["state"], "rejected")
                self.assertEqual(
                    candidate["certification_status"], "INVALID_CANDIDATE"
                )
                self.assertEqual(
                    store.connection.execute(
                        "SELECT count(*) FROM campaign_terminal_events"
                    ).fetchone()[0],
                    0,
                )
            finally:
                broker.shutdown()
                manager.shutdown()
                store.close()

    def test_success_manifest_requires_both_complete_independent_paths(self) -> None:
        valid = {
            "status": "COUNTEREXAMPLE_VERIFIED",
            "verifiers": [
                {
                    "implementation": "python-reference-dfs",
                    "status": "VERIFIED",
                    "complete": True,
                },
                {
                    "implementation": "cpp17-bitset-dfs",
                    "status": "ABSENT",
                    "complete": True,
                },
            ],
        }
        self.assertTrue(_valid_manifest(valid))
        invalid = json.loads(json.dumps(valid))
        invalid["verifiers"][1]["complete"] = False
        self.assertFalse(_valid_manifest(invalid))
        invalid = json.loads(json.dumps(valid))
        invalid["verifiers"][1]["implementation"] = "python-reference-dfs"
        self.assertFalse(_valid_manifest(invalid))

    def test_control_target_success_is_latched_only_by_broker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            manager = LaneManager(root)
            broker = M4VerificationBroker(
                store=store,
                manager=manager,
                campaign_id="campaign-1",
                campaign_dir=root,
                timeout_seconds=5,
            )
            try:
                target = "m6_hidden_witness_control_v1"
                self._seed_campaign(store, target=target)
                graph = BitGraph.from_edges(
                    10,
                    {
                        (0, 1), (1, 2), (2, 3), (3, 4), (0, 4),
                        (5, 7), (7, 9), (6, 9), (6, 8), (5, 8),
                        (0, 5), (1, 6), (2, 7), (3, 8), (4, 9),
                    },
                )
                candidate_id = CandidateArchive(
                    store=store,
                    campaign_id="campaign-1",
                    campaign_dir=root,
                ).observe_improvement(
                    {
                        "lane_id": "lane-1",
                        "lane_version": 0,
                        "checkpoint_id": "checkpoint-1",
                        "graph6": graph.to_graph6(),
                        "score": {
                            "valid": True,
                            "ordering_key": [0, 0, 0, 0, 15],
                        },
                    }
                )
                self._seed_promote_action(store, candidate_id)
                broker.dispatch_pending_actions()
                broker.start_ready()
                deadline = time.monotonic() + 15
                event = None
                while time.monotonic() < deadline and event is None:
                    event = broker.poll()
                    time.sleep(0.01)
                self.assertIsNotNone(event)
                self.assertEqual(event["status"], "COUNTEREXAMPLE_VERIFIED")
                self.assertTrue(event["terminal"])
                self.assertEqual(
                    store.campaign("campaign-1")["state"],
                    "succeeded_certified_counterexample",
                )
                terminal = store.connection.execute(
                    "SELECT * FROM campaign_terminal_events"
                ).fetchall()
                self.assertEqual(len(terminal), 1)
                self.assertEqual(
                    terminal[0]["terminal_kind"],
                    "succeeded_certified_counterexample",
                )
            finally:
                broker.shutdown()
                manager.shutdown()
                store.close()

    def _seed_campaign(
        self,
        store: ResearchStore,
        *,
        target: str = "erdos_gyarfas",
    ) -> None:
        store.create_campaign(
            campaign_id="campaign-1",
            target=target,
            target_definition_sha256="a" * 64,
            stop_mode="until_success",
            deadline_at=None,
        )
        store.create_lane(
            lane_id="lane-1",
            campaign_id="campaign-1",
            target=target,
            parent_lane_id=None,
            parent_checkpoint_ref=None,
            action_id="bootstrap",
            algorithm="simulated_annealing",
            graph_family="connected_cubic",
            parameters={},
            seed_lineage=[1],
            resource_share=1,
            lease_expires_at=None,
        )
        store.mark_lane_running("lane-1")

    def _seed_promote_action(
        self, store: ResearchStore, candidate_id: str
    ) -> None:
        store.connection.executescript(
            f"""
            INSERT INTO director_snapshots
            VALUES ('snapshot-1', 'campaign-1', 0, '{{}}', 'snapshot.json',
                    '{"b" * 64}', 1, '2026-07-24T00:00:00Z');
            INSERT INTO director_triggers
            VALUES ('trigger-1', 'campaign-1', 0, '[]',
                    '2026-07-24T00:00:00Z', '2026-07-24T00:00:00Z',
                    'snapshot-1', 'decided');
            INSERT INTO app_server_sessions
            (session_record_id, campaign_id, thread_id, codex_version,
             codex_executable_sha256, protocol_schema_sha256, state,
             started_at)
            VALUES ('session-1', 'campaign-1', 'thread-1', 'test',
                    '{"c" * 64}', '{"d" * 64}', 'active',
                    '2026-07-24T00:00:00Z');
            INSERT INTO app_server_turns
            (turn_record_id, session_record_id, campaign_id, thread_id,
             snapshot_id, trigger_id, status, started_at, completed_at)
            VALUES ('turn-1', 'session-1', 'campaign-1', 'thread-1',
                    'snapshot-1', 'trigger-1', 'completed_valid',
                    '2026-07-24T00:00:00Z', '2026-07-24T00:00:00Z');
            INSERT INTO director_action_batches
            (decision_batch_id, campaign_id, snapshot_id, trigger_id,
             turn_record_id, campaign_assessment, next_review_json,
             validation_status, created_at)
            VALUES ('batch-1', 'campaign-1', 'snapshot-1', 'trigger-1',
                    'turn-1', 'test', '{{}}', 'accepted',
                    '2026-07-24T00:00:00Z');
            """
        )
        store.connection.execute(
            """
            INSERT INTO director_actions
            (action_id, decision_batch_id, campaign_id, action_type, priority,
             hypothesis_ids_json, evidence_ids_json, parameters_json,
             rationale, expected_effect, evaluation_window_json,
             fallback_json, idempotency_key, lease_expires_at,
             validation_status, created_at)
            VALUES ('promote-k4', 'batch-1', 'campaign-1',
                    'promote_candidate', 90, '[]', '[]', ?, 'test',
                    'Run exact verification', '{"max_wall_seconds":10,
                    "max_candidate_delta":100}', '{}', 'promote:k4',
                    '2099-01-01T00:00:00Z', 'accepted',
                    '2026-07-24T00:00:00Z')
            """,
            (json.dumps({"candidate_id": candidate_id}),),
        )
        store.connection.commit()
