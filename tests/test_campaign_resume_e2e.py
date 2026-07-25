from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from sglab.research.campaign import ResearchCampaignRunner
from sglab.research.store import ResearchStore


class CampaignResumeEndToEndTests(unittest.TestCase):
    def test_two_attempts_continue_real_search_from_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            first = ResearchCampaignRunner(
                workspace=workspace,
                stop_mode="time_limit",
                duration_seconds=3,
                controller_mode="continuity_demo",
                controller_seed=41,
                maximum_director_turns=100,
                resume_resource_overrides={
                    "cpu_workers": 2,
                    "maximum_active_lanes": 2,
                },
                code_commit="offline-attempt-one",
            ).run()
            campaign_id = str(first["campaign_id"])
            with ResearchStore(workspace / "results.sqlite3") as store:
                before = store.cumulative_campaign_counters(campaign_id)
                first_attempt = store.latest_execution_attempt(campaign_id)
                self.assertEqual(first_attempt["attempt_index"], 1)
                self.assertEqual(
                    first_attempt["terminal_status"],
                    "completed_deadline_reached",
                )
                checkpoints = store.checkpoint_references(campaign_id)
                self.assertTrue(checkpoints)
                self.assertGreater(before["evaluations"], 0)
                terminal_memory = store.latest_memory_snapshot(campaign_id)
                self.assertIsNotNone(terminal_memory)
                hypotheses_before = [
                    tuple(row)
                    for row in store.connection.execute(
                        """
                        SELECT hypothesis_id, statement, confidence, status
                        FROM research_hypotheses_v2 WHERE campaign_id=?
                        ORDER BY created_at, rowid
                        """,
                        (campaign_id,),
                    )
                ]
                self.assertTrue(hypotheses_before)
                action_ids = {
                    str(row[0])
                    for row in store.connection.execute(
                        """
                        SELECT action_id FROM director_actions
                        WHERE campaign_id=?
                        """,
                        (campaign_id,),
                    )
                }
            second = ResearchCampaignRunner(
                workspace=workspace,
                stop_mode="time_limit",
                duration_seconds=3,
                campaign_id=campaign_id,
                controller_mode="continuity_demo",
                controller_seed=41,
                maximum_director_turns=100,
                resume_resource_overrides={
                    "cpu_workers": 16,
                    "maximum_active_lanes": 8,
                },
                code_commit="offline-attempt-two",
            ).run()
            self.assertEqual(second["campaign_id"], campaign_id)
            with ResearchStore(workspace / "results.sqlite3") as store:
                after = store.cumulative_campaign_counters(campaign_id)
                attempts = store.execution_attempts(campaign_id)
                self.assertEqual(len(attempts), 2)
                self.assertNotEqual(
                    attempts[0]["attempt_id"], attempts[1]["attempt_id"]
                )
                self.assertEqual(
                    json.loads(attempts[0]["effective_resource_json"])[
                        "cpu_workers"
                    ],
                    2,
                )
                self.assertEqual(
                    json.loads(attempts[1]["effective_resource_json"])[
                        "cpu_workers"
                    ],
                    16,
                )
                starting = attempts[1]["starting_checkpoint_refs_json"]
                self.assertNotEqual(starting, "[]")
                self.assertGreater(after["evaluations"], before["evaluations"])
                self.assertEqual(
                    hypotheses_before,
                    [
                        tuple(row)
                        for row in store.connection.execute(
                            """
                            SELECT hypothesis_id, statement, confidence, status
                            FROM research_hypotheses_v2 WHERE campaign_id=?
                            ORDER BY created_at, rowid
                            """,
                            (campaign_id,),
                        )
                    ],
                )
                later_ids = {
                    str(row[0])
                    for row in store.connection.execute(
                        """
                        SELECT action_id FROM director_actions
                        WHERE campaign_id=?
                        """,
                        (campaign_id,),
                    )
                }
                self.assertTrue(action_ids <= later_ids)
                self.assertEqual(
                    len(later_ids),
                    store.connection.execute(
                        """
                        SELECT count(DISTINCT idempotency_key)
                        FROM director_actions WHERE campaign_id=?
                        """,
                        (campaign_id,),
                    ).fetchone()[0],
                )
                latest_memory = store.latest_memory_snapshot(campaign_id)
                self.assertIsNotNone(latest_memory)
                self.assertLessEqual(latest_memory["byte_size"], 32_768)
                memory_projection = json.loads(
                    latest_memory["canonical_json"]
                )
                self.assertEqual(
                    memory_projection["continuity"][
                        "current_executable_candidate_ids"
                    ],
                    sorted(
                        memory_projection["continuity"][
                            "current_executable_candidate_ids"
                        ]
                    ),
                )
                self.assertTrue(
                    memory_projection["continuity"][
                        "exact_verifier_outcomes"
                    ]
                )
                self.assertGreater(
                    store.connection.execute(
                        """
                        SELECT count(*) FROM lane_metric_windows
                        WHERE campaign_id=?
                        """,
                        (campaign_id,),
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    attempts[1]["starting_memory_snapshot_id"],
                    terminal_memory["memory_snapshot_id"],
                )
                self.assertEqual(
                    store.connection.execute(
                        "PRAGMA integrity_check"
                    ).fetchone()[0],
                    "ok",
                )
                self.assertEqual(
                    store.connection.execute(
                        "PRAGMA foreign_key_check"
                    ).fetchall(),
                    [],
                )
                turn_links = store.connection.execute(
                    """
                    SELECT execution_attempt_id, memory_snapshot_id
                    FROM app_server_turns WHERE campaign_id=?
                    ORDER BY started_at, rowid
                    """,
                    (campaign_id,),
                ).fetchall()
                self.assertTrue(turn_links)
                self.assertTrue(
                    all(
                        row["execution_attempt_id"]
                        and row["memory_snapshot_id"]
                        for row in turn_links
                    )
                )


if __name__ == "__main__":
    unittest.main()
