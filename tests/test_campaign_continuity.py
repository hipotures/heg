from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
import hashlib
import json
import sqlite3
import tempfile
import unittest

from sglab.db import SCHEMA_VERSION, connect
from sglab.model import BitGraph
from sglab.research.continuity import (
    CampaignResources,
    ScientificMemoryCompactor,
    ScientificMemoryPolicy,
    ScientificStateOverflow,
)
from sglab.research.campaign import campaign_status
from sglab.research.providers import SyntheticControlProvider
from sglab.research.resume import build_resume_preview
from sglab.research.snapshot import _exact_verifier_continuity_fact
from sglab.research.store import ResearchStore
from sglab.research.validation import DecisionContext


class CampaignContinuityTests(unittest.TestCase):
    def test_synthetic_control_never_targets_advisory_only_candidate(self) -> None:
        context = DecisionContext(
            snapshot_id="snapshot-1",
            evidence_ids=frozenset({"candidate-historical"}),
            lane_versions={},
            lane_algorithms={},
            checkpoint_ids=frozenset(),
            candidate_ids=frozenset({"candidate-historical"}),
            executable_target_ids=frozenset(),
        )
        self.assertIsNone(
            SyntheticControlProvider._unsubmitted_candidate(
                {
                    "global_best": {
                        "candidate_id": "candidate-historical",
                    }
                },
                context,
            )
        )

    def test_schema_15_online_backup_migrates_to_16(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = connect(root / "source.sqlite3")
            source.execute(
                """
                ALTER TABLE campaign_candidates
                DROP COLUMN provenance_json
                """
            )
            source.execute(
                """
                ALTER TABLE campaign_candidate_snapshots
                DROP COLUMN provenance_json
                """
            )
            source.execute("PRAGMA user_version=15")
            source.commit()
            snapshot_path = root / "snapshot.sqlite3"
            snapshot = sqlite3.connect(snapshot_path)
            source.backup(snapshot)
            snapshot.close()
            source.close()
            migrated = connect(snapshot_path)
            self.assertEqual(SCHEMA_VERSION, 16)
            self.assertEqual(
                migrated.execute("PRAGMA user_version").fetchone()[0], 16
            )
            self.assertEqual(
                migrated.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )
            self.assertEqual(
                migrated.execute("PRAGMA foreign_key_check").fetchall(), []
            )
            for table in (
                "campaign_candidates",
                "campaign_candidate_snapshots",
            ):
                columns = {
                    row[1]
                    for row in migrated.execute(
                        f"PRAGMA table_info({table})"
                    )
                }
                self.assertIn("provenance_json", columns)
            migrated.close()

    def test_attempt_lifecycle_resources_and_cumulative_counters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "results.sqlite3")
            self._campaign(store, state="running")
            resources = CampaignResources.from_plan(
                {
                    "search_limits": {
                        "cpu_workers": 2,
                        "maximum_active_lanes": 2,
                    }
                }
            ).as_dict()
            store.create_execution_attempt(
                attempt_id="attempt-1",
                campaign_id="campaign-1",
                reason="initial_start",
                code_commit="commit-a",
                requested_resources=resources,
                effective_resources=resources,
                additional_wall_seconds=60,
                starting_memory_snapshot_id=None,
                starting_memory_sha256=None,
                starting_checkpoint_refs=[],
            )
            store.finish_execution_attempt(
                "attempt-1",
                terminal_status="completed_deadline_reached",
                terminal_reason="bounded deadline",
            )
            store.transition_campaign(
                "campaign-1",
                expected_version=0,
                state="completed_deadline_reached",
            )
            store.resume_campaign(
                "campaign-1",
                deadline_at=self._future(),
                repair_acknowledgement=None,
            )
            changed = CampaignResources.from_plan(
                {},
                overrides={
                    "cpu_workers": 16,
                    "maximum_active_lanes": 8,
                },
            ).as_dict()
            store.create_execution_attempt(
                attempt_id="attempt-2",
                campaign_id="campaign-1",
                reason="additional_budget",
                code_commit="commit-b",
                requested_resources=changed,
                effective_resources=changed,
                additional_wall_seconds=90,
                starting_memory_snapshot_id=None,
                starting_memory_sha256=None,
                starting_checkpoint_refs=[],
            )
            attempts = store.execution_attempts("campaign-1")
            self.assertEqual(
                [row["attempt_id"] for row in attempts],
                ["attempt-1", "attempt-2"],
            )
            self.assertEqual(attempts[0]["terminal_status"],
                             "completed_deadline_reached")
            self.assertEqual(
                json.loads(attempts[1]["effective_resource_json"])[
                    "cpu_workers"
                ],
                16,
            )
            self.assertEqual(store.campaign("campaign-1")["state"], "running")
            store.close()

    def test_supported_and_refused_resume_states(self) -> None:
        supported = {
            "paused_by_operator",
            "stopped_by_operator",
            "completed_deadline_reached",
            "budget_exhausted",
            "interrupted",
            "infrastructure_failure",
        }
        for state in supported:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                store = ResearchStore(Path(directory) / "results.sqlite3")
                self._campaign(store, state=state)
                store.resume_campaign(
                    "campaign-1",
                    deadline_at=self._future(),
                    repair_acknowledgement=None,
                )
                self.assertEqual(
                    store.campaign("campaign-1")["state"], "running"
                )
                store.close()
        for state in {"succeeded_certified_counterexample",
                      "scientifically_invalidated"}:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                store = ResearchStore(Path(directory) / "results.sqlite3")
                self._campaign(store, state=state)
                with self.assertRaisesRegex(RuntimeError, "not resumable"):
                    store.resume_campaign(
                        "campaign-1",
                        deadline_at=self._future(),
                        repair_acknowledgement=None,
                    )
                store.close()

    def test_dashboard_offers_resume_for_stale_running_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with ResearchStore(root / "results.sqlite3") as store:
                self._campaign(store, state="running")
            (root / "active-research-campaign.json").write_text(
                json.dumps(
                    {
                        "campaign_id": "campaign-1",
                        "pid": 999_999_999,
                    }
                ),
                encoding="utf-8",
            )
            status = campaign_status(root, "campaign-1")
            self.assertTrue(status["host_restart_resume"])
            self.assertTrue(status["resume_supported"])

    def test_fault_resume_requires_and_preserves_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "results.sqlite3")
            self._campaign(
                store,
                state="paused_fault",
                fault_kind="RuntimeError",
                fault_detail="historical fault",
            )
            resources = CampaignResources.from_plan({}).as_dict()
            store.create_execution_attempt(
                attempt_id="fault-attempt",
                campaign_id="campaign-1",
                reason="initial_start",
                code_commit="broken-commit",
                requested_resources=resources,
                effective_resources=resources,
                additional_wall_seconds=60,
                starting_memory_snapshot_id=None,
                starting_memory_sha256=None,
                starting_checkpoint_refs=[],
            )
            store.finish_execution_attempt(
                "fault-attempt",
                terminal_status="paused_fault",
                terminal_reason="historical fault",
            )
            with self.assertRaisesRegex(
                RuntimeError, "repair acknowledgement"
            ):
                store.resume_campaign(
                    "campaign-1",
                    deadline_at=self._future(),
                    repair_acknowledgement=None,
                )
            store.resume_campaign(
                "campaign-1",
                deadline_at=self._future(),
                repair_acknowledgement="fixed in commit-b",
            )
            campaign = store.campaign("campaign-1")
            self.assertEqual(campaign["state"], "running")
            self.assertIsNone(campaign["fault_kind"])
            self.assertIsNone(campaign["fault_detail"])
            store.create_execution_attempt(
                attempt_id="repair-attempt",
                campaign_id="campaign-1",
                reason="infrastructure_recovery",
                code_commit="fixed-commit",
                requested_resources=resources,
                effective_resources=resources,
                additional_wall_seconds=120,
                starting_memory_snapshot_id=None,
                starting_memory_sha256=None,
                starting_checkpoint_refs=[],
                repair_acknowledgement="fixed in commit-b",
            )
            attempts = store.execution_attempts("campaign-1")
            self.assertEqual(
                attempts[0]["terminal_reason"], "historical fault"
            )
            self.assertEqual(
                attempts[1]["repair_acknowledgement"],
                "fixed in commit-b",
            )
            self.assertNotEqual(
                attempts[0]["attempt_id"], attempts[1]["attempt_id"]
            )
            store.close()

    def test_candidate_pin_snapshot_and_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "results.sqlite3")
            self._campaign(store, state="running")
            self._lane(store)
            graph = BitGraph.from_edges(
                4,
                (
                    (0, 1),
                    (0, 2),
                    (0, 3),
                    (1, 2),
                    (1, 3),
                    (2, 3),
                ),
            ).to_graph6()
            digest = hashlib.sha256(graph.encode("ascii")).hexdigest()
            store.retain_campaign_candidate(
                candidate_id="candidate-1",
                campaign_id="campaign-1",
                lane_id="lane-1",
                lane_version=0,
                checkpoint_ref="checkpoint-1",
                graph6=graph,
                graph_sha256=digest,
                score={"ordering_key": [0, 0, 0, 0, 0]},
                artifact_ref="candidates/candidate-1.graph6",
                artifact_sha256="b" * 64,
                provenance={
                    "schema_version": 2,
                    "provenance_kind": "independent_sample",
                    "graph_sha256": digest,
                },
            )
            self._accepted_candidate_action(store, "candidate-1")
            self.assertTrue(
                store.queue_verification_action(
                    action_id="verify-1",
                    candidate_ids=["candidate-1"],
                    priority=80,
                    job_ids=["job-1"],
                )
            )
            pin = store.connection.execute(
                "SELECT * FROM campaign_candidate_pins"
            ).fetchone()
            self.assertEqual(pin["state"], "active")
            immutable = store.candidate_snapshot_for_job("job-1")
            self.assertEqual(immutable["graph6"], graph)
            self.assertEqual(
                immutable["score_semantics"],
                "heuristic_ordering_key_v1_not_certification",
            )
            self.assertEqual(
                json.loads(immutable["provenance_json"])[
                    "provenance_kind"
                ],
                "independent_sample",
            )
            with self.assertRaises(sqlite3.IntegrityError):
                store.connection.execute(
                    """
                    DELETE FROM campaign_candidates
                    WHERE candidate_id='candidate-1'
                    """
                )
            store.connection.rollback()
            store.prune_campaign_candidates("campaign-1", 1)
            self.assertIsNotNone(
                store.connection.execute(
                    """
                    SELECT 1 FROM campaign_candidates
                    WHERE candidate_id='candidate-1'
                    """
                ).fetchone()
            )
            store.mark_verification_started("job-1")
            store.complete_verification_job(
                job_id="job-1",
                status="TOOL_FAILURE",
                artifact_ref="verifications/job-1",
            )
            pin = store.connection.execute(
                "SELECT * FROM campaign_candidate_pins"
            ).fetchone()
            self.assertEqual(pin["state"], "released")
            self.assertIsNone(pin["candidate_id"])
            store.close()

    def test_historical_missing_candidate_becomes_stale_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "results.sqlite3")
            self._campaign(store, state="paused_fault")
            self._lane(store)
            self._accepted_candidate_action(
                store, "candidate-missing", action_id="historical-action"
            )
            terminalized = store.terminalize_stale_candidate_actions(
                "campaign-1"
            )
            self.assertEqual(
                terminalized[0]["action_id"], "historical-action"
            )
            outcome = store.connection.execute(
                """
                SELECT * FROM director_action_outcomes
                WHERE action_id='historical-action'
                """
            ).fetchone()
            self.assertEqual(outcome["application_status"], "stale_target")
            self.assertEqual(
                outcome["failure_kind"], "stale_candidate_target"
            )
            self.assertEqual(
                store.pending_candidate_actions("campaign-1"), []
            )
            store.close()

    def test_deterministic_compaction_is_bounded_and_preserves_facts(self) -> None:
        policy = ScientificMemoryPolicy(
            soft_limit_bytes=4096,
            hard_limit_bytes=8192,
            snapshot_interval_cycles=2,
        )
        compactor = ScientificMemoryCompactor(policy)
        state = self._memory_state()
        state["previous_outcomes"] = [
            {"index": index, "detail": "x" * 900}
            for index in range(20)
        ]
        state["exact_verifier"] = {
            "status": "INVALID_CANDIDATE",
            "candidate_id": "candidate-exact",
        }
        state["allowed_action_space"] = {
            "actions": ["schedule_verification"],
            "reference_objects": [
                {
                    "id": "candidate-current",
                    "executable_allowed": True,
                }
            ],
        }
        first = compactor.project(state)
        second = compactor.project(state)
        payload = compactor.encode(first)
        self.assertEqual(first, second)
        self.assertLessEqual(len(payload), 8192)
        self.assertEqual(
            first["exact_verifier"]["candidate_id"], "candidate-exact"
        )
        self.assertEqual(
            first["allowed_action_space"]["reference_objects"][0]["id"],
            "candidate-current",
        )
        impossible = self._memory_state()
        impossible["exact_verifier"] = {"certificate": "z" * 20_000}
        with self.assertRaises(ScientificStateOverflow):
            compactor.project(impossible)

    def test_continuity_merge_does_not_regrow_bounded_ledgers(self) -> None:
        compactor = ScientificMemoryCompactor(ScientificMemoryPolicy())
        current = self._memory_state()
        previous = self._memory_state()
        current["continuity"] = {
            "exact_verifier_outcomes": [
                {
                    "candidate_id": f"candidate-{index:02d}",
                    "state": "completed",
                    "certification_status": "INVALID_CANDIDATE",
                }
                for index in range(10, 42)
            ],
        }
        previous["continuity"] = {
            "exact_verifier_outcomes": [
                {
                    "candidate_id": f"candidate-{index:02d}",
                    "state": "completed",
                    "certification_status": "INVALID_CANDIDATE",
                }
                for index in range(36)
            ],
        }

        projected = compactor.project(current, previous=previous)
        outcomes = projected["continuity"]["exact_verifier_outcomes"]

        self.assertEqual(len(outcomes), 32)
        self.assertEqual(
            [item["candidate_id"] for item in outcomes],
            [f"candidate-{index:02d}" for index in range(10, 42)],
        )
        self.assertTrue(
            all(
                item["certification_status"] == "INVALID_CANDIDATE"
                for item in outcomes
            )
        )

    def test_exact_verifier_continuity_fact_omits_durable_artifact_path(
        self,
    ) -> None:
        completed = _exact_verifier_continuity_fact(
            {
                "candidate_id": "candidate-1",
                "state": "completed",
                "certification_status": "INVALID_CANDIDATE",
                "certification_artifact_ref": (
                    "verifications/job-1/manifest.json"
                ),
            }
        )
        unknown = _exact_verifier_continuity_fact(
            {
                "candidate_id": "candidate-2",
                "state": "unknown",
                "certification_status": None,
                "certification_artifact_ref": None,
            }
        )

        self.assertEqual(
            completed,
            {
                "candidate_id": "candidate-1",
                "certification_status": "INVALID_CANDIDATE",
            },
        )
        self.assertEqual(
            unknown,
            {
                "candidate_id": "candidate-2",
                "certification_status": None,
                "state": "unknown",
            },
        )

    def test_real_shape_resume_preview_has_no_side_effects(self) -> None:
        root = Path("workspace/first-real-graph-campaign-01")
        if not root.is_dir():
            self.skipTest("real campaign compatibility workspace unavailable")
        database = root / "results.sqlite3"
        before = database.stat()
        with sqlite3.connect(
            f"file:{database.resolve()}?mode=ro",
            uri=True,
        ) as connection:
            campaign_state = str(
                connection.execute(
                    """
                    SELECT state FROM research_campaigns
                    WHERE campaign_id=?
                    """,
                    ("campaign-b68ec445388e49b2be0b6fabf8ff6600",),
                ).fetchone()[0]
            )
            if campaign_state == "running":
                self.skipTest(
                    "real campaign is active; Resume preview is not applicable"
                )
            expected_attempt_index = int(
                connection.execute(
                    """
                    SELECT coalesce(max(attempt_index), 0) + 1
                    FROM campaign_execution_attempts
                    WHERE campaign_id=?
                    """,
                    ("campaign-b68ec445388e49b2be0b6fabf8ff6600",),
                ).fetchone()[0]
            )
        preview = build_resume_preview(
            root,
            "campaign-b68ec445388e49b2be0b6fabf8ff6600",
            additional_wall_seconds=7200,
            resource_overrides={
                "cpu_workers": 16,
                "maximum_active_lanes": 8,
            },
            repair_acknowledgement="candidate lifetime repair",
            code_commit="offline-test",
        )
        after = database.stat()
        self.assertEqual(
            preview["proposed_attempt_index"],
            expected_attempt_index,
        )
        self.assertEqual(
            preview["reusable_checkpoint_count"],
            sum(
                bool(checkpoint["valid"])
                for checkpoint in preview["checkpoints"]
            ),
        )
        self.assertGreater(preview["reusable_checkpoint_count"], 0)
        self.assertEqual(
            preview["historical_stale_actions_excluded"][0]["action_id"],
            "verify-retained-candidate-01",
        )
        self.assertEqual(
            preview["side_effects"],
            {
                "database_writes": 0,
                "model_inferences": 0,
                "auth_accesses": 0,
                "search_batches": 0,
            },
        )
        self.assertEqual(
            (before.st_size, before.st_mtime_ns),
            (after.st_size, after.st_mtime_ns),
        )

    @staticmethod
    def _future() -> str:
        return (
            datetime.now(UTC) + timedelta(minutes=5)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _campaign(
        store: ResearchStore,
        *,
        state: str,
        fault_kind: str | None = None,
        fault_detail: str | None = None,
    ) -> None:
        store.create_campaign(
            campaign_id="campaign-1",
            target="erdos_gyarfas",
            target_definition_sha256="a" * 64,
            stop_mode="time_limit",
            deadline_at=CampaignContinuityTests._future(),
        )
        store.connection.execute(
            """
            UPDATE research_campaigns
            SET state=?, fault_kind=?, fault_detail=?
            WHERE campaign_id='campaign-1'
            """,
            (state, fault_kind, fault_detail),
        )
        store.connection.commit()

    @staticmethod
    def _lane(store: ResearchStore) -> None:
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
        store.mark_lane_running("lane-1")

    @staticmethod
    def _accepted_candidate_action(
        store: ResearchStore,
        candidate_id: str,
        *,
        action_id: str = "verify-1",
    ) -> None:
        store.connection.executescript(
            """
            INSERT INTO director_snapshots
            VALUES ('snapshot-1', 'campaign-1', 0, '{}', 'snapshot.json',
                    'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                    1, '2026-07-24T00:00:00Z');
            INSERT INTO director_triggers
            VALUES ('trigger-1', 'campaign-1', 0, '[]',
                    '2026-07-24T00:00:00Z', '2026-07-24T00:00:00Z',
                    'snapshot-1', 'decided');
            INSERT INTO app_server_sessions
            (session_record_id, campaign_id, thread_id, codex_version,
             codex_executable_sha256, protocol_schema_sha256, state,
             started_at)
            VALUES ('session-1', 'campaign-1', 'thread-1', 'test',
                    'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',
                    'dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd',
                    'closed', '2026-07-24T00:00:00Z');
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
                    'turn-1', 'test', '{}', 'accepted',
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
            VALUES (?, 'batch-1', 'campaign-1', 'schedule_verification', 80,
                    '[]', '[]', ?, 'test', 'exact check', '{}', '{}', ?,
                    '2099-01-01T00:00:00Z', 'accepted',
                    '2026-07-24T00:00:00Z')
            """,
            (
                action_id,
                json.dumps(
                    {
                        "candidate_ids": [candidate_id],
                        "verification_priority": 80,
                    }
                ),
                f"idempotency:{action_id}",
            ),
        )
        store.connection.commit()

    @staticmethod
    def _memory_state() -> dict:
        return {
            "schema_version": "2.0",
            "source_snapshot_id": "snapshot-1",
            "target": {},
            "campaign_budget": {},
            "allowed_action_space": {},
            "best_ever_result": None,
            "latest_batch_outcome": None,
            "previous_outcomes": [],
            "plateau": None,
            "operator_aggregates": {},
            "stage_timing_percentages": {},
            "exact_verifier": None,
            "parameter_effects": {},
            "previous_hypothesis": None,
            "ancestry": {
                "global_record_summaries": [],
                "final_best_accepted_ancestors": [],
            },
            "artifact_references": [],
        }


if __name__ == "__main__":
    unittest.main()
