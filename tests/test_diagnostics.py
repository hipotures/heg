from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from sglab.model import BitGraph
from sglab.research.candidates import CandidateArchive
from sglab.research.diagnostics import ScientificActionDispatcher
from sglab.research.store import ResearchStore


class ScientificActionDispatcherTests(unittest.TestCase):
    def test_reviewed_diagnostic_and_review_contract_are_durable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            try:
                store.create_campaign(
                    campaign_id="campaign-1",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="until_success",
                    deadline_at=None,
                )
                store.create_lane(
                    lane_id="lane-1",
                    campaign_id="campaign-1",
                    target="erdos_gyarfas",
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
                graph = BitGraph.from_edges(
                    4,
                    (
                        (u, v)
                        for u in range(4)
                        for v in range(u + 1, 4)
                    ),
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
                        "score": {"ordering_key": [0, 1, 4, 0, 6]},
                    }
                )
                self._seed_actions(store, candidate_id)
                dispatcher = ScientificActionDispatcher(
                    store=store,
                    campaign_id="campaign-1",
                    campaign_dir=root,
                )
                self.assertEqual(
                    set(dispatcher.dispatch_pending()),
                    {"diagnose-1", "review-1"},
                )
                contracts = dispatcher.drain_review_contracts()
                self.assertEqual(len(contracts), 1)
                self.assertEqual(contracts[0]["max_wall_seconds"], 120)
                row = store.connection.execute(
                    """
                    SELECT observed_effect_json FROM director_action_outcomes
                    WHERE action_id='diagnose-1'
                    """
                ).fetchone()
                observed = json.loads(row[0])
                path = root / observed["artifact_ref"]
                self.assertTrue(path.is_file())
                self.assertEqual(
                    observed["artifact_sha256"],
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
                self.assertEqual(
                    observed["summary"]["graphs"][0]["minimum_degree"], 3
                )
            finally:
                store.close()

    def _seed_actions(
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
        common = {
            "decision_batch_id": "batch-1",
            "campaign_id": "campaign-1",
            "priority": 50,
            "hypothesis_ids_json": "[]",
            "evidence_ids_json": "[]",
            "rationale": "test",
            "expected_effect": "produce deterministic evidence",
            "evaluation_window_json": "{}",
            "fallback_json": "{}",
            "lease_expires_at": "2026-07-25T00:00:00Z",
            "validation_status": "accepted",
            "created_at": "2026-07-24T00:00:00Z",
        }
        rows = [
            (
                "diagnose-1",
                "request_diagnostic",
                json.dumps(
                    {
                        "diagnostic_type": "graph_invariants",
                        "subject_ids": [candidate_id],
                    }
                ),
                "diagnose:1",
            ),
            (
                "review-1",
                "set_review_trigger",
                json.dumps(
                    {
                        "review_trigger": {
                            "min_wall_seconds": 30,
                            "max_wall_seconds": 120,
                            "candidate_delta": 1000,
                            "events": ["stagnation", "lane_failure"],
                        }
                    }
                ),
                "review:1",
            ),
        ]
        for action_id, kind, parameters, key in rows:
            store.connection.execute(
                """
                INSERT INTO director_actions
                (action_id, decision_batch_id, campaign_id, action_type,
                 priority, hypothesis_ids_json, evidence_ids_json,
                 parameters_json, rationale, expected_effect,
                 evaluation_window_json, fallback_json, idempotency_key,
                 lease_expires_at, validation_status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    common["decision_batch_id"],
                    common["campaign_id"],
                    kind,
                    common["priority"],
                    common["hypothesis_ids_json"],
                    common["evidence_ids_json"],
                    parameters,
                    common["rationale"],
                    common["expected_effect"],
                    common["evaluation_window_json"],
                    common["fallback_json"],
                    key,
                    common["lease_expires_at"],
                    common["validation_status"],
                    common["created_at"],
                ),
            )
        store.connection.commit()
