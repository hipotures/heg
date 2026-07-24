from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from sglab.research.effects import EffectEvaluator
from sglab.research.store import ResearchStore


class EffectEvaluatorTests(unittest.TestCase):
    def test_patch_effect_is_attached_to_durable_outcome(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "effects.sqlite3")
            try:
                self._seed(store)
                result = EffectEvaluator(store, "campaign-1").evaluate_ready()
                self.assertEqual(len(result), 1)
                self.assertTrue(result[0]["expectation_met"])
                row = store.connection.execute(
                    """
                    SELECT * FROM director_action_outcomes
                    WHERE action_id='action-patch'
                    """
                ).fetchone()
                self.assertIsNotNone(row["evaluated_at"])
                self.assertEqual(row["expectation_met"], 1)
                effect = json.loads(row["observed_effect_json"])
                self.assertLess(effect["score_slope_change"], 0)
                self.assertEqual(effect["pre_window_count"], 4)
                self.assertEqual(effect["post_window_count"], 4)
                self.assertEqual(
                    EffectEvaluator(store, "campaign-1").evaluate_ready(), []
                )
            finally:
                store.close()

    def _seed(self, store: ResearchStore) -> None:
        sql = """
        INSERT INTO research_campaigns
        (campaign_id, created_at, updated_at, target,
         target_definition_sha256, state, state_version, stop_mode)
        VALUES ('campaign-1', '2026-07-24T00:00:00Z',
                '2026-07-24T00:00:00Z', 'erdos_gyarfas',
                'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                'running', 0,
                'until_success');
        INSERT INTO director_snapshots
        VALUES ('snapshot-1', 'campaign-1', 0, '{}', 'snapshot.json',
                'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb', 1,
                '2026-07-24T00:00:00Z');
        INSERT INTO director_triggers
        VALUES ('trigger-1', 'campaign-1', 0, '[]',
                '2026-07-24T00:00:00Z', '2026-07-24T00:00:00Z',
                'snapshot-1', 'decided');
        INSERT INTO app_server_sessions
        (session_record_id, campaign_id, thread_id, codex_version,
         codex_executable_sha256, protocol_schema_sha256, state, started_at)
        VALUES ('session-1', 'campaign-1', 'thread-1', 'test',
                'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
                'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
                'active',
                '2026-07-24T00:00:00Z');
        INSERT INTO app_server_turns
        (turn_record_id, session_record_id, campaign_id, thread_id,
         snapshot_id, trigger_id, status, started_at, completed_at)
        VALUES ('turn-1', 'session-1', 'campaign-1', 'thread-1', 'snapshot-1',
                'trigger-1', 'completed_valid', '2026-07-24T00:00:00Z',
                '2026-07-24T00:00:00Z');
        INSERT INTO director_action_batches
        (decision_batch_id, campaign_id, snapshot_id, trigger_id,
         turn_record_id, campaign_assessment, next_review_json,
         validation_status, created_at)
        VALUES ('batch-1', 'campaign-1', 'snapshot-1', 'trigger-1', 'turn-1',
                'test', '{}', 'accepted', '2026-07-24T00:00:00Z');
        INSERT INTO director_actions
        (action_id, decision_batch_id, campaign_id, action_type, priority,
         target_lane_id, expected_lane_version, hypothesis_ids_json,
         evidence_ids_json, parameters_json, rationale, expected_effect,
         evaluation_window_json, fallback_json, idempotency_key,
         lease_expires_at, validation_status, created_at)
        VALUES ('action-patch', 'batch-1', 'campaign-1', 'patch_lane', 50,
                'lane-1', 0, '[]', '[]', '{}', 'test',
                'Improve score slope', '{"max_wall_seconds":10,
                "max_candidate_delta":100}', '{}', 'idempotency:effect',
                '2026-07-25T00:00:00Z', 'accepted',
                '2026-07-24T00:00:00Z');
        INSERT INTO research_lanes
        (lane_id, campaign_id, target, state, lane_version, algorithm,
         graph_family, current_parameters_json, seed_lineage_json,
         telemetry_high_water, resource_share, process_generation,
         created_at, updated_at)
        VALUES ('lane-1', 'campaign-1', 'erdos_gyarfas', 'running', 1,
                'simulated_annealing', 'connected_cubic', '{}', '[1]', 800,
                1.0, 0, '2026-07-24T00:00:00Z',
                '2026-07-24T00:00:00Z');
        INSERT INTO director_action_outcomes
        (action_outcome_id, action_id, campaign_id, application_status,
         resulting_lane_id, resulting_lane_version, applied_at)
        VALUES ('outcome-1', 'action-patch', 'campaign-1', 'applied',
                'lane-1', 1, '2026-07-24T00:00:00Z');
        """
        store.connection.executescript(sql)
        for lane_version, scores in ((0, [10, 10, 10, 10]), (1, [9, 8, 7, 6])):
            for index, score in enumerate(scores, start=1):
                start = (lane_version * 400) + (index - 1) * 100
                end = start + 100
                metrics = {
                    "end_high_water": end,
                    "best_scalar": score,
                    "candidates_per_second": 1000,
                    "duplicate_rate": 0.2,
                    "diversity": 0.8,
                    "operator_yield": 0.01,
                }
                store.connection.execute(
                    """
                    INSERT INTO lane_metric_windows
                    VALUES (?, 'lane-1', 'campaign-1', ?, ?, ?,
                            '2026-07-24T00:00:00Z',
                            '2026-07-24T00:00:01Z', ?, NULL, NULL)
                    """,
                    (
                        f"window-{lane_version}-{index}",
                        lane_version,
                        start,
                        end,
                        json.dumps(metrics),
                    ),
                )
        store.connection.commit()
