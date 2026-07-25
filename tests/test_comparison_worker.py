from __future__ import annotations

from hashlib import sha256
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from time import monotonic, sleep
import json
import os
import sqlite3
import sys
import tempfile
import unittest

from sglab.comparison_worker import (
    ComparisonWorker,
    process_is_live,
    recover_stale_workers,
    request_stop,
)
from sglab.comparisons import (
    ComparisonStore,
    canonical_sha256,
    import_campaign_snapshot_fixture,
    import_comparison_fixture_bundle,
)
from sglab.db import (
    ACTIVE_DIRECTOR_SCHEMA_SQL,
    BASE_SCHEMA_SQL,
    COMPARISON_SCHEMA_SQL,
    COMPARISON_WORKER_SCHEMA_SQL,
    SCHEMA_VERSION,
    connect,
)
from sglab.research.director import base_instructions
from sglab.research.protocol import director_decision_schema
from sglab.web import create_server


def worker_fixture_material() -> tuple[dict, dict]:
    snapshot_id = "comparison-snapshot-visible"
    action_space = {
        "actions": ["set_review_trigger"],
        "action_applicability": {
            "set_review_trigger": "lane-independent measurement review"
        },
        "active_executable_lane_ids": [],
        "historical_lane_ids": [],
        "candidate_target_ids": [],
        "checkpoint_target_ids": [],
        "reference_objects": [],
    }
    state = {
        "schema_version": "2.0",
        "source_snapshot_id": snapshot_id,
        "allowed_action_space": action_space,
        "campaign_budget": {
            "evaluations": {"remaining": 1000},
            "model_turns": {"remaining": 3},
        },
    }
    reference = {
        "id": snapshot_id,
        "object_kind": "source_snapshot",
        "object_kinds": ["source_snapshot"],
        "current_lifecycle_status": "visible_evidence",
        "director_state_json_paths": ["$.source_snapshot_id"],
        "evidence_allowed": True,
        "advisory_allowed": False,
        "executable_allowed": False,
    }
    evidence = {
        "schema_version": "2.0",
        "role": "evidence_ids",
        "director_state_sha256": canonical_sha256(state),
        "references": [reference],
    }
    advisory = {
        "schema_version": "2.0",
        "role": "advisory_target_ids",
        "director_state_sha256": canonical_sha256(state),
        "references": [],
    }
    executable = {
        "schema_version": "2.0",
        "role": "executable_target_ids",
        "director_state_sha256": canonical_sha256(state),
        "references": [],
    }
    prompt = json.dumps(
        {
            "objective": "Return one measurement-only Director decision.",
            "director_state_v2": state,
            "measurement_contract": {
                "measurement_only": True,
                "decision_will_not_be_executed": True,
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    schema = director_decision_schema(action_space)
    campaign_budget = state["campaign_budget"]
    base = base_instructions()
    materials = {
        "prompt": prompt,
        "output_schema": schema,
        "applicable_action_space": action_space,
        "evidence_registry": evidence,
        "advisory_registry": advisory,
        "executable_registry": executable,
        "base_instructions": base,
        "developer_instructions": "",
        "campaign_budget": campaign_budget,
    }
    hashes = {
        "prompt": _sha(prompt.encode()),
        "output_schema": canonical_sha256(schema),
        "applicable_action_space": canonical_sha256(action_space),
        "evidence_registry": canonical_sha256(evidence),
        "advisory_registry": canonical_sha256(advisory),
        "executable_registry": canonical_sha256(executable),
        "base_instructions": _sha(base.encode()),
        "developer_instructions": _sha(b""),
        "campaign_budget": canonical_sha256(campaign_budget),
    }
    return state, {"materials": materials, "hashes": hashes}


def _sha(value: bytes) -> str:
    import hashlib

    return hashlib.sha256(value).hexdigest()


def seed_worker_fixture(store: ComparisonStore) -> None:
    state, metadata = worker_fixture_material()
    store.seed_fixture(
        fixture_id="worker-fixture",
        display_name="Worker fixture",
        fixture_type="custom_director_state_json",
        source_artifact_reference="deterministic-inline",
        director_state=state,
        metadata={
            **metadata,
            "estimated_client_owned_tokens": 200,
            "status_timestamp": "2026-07-25T00:00:00Z",
        },
    )


def worker_suite_payload(*, three_arms: bool = False) -> dict:
    arms = [
        {
            "display_name": "Stateless",
            "model": "gpt-5.6-luna",
            "reasoning_effort": "xhigh",
            "context_mode": "stateless_turns",
        },
        {
            "display_name": "Persistent first",
            "model": "gpt-5.6-luna",
            "reasoning_effort": "xhigh",
            "context_mode": "persistent_thread",
            "conversation_group_id": "persistent-sequence",
        },
    ]
    if three_arms:
        arms.append(
            {
                "display_name": "Persistent second",
                "model": "gpt-5.6-luna",
                "reasoning_effort": "xhigh",
                "context_mode": "persistent_thread",
                "conversation_group_id": "persistent-sequence",
                "resume_prior_thread": True,
            }
        )
    return {
        "name": "Worker test",
        "description": "Deterministic fake App Server execution",
        "fixture_id": "worker-fixture",
        "arms": arms,
        "timeout_seconds": 2,
        "ordering": "fixed",
        "ordering_seed": 0,
        "measurement_only": True,
        "execute_decisions": False,
        "fail_closed": True,
        "maximum_inference_starts": len(arms),
        "maximum_worker_wall_seconds": 30,
    }


class ComparisonWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        self.database = self.workspace / "results.sqlite3"
        self.fake = (
            Path(__file__).resolve().parent / "fixtures" / "fake_app_server.py"
        )
        self.auth = self.workspace / "synthetic" / "auth.json"
        self.auth.parent.mkdir()
        self.auth.write_text('{"synthetic":true}\n', encoding="utf-8")
        self.auth.chmod(0o600)
        with ComparisonStore(self.database) as store:
            seed_worker_fixture(store)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _authorize(self, *, three_arms: bool = False) -> tuple[str, list[str]]:
        with ComparisonStore(self.database) as store:
            suite_id = store.create_suite(
                worker_suite_payload(three_arms=three_arms),
                created_by="worker-test",
            )
            plan = store.prepare(suite_id)
            store.authorize(suite_id, plan["plan_fingerprint"])
            arm_ids = [
                str(row["arm_id"])
                for row in store.connection.execute(
                    """
                    SELECT arm_id FROM comparison_arms WHERE suite_id=?
                    ORDER BY effective_order
                    """,
                    (suite_id,),
                )
            ]
        return suite_id, arm_ids

    def _authorize_one(
        self, *, maximum_total_server_tokens: int | None = None
    ) -> tuple[str, str]:
        payload = worker_suite_payload()
        payload["arms"] = [payload["arms"][0]]
        payload["maximum_inference_starts"] = 1
        payload["maximum_total_server_tokens"] = maximum_total_server_tokens
        with ComparisonStore(self.database) as store:
            suite_id = store.create_suite(payload, created_by="worker-test")
            plan = store.prepare(suite_id)
            store.authorize(suite_id, plan["plan_fingerprint"])
            arm_id = str(
                store.connection.execute(
                    "SELECT arm_id FROM comparison_arms WHERE suite_id=?",
                    (suite_id,),
                ).fetchone()[0]
            )
        return suite_id, arm_id

    def _run(self, suite_id: str, mode: str):
        return ComparisonWorker(
            workspace=self.workspace,
            suite_id=suite_id,
            auth_source=self.auth,
            launcher=(sys.executable, str(self.fake), f"--fake-mode={mode}"),
        ).run()

    def _authorize_with_limits(
        self, **changes: int
    ) -> tuple[str, list[str]]:
        payload = worker_suite_payload()
        payload.update(changes)
        with ComparisonStore(self.database) as store:
            suite_id = store.create_suite(payload, created_by="worker-test")
            plan = store.prepare(suite_id)
            store.authorize(suite_id, plan["plan_fingerprint"])
            arm_ids = [
                str(row["arm_id"])
                for row in store.connection.execute(
                    """
                    SELECT arm_id FROM comparison_arms WHERE suite_id=?
                    ORDER BY effective_order
                    """,
                    (suite_id,),
                )
            ]
        return suite_id, arm_ids

    def test_success_uses_stateless_fresh_and_persistent_group(self) -> None:
        suite_id, arm_ids = self._authorize(three_arms=True)
        result = self._run(suite_id, "director-screen-success")
        self.assertTrue(result.ok, result.terminal_reason)
        self.assertEqual(result.inference_starts, 3)
        with ComparisonStore(self.database) as store:
            suite = store._suite_row(suite_id)
            self.assertEqual(suite["status"], "completed")
            turns = list(
                store.connection.execute(
                    """
                    SELECT t.*, a.arm_id FROM comparison_turns t
                    JOIN comparison_arms a ON a.arm_id=t.arm_id
                    WHERE t.suite_id=? ORDER BY a.effective_order
                    """,
                    (suite_id,),
                )
            )
            self.assertEqual(len(turns), 3)
            self.assertTrue(all(row["lifecycle_status"] == "completed" for row in turns))
            self.assertEqual(turns[0]["thread_lifecycle"], "fresh")
            self.assertEqual(turns[1]["thread_lifecycle"], "fresh")
            self.assertEqual(turns[2]["thread_lifecycle"], "resumed")
            self.assertNotEqual(turns[0]["thread_id"], turns[1]["thread_id"])
            self.assertEqual(turns[1]["thread_id"], turns[2]["thread_id"])
            self.assertTrue(all(row["measurement_only"] for row in turns))
            self.assertTrue(all(not row["executed"] for row in turns))
            self.assertEqual(
                store.connection.execute(
                    "SELECT count(*) FROM research_lanes"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                store.connection.execute(
                    "SELECT count(*) FROM comparison_inference_reservations "
                    "WHERE inference_reached_at IS NOT NULL"
                ).fetchone()[0],
                3,
            )
            self.assertEqual(
                [
                    store.connection.execute(
                        """
                        SELECT lifecycle_state FROM comparison_arm_transitions
                        WHERE arm_id=? ORDER BY sequence_number DESC LIMIT 1
                        """,
                        (arm_id,),
                    ).fetchone()[0]
                    for arm_id in arm_ids
                ],
                ["completed", "completed", "completed"],
            )

    def test_transient_80m_scratch_does_not_consume_preserved_quota(self) -> None:
        suite_id, _ = self._authorize()
        result = self._run(suite_id, "director-screen-scratch-80m")
        self.assertTrue(result.ok, result.terminal_reason)
        self.assertEqual(result.inference_starts, 2)
        with ComparisonStore(self.database) as store:
            scratch = store.connection.execute(
                """
                SELECT * FROM comparison_resource_samples
                WHERE suite_id=? AND category='runtime_scratch'
                  AND sample_kind='terminal'
                """,
                (suite_id,),
            ).fetchone()
            preserved = store.connection.execute(
                """
                SELECT * FROM comparison_resource_samples
                WHERE suite_id=? AND category='preserved_artifacts'
                  AND sample_kind='terminal'
                """,
                (suite_id,),
            ).fetchone()
            self.assertGreaterEqual(
                scratch["peak_apparent_bytes"], 80 * 1024 * 1024
            )
            peak = store.connection.execute(
                """
                SELECT * FROM comparison_resource_samples
                WHERE suite_id=? AND category='runtime_scratch'
                  AND sample_kind='peak'
                """,
                (suite_id,),
            ).fetchone()
            peak_files = json.loads(peak["largest_files_json"])
            self.assertTrue(any(row["sparse"] for row in peak_files))
            self.assertLess(
                peak["current_allocated_bytes"],
                peak["current_apparent_bytes"],
            )
            self.assertLess(
                scratch["current_apparent_bytes"],
                scratch["peak_apparent_bytes"],
            )
            self.assertLess(
                preserved["peak_apparent_bytes"], 64 * 1024 * 1024
            )

    def test_scratch_quota_crossing_is_attributed_before_cleanup(self) -> None:
        suite_id, arm_ids = self._authorize_with_limits(
            max_runtime_scratch_bytes=4 * 1024 * 1024,
            max_single_runtime_file_bytes=4 * 1024 * 1024,
        )
        result = self._run(
            suite_id, "director-screen-scratch-total-exceed"
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.inference_starts, 1)
        with ComparisonStore(self.database) as store:
            crossing = store.connection.execute(
                """
                SELECT * FROM comparison_resource_samples
                WHERE suite_id=? AND category='runtime_scratch'
                  AND sample_kind='threshold_crossing'
                """,
                (suite_id,),
            ).fetchone()
            self.assertIsNotNone(crossing)
            self.assertGreaterEqual(
                crossing["peak_apparent_bytes"], 6 * 1024 * 1024
            )
            self.assertIn(
                "transient-runtime.bin",
                crossing["largest_contributor_relative_path"],
            )
            self.assertEqual(crossing["failure_domain"], "byte_quota")
            self.assertEqual(crossing["byte_quota_exceeded"], 1)
            self.assertGreater(
                crossing["current_apparent_bytes"],
                crossing["configured_limit_bytes"],
            )
            self.assertEqual(crossing["interruption_sent"], 1)
            latest = [
                store.connection.execute(
                    """
                    SELECT lifecycle_state FROM comparison_arm_transitions
                    WHERE arm_id=? ORDER BY sequence_number DESC LIMIT 1
                    """,
                    (arm_id,),
                ).fetchone()[0]
                for arm_id in arm_ids
            ]
            self.assertEqual(latest, ["failed", "blocked"])

    def test_preserved_artifact_quota_fails_before_large_response_write(self) -> None:
        suite_id, arm_ids = self._authorize_with_limits(
            max_preserved_artifact_bytes=1024 * 1024,
            max_single_preserved_artifact_bytes=1024 * 1024,
            maximum_stdout_bytes=8 * 1024 * 1024,
        )
        result = self._run(suite_id, "director-screen-large-response")
        self.assertFalse(result.ok)
        with ComparisonStore(self.database) as store:
            suite = store._suite_row(suite_id)
            self.assertEqual(
                suite["resource_exceeded_category"], "preserved_artifacts"
            )
            first_root = (
                self.workspace
                / ".sglab"
                / "comparisons"
                / suite_id
                / "arms"
                / arm_ids[0]
            )
            self.assertFalse((first_root / "response.json").exists())
            self.assertEqual(
                store.connection.execute(
                    """
                    SELECT lifecycle_state FROM comparison_arm_transitions
                    WHERE arm_id=? ORDER BY sequence_number DESC LIMIT 1
                    """,
                    (arm_ids[1],),
                ).fetchone()[0],
                "blocked",
            )

    def test_single_preserved_file_cap_identifies_pending_file(self) -> None:
        suite_id, _ = self._authorize_with_limits(
            max_preserved_artifact_bytes=4 * 1024 * 1024,
            max_single_preserved_artifact_bytes=1024 * 1024,
            maximum_stdout_bytes=8 * 1024 * 1024,
        )
        result = self._run(suite_id, "director-screen-large-response")
        self.assertFalse(result.ok)
        with ComparisonStore(self.database) as store:
            suite = store._suite_row(suite_id)
            self.assertEqual(
                suite["resource_exceeded_limit_bytes"], 1024 * 1024
            )
            self.assertIn("response.json", suite["resource_largest_contributor"])

    def test_wal_peak_survives_shutdown_cleanup(self) -> None:
        suite_id, _ = self._authorize_with_limits(
            max_runtime_scratch_bytes=4 * 1024 * 1024,
            max_single_runtime_file_bytes=4 * 1024 * 1024,
        )
        result = self._run(suite_id, "director-screen-wal-growth")
        self.assertFalse(result.ok)
        with ComparisonStore(self.database) as store:
            crossing = store.connection.execute(
                """
                SELECT * FROM comparison_resource_samples
                WHERE suite_id=? AND category='runtime_scratch'
                  AND sample_kind='threshold_crossing'
                """,
                (suite_id,),
            ).fetchone()
            terminal = store.connection.execute(
                """
                SELECT * FROM comparison_resource_samples
                WHERE suite_id=? AND category='runtime_scratch'
                  AND sample_kind='terminal'
                """,
                (suite_id,),
            ).fetchone()
            self.assertIn(
                "state_5.sqlite-wal",
                crossing["largest_contributor_relative_path"],
            )
            self.assertLess(
                terminal["current_apparent_bytes"],
                crossing["peak_apparent_bytes"],
            )
            self.assertEqual(terminal["cleanup_reduced_size"], 1)

    def test_runtime_hardlink_is_not_double_counted_by_worker(self) -> None:
        suite_id, _ = self._authorize_with_limits(
            max_runtime_scratch_bytes=6 * 1024 * 1024,
            max_single_runtime_file_bytes=6 * 1024 * 1024,
        )
        result = self._run(suite_id, "director-screen-hardlink")
        self.assertTrue(result.ok, result.terminal_reason)
        with ComparisonStore(self.database) as store:
            peak = store.connection.execute(
                """
                SELECT * FROM comparison_resource_samples
                WHERE suite_id=? AND category='runtime_scratch'
                  AND sample_kind='peak'
                """,
                (suite_id,),
            ).fetchone()
            self.assertLess(
                peak["peak_apparent_bytes"], 6 * 1024 * 1024
            )
            contributors = json.loads(peak["largest_files_json"])
            self.assertEqual(
                sum(
                    "transient-runtime.bin" in row["relative_path"]
                    for row in contributors
                ),
                1,
            )

    def test_runtime_symlink_escape_is_rejected_without_following(self) -> None:
        suite_id, arm_ids = self._authorize()
        result = self._run(suite_id, "director-screen-symlink-escape")
        self.assertFalse(result.ok)
        self.assertEqual(result.inference_starts, 1)
        with ComparisonStore(self.database) as store:
            crossing = store.connection.execute(
                """
                SELECT * FROM comparison_resource_samples
                WHERE suite_id=? AND category='runtime_scratch'
                  AND sample_kind='threshold_crossing'
                """,
                (suite_id,),
            ).fetchone()
            self.assertIn("escape-link", crossing["accounting_errors_json"])
            self.assertEqual(
                crossing["failure_domain"], "filesystem_policy"
            )
            self.assertEqual(
                crossing["failure_code"],
                "unexpected_external_symlink",
            )
            self.assertEqual(crossing["byte_quota_exceeded"], 0)
            self.assertEqual(crossing["byte_quota_status"], "within_limit")
            self.assertEqual(
                store.connection.execute(
                    """
                    SELECT lifecycle_state FROM comparison_arm_transitions
                    WHERE arm_id=? ORDER BY sequence_number DESC LIMIT 1
                    """,
                    (arm_ids[1],),
                ).fetchone()[0],
                "blocked",
            )

    def test_expected_app_server_wrappers_allow_two_fake_arms(self) -> None:
        suite_id, _ = self._authorize()
        result = self._run(suite_id, "director-screen-wrappers")
        self.assertTrue(result.ok, result.terminal_reason)
        self.assertEqual(result.inference_starts, 2)
        with ComparisonStore(self.database) as store:
            rows = list(
                store.connection.execute(
                    """
                    SELECT symlink_policy_status, symlink_observations_json
                    FROM comparison_resource_samples
                    WHERE suite_id=? AND category='runtime_scratch'
                    """,
                    (suite_id,),
                )
            )
            self.assertTrue(rows)
            self.assertTrue(
                all(row["symlink_policy_status"] == "passed" for row in rows)
            )
            observed = [
                item
                for row in rows
                for item in json.loads(
                    row["symlink_observations_json"] or "[]"
                )
            ]
            self.assertEqual(
                {
                    item["wrapper_basename"]
                    for item in observed
                    if item["classification"]
                    == "expected_runtime_wrapper"
                },
                {
                    "apply_patch",
                    "applypatch",
                    "codex-execve-wrapper",
                    "codex-linux-sandbox",
                },
            )
            self.assertTrue(
                all(item["no_follow_confirmed"] for item in observed)
            )

    def test_expected_wrapper_two_arm_soak_ten_times(self) -> None:
        for _ in range(10):
            suite_id, _ = self._authorize()
            result = self._run(suite_id, "director-screen-wrappers")
            self.assertTrue(result.ok, result.terminal_reason)
            self.assertEqual(result.inference_starts, 2)
            with ComparisonStore(self.database) as store:
                self.assertEqual(
                    store.connection.execute(
                        """
                        SELECT count(*) FROM comparison_worker_leases
                        WHERE suite_id=? AND released_at IS NULL
                        """,
                        (suite_id,),
                    ).fetchone()[0],
                    0,
                )

    def test_unexpected_wrapper_fails_as_filesystem_policy(self) -> None:
        suite_id, arm_ids = self._authorize()
        result = self._run(
            suite_id, "director-screen-wrapper-unexpected"
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.inference_starts, 0)
        with ComparisonStore(self.database) as store:
            suite = store._suite_row(suite_id)
            self.assertEqual(suite["failure_domain"], "filesystem_policy")
            self.assertEqual(
                suite["failure_code"], "unexpected_external_symlink"
            )
            self.assertEqual(suite["byte_quota_exceeded"], 0)
            self.assertIsNone(suite["resource_exceeded_limit_bytes"])
            self.assertEqual(
                store.connection.execute(
                    """
                    SELECT lifecycle_state FROM comparison_arm_transitions
                    WHERE arm_id=? ORDER BY sequence_number DESC LIMIT 1
                    """,
                    (arm_ids[1],),
                ).fetchone()[0],
                "blocked",
            )

    def test_wrapper_basename_in_wrong_directory_is_rejected(self) -> None:
        suite_id, _ = self._authorize()
        result = self._run(
            suite_id, "director-screen-wrapper-wrong-directory"
        )
        self.assertFalse(result.ok)
        with ComparisonStore(self.database) as store:
            suite = store._suite_row(suite_id)
            self.assertEqual(suite["failure_domain"], "filesystem_policy")
            self.assertEqual(
                suite["failure_code"], "unexpected_external_symlink"
            )

    def test_wrapper_with_untrusted_target_is_rejected(self) -> None:
        suite_id, _ = self._authorize()
        result = self._run(
            suite_id, "director-screen-wrapper-untrusted"
        )
        self.assertFalse(result.ok)
        with ComparisonStore(self.database) as store:
            suite = store._suite_row(suite_id)
            self.assertEqual(suite["failure_domain"], "filesystem_policy")

    def test_broken_wrapper_is_rejected_explicitly(self) -> None:
        suite_id, _ = self._authorize()
        result = self._run(
            suite_id, "director-screen-wrapper-broken"
        )
        self.assertFalse(result.ok)
        with ComparisonStore(self.database) as store:
            suite = store._suite_row(suite_id)
            self.assertEqual(suite["failure_domain"], "filesystem_policy")
            self.assertEqual(suite["failure_code"], "broken_symlink")

    def test_single_runtime_file_has_separate_failure_domain(self) -> None:
        suite_id, _ = self._authorize_with_limits(
            max_runtime_scratch_bytes=16 * 1024 * 1024,
            max_single_runtime_file_bytes=4 * 1024 * 1024,
        )
        result = self._run(suite_id, "director-screen-scratch-exceed")
        self.assertFalse(result.ok)
        with ComparisonStore(self.database) as store:
            suite = store._suite_row(suite_id)
            self.assertEqual(
                suite["failure_domain"], "single_file_quota"
            )
            self.assertEqual(suite["byte_quota_exceeded"], 0)

    def test_completed_arm_remains_valid_when_shutdown_scratch_fails_suite(self) -> None:
        suite_id, arm_ids = self._authorize_with_limits(
            max_runtime_scratch_bytes=4 * 1024 * 1024,
            max_single_runtime_file_bytes=4 * 1024 * 1024,
        )
        result = self._run(suite_id, "director-screen-scratch-on-shutdown")
        self.assertFalse(result.ok)
        self.assertEqual(result.inference_starts, 1)
        with ComparisonStore(self.database) as store:
            turn = store.connection.execute(
                "SELECT * FROM comparison_turns WHERE arm_id=?",
                (arm_ids[0],),
            ).fetchone()
            self.assertEqual(turn["lifecycle_status"], "completed")
            self.assertEqual(turn["schema_valid"], 1)
            self.assertEqual(turn["semantic_valid"], 1)
            latest = [
                store.connection.execute(
                    """
                    SELECT lifecycle_state FROM comparison_arm_transitions
                    WHERE arm_id=? ORDER BY sequence_number DESC LIMIT 1
                    """,
                    (arm_id,),
                ).fetchone()[0]
                for arm_id in arm_ids
            ]
            self.assertEqual(latest, ["completed", "blocked"])
            suite = store._suite_row(suite_id)
            self.assertEqual(suite["status"], "failed")
            self.assertEqual(suite["resource_active_turn_completed"], 1)
            self.assertEqual(suite["resource_later_arms_blocked"], 1)

    def test_log_growth_is_bounded_with_observed_size_marker(self) -> None:
        suite_id, arm_ids = self._authorize_with_limits(
            maximum_stderr_bytes=4096
        )
        result = self._run(suite_id, "director-screen-log-growth")
        self.assertTrue(result.ok, result.terminal_reason)
        for arm_id in arm_ids:
            stderr = (
                self.workspace
                / ".sglab"
                / "comparisons"
                / suite_id
                / "arms"
                / arm_id
                / "stderr.log"
            )
            self.assertLessEqual(stderr.stat().st_size, 4096)
            self.assertIn("original_observed_bytes", stderr.read_text())

    def test_two_valid_fake_arms_release_lease_without_orphan(self) -> None:
        suite_id, _ = self._authorize()
        result = self._run(suite_id, "director-screen-success")
        self.assertTrue(result.ok, result.terminal_reason)
        self.assertEqual(result.inference_starts, 2)
        with ComparisonStore(self.database) as store:
            self.assertNotIn(
                "credential_material",
                {
                    row["category"]
                    for row in store.suite_detail(suite_id)["resource_samples"]
                },
            )
            self.assertEqual(
                store.connection.execute(
                    """
                    SELECT count(*) FROM comparison_worker_leases
                    WHERE suite_id=? AND released_at IS NULL
                    """,
                    (suite_id,),
                ).fetchone()[0],
                0,
            )

    def test_timeout_on_persistent_second_blocks_no_replacement(self) -> None:
        suite_id, arm_ids = self._authorize(three_arms=True)
        result = self._run(suite_id, "director-screen-timeout-second")
        self.assertFalse(result.ok)
        self.assertEqual(result.inference_starts, 3)
        with ComparisonStore(self.database) as store:
            turns = list(
                store.connection.execute(
                    "SELECT * FROM comparison_turns WHERE suite_id=?",
                    (suite_id,),
                )
            )
            self.assertEqual(len(turns), 3)
            timed_out = [row for row in turns if row["lifecycle_status"] == "timed_out"]
            self.assertEqual(len(timed_out), 1)
            self.assertIsNone(timed_out[0]["server_reported_total_tokens"])
            self.assertEqual(timed_out[0]["usage_present"], 0)
            self.assertEqual(
                store.connection.execute(
                    "SELECT consumed_inference_starts FROM comparison_suites "
                    "WHERE suite_id=?",
                    (suite_id,),
                ).fetchone()[0],
                3,
            )
            self.assertEqual(
                store.connection.execute(
                    "SELECT count(*) FROM comparison_arms WHERE suite_id=?",
                    (suite_id,),
                ).fetchone()[0],
                len(arm_ids),
            )

    def test_independent_invalid_arm_continues_to_second(self) -> None:
        for mode, expected in (
            ("director-screen-schema-invalid-first", "schema_invalid"),
            ("director-screen-semantic-invalid-first", "semantic_invalid"),
        ):
            with self.subTest(mode=mode):
                suite_id, arm_ids = self._authorize()
                result = self._run(suite_id, mode)
                self.assertFalse(result.ok)
                self.assertEqual(result.inference_starts, 2)
                with ComparisonStore(self.database) as store:
                    latest = [
                        store.connection.execute(
                            """
                            SELECT lifecycle_state FROM comparison_arm_transitions
                            WHERE arm_id=? ORDER BY sequence_number DESC LIMIT 1
                            """,
                            (arm_id,),
                        ).fetchone()[0]
                        for arm_id in arm_ids
                    ]
                    self.assertEqual(latest, [expected, "completed"])
                    self.assertEqual(
                        store.connection.execute(
                            "SELECT count(*) FROM director_action_batches"
                        ).fetchone()[0],
                        0,
                    )
                    self.assertEqual(
                        store.connection.execute(
                            "SELECT count(*) FROM director_actions"
                        ).fetchone()[0],
                        0,
                    )

    def test_infrastructure_failure_still_blocks_second(self) -> None:
        suite_id, arm_ids = self._authorize()
        result = self._run(suite_id, "director-screen-process-crash")
        self.assertFalse(result.ok)
        self.assertEqual(result.inference_starts, 1)
        with ComparisonStore(self.database) as store:
            latest = [
                store.connection.execute(
                    """
                    SELECT lifecycle_state FROM comparison_arm_transitions
                    WHERE arm_id=? ORDER BY sequence_number DESC LIMIT 1
                    """,
                    (arm_id,),
                ).fetchone()[0]
                for arm_id in arm_ids
            ]
            self.assertEqual(latest, ["failed", "blocked"])

    def test_invalid_persistent_predecessor_blocks_dependent_arm(self) -> None:
        suite_id, arm_ids = self._authorize(three_arms=True)
        result = self._run(
            suite_id,
            "director-screen-semantic-invalid-second",
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.inference_starts, 2)
        with ComparisonStore(self.database) as store:
            latest = [
                store.connection.execute(
                    """
                    SELECT lifecycle_state FROM comparison_arm_transitions
                    WHERE arm_id=? ORDER BY sequence_number DESC LIMIT 1
                    """,
                    (arm_id,),
                ).fetchone()[0]
                for arm_id in arm_ids
            ]
            self.assertEqual(
                latest,
                ["completed", "semantic_invalid", "blocked"],
            )
            self.assertEqual(
                store.connection.execute(
                    "SELECT count(*) FROM director_action_batches"
                ).fetchone()[0],
                0,
            )

    def test_plan_change_and_revocation_fail_before_auth_copy(self) -> None:
        suite_id, _ = self._authorize()
        self.auth.unlink()
        with ComparisonStore(self.database) as store, store.connection:
            store.connection.execute(
                "UPDATE comparison_arms SET prompt_sha256=? WHERE suite_id=?",
                ("f" * 64, suite_id),
            )
        result = self._run(suite_id, "director-screen-success")
        self.assertFalse(result.ok)
        self.assertIn("fingerprint", result.terminal_reason or "")
        self.assertEqual(result.inference_starts, 0)
        self.assertFalse(
            (self.workspace / ".sglab" / "comparisons" / suite_id).exists()
        )
        revoked_id, _ = self._authorize_one()
        with ComparisonStore(self.database) as store, store.connection:
            store.connection.execute(
                """
                UPDATE comparison_authorizations SET revoked_at=?
                WHERE suite_id=?
                """,
                ("2026-07-25T00:00:00Z", revoked_id),
            )
        revoked = self._run(revoked_id, "director-screen-success")
        self.assertFalse(revoked.ok)
        self.assertEqual(revoked.inference_starts, 0)
        self.assertIn("authorization", revoked.terminal_reason or "")

    def test_randomized_order_keeps_persistent_sequence_contiguous(self) -> None:
        payload = worker_suite_payload(three_arms=True)
        payload["ordering"] = "randomized"
        payload["ordering_seed"] = 20260725
        payload["arms"].append(
            {
                "display_name": "Second stateless",
                "model": "gpt-5.6-luna",
                "reasoning_effort": "xhigh",
                "context_mode": "stateless_turns",
            }
        )
        payload["maximum_inference_starts"] = 4
        with ComparisonStore(self.database) as store:
            suite_id = store.create_suite(payload)
            rows = list(
                store.connection.execute(
                    """
                    SELECT conversation_group_id, sequence_index, effective_order
                    FROM comparison_arms WHERE suite_id=?
                    ORDER BY effective_order
                    """,
                    (suite_id,),
                )
            )
        group_positions = [
            index
            for index, row in enumerate(rows)
            if row["conversation_group_id"] == "persistent-sequence"
        ]
        self.assertEqual(len(group_positions), 2)
        self.assertEqual(group_positions[1], group_positions[0] + 1)
        self.assertEqual(
            [rows[index]["sequence_index"] for index in group_positions],
            [0, 1],
        )

    def test_reservation_release_before_and_no_refund_after_inference(self) -> None:
        suite_id, _ = self._authorize()
        missing = self.workspace / "missing" / "auth.json"
        result = ComparisonWorker(
            workspace=self.workspace,
            suite_id=suite_id,
            auth_source=missing,
            launcher=(
                sys.executable,
                str(self.fake),
                "--fake-mode=director-screen-success",
            ),
        ).run()
        self.assertFalse(result.ok)
        with ComparisonStore(self.database) as store:
            reservation = store.connection.execute(
                "SELECT * FROM comparison_inference_reservations"
            ).fetchone()
            self.assertIsNone(reservation)
            self.assertEqual(
                store.connection.execute(
                    "SELECT consumed_inference_starts FROM comparison_suites "
                    "WHERE suite_id=?",
                    (suite_id,),
                ).fetchone()[0],
                0,
            )

    def test_worker_lease_exclusive_heartbeat_release_and_recovery(self) -> None:
        suite_id, _ = self._authorize()
        with ComparisonStore(self.database) as store, store.connection:
            attempt = "stale-attempt"
            authorization = store.connection.execute(
                "SELECT authorization_id, plan_fingerprint "
                "FROM comparison_authorizations WHERE suite_id=?",
                (suite_id,),
            ).fetchone()
            store.connection.execute(
                """
                INSERT INTO comparison_execution_attempts
                (attempt_id, suite_id, authorization_id, worker_instance_id,
                 plan_fingerprint, plan_verification_artifact,
                 plan_verification_sha256, status, pid, process_group_id,
                 host_identifier, started_at)
                VALUES (?, ?, ?, 'old-worker', ?, 'old.json', ?, 'running',
                        99999999, 99999999, 'old-host', ?)
                """,
                (
                    attempt,
                    suite_id,
                    authorization["authorization_id"],
                    authorization["plan_fingerprint"],
                    "a" * 64,
                    "2020-01-01T00:00:00Z",
                ),
            )
            store.connection.execute(
                """
                INSERT INTO comparison_worker_leases
                (lease_id, worker_instance_id, suite_id, attempt_id, pid,
                 process_group_id, host_identifier, acquired_at, heartbeat_at,
                 lease_expires_at)
                VALUES ('stale-lease', 'old-worker', ?, ?, 99999999,
                        99999999, 'old-host', ?, ?, ?)
                """,
                (
                    suite_id,
                    attempt,
                    "2020-01-01T00:00:00Z",
                    "2020-01-01T00:00:00Z",
                    "2020-01-01T00:00:01Z",
                ),
            )
            store.connection.execute(
                "UPDATE comparison_suites SET status='running' WHERE suite_id=?",
                (suite_id,),
            )
        self.assertEqual(recover_stale_workers(self.database), [suite_id])
        with ComparisonStore(self.database) as store:
            lease = store.connection.execute(
                "SELECT * FROM comparison_worker_leases WHERE lease_id='stale-lease'"
            ).fetchone()
            self.assertIsNotNone(lease["released_at"])
            self.assertEqual(store._suite_row(suite_id)["status"], "failed")

    def test_stop_request_is_durable_and_not_a_pid_kill_api(self) -> None:
        suite_id, _ = self._authorize()
        request_id = request_stop(self.database, suite_id)
        with ComparisonStore(self.database) as store:
            row = store.connection.execute(
                "SELECT * FROM comparison_stop_requests WHERE stop_request_id=?",
                (request_id,),
            ).fetchone()
            self.assertEqual(row["state"], "stopped")
            self.assertIsNone(row["attempt_id"])
            self.assertEqual(store._suite_row(suite_id)["stop_state"], "stopped")

    def test_runtime_fault_matrix_uses_one_fail_closed_worker_path(self) -> None:
        cases = (
            ("director-screen-model-mismatch", 0, "failed"),
            ("director-screen-context-mismatch", 0, "failed"),
            ("director-screen-malformed-jsonl", 1, "failed"),
            ("director-screen-process-crash", 1, "failed"),
            ("director-screen-unsupported-request", 1, "failed"),
            ("director-screen-retrying-error", 1, "failed"),
            ("director-screen-tool-call", 1, "failed"),
        )
        for mode, starts, lifecycle in cases:
            with self.subTest(mode=mode):
                suite_id, arm_id = self._authorize_one()
                result = self._run(suite_id, mode)
                self.assertFalse(result.ok)
                self.assertEqual(result.inference_starts, starts)
                with ComparisonStore(self.database) as store:
                    self.assertEqual(
                        store.connection.execute(
                            """
                            SELECT lifecycle_state FROM comparison_arm_transitions
                            WHERE arm_id=? ORDER BY sequence_number DESC LIMIT 1
                            """,
                            (arm_id,),
                        ).fetchone()[0],
                        lifecycle,
                    )
                    if mode == "director-screen-tool-call":
                        self.assertEqual(
                            store.connection.execute(
                                "SELECT tool_call_count FROM comparison_turns "
                                "WHERE arm_id=?",
                                (arm_id,),
                            ).fetchone()[0],
                            1,
                        )
                    if mode == "director-screen-retrying-error":
                        self.assertEqual(
                            store.connection.execute(
                                """
                                SELECT retry_count_reaching_inference
                                FROM comparison_turns WHERE arm_id=?
                                """,
                                (arm_id,),
                            ).fetchone()[0],
                            0,
                        )

    def test_missing_usage_is_nullable_unless_strict_cap_requires_it(self) -> None:
        suite_id, _ = self._authorize_one()
        result = self._run(suite_id, "director-screen-no-usage")
        self.assertTrue(result.ok, result.terminal_reason)
        with ComparisonStore(self.database) as store:
            turn = store.connection.execute(
                "SELECT * FROM comparison_turns WHERE suite_id=?",
                (suite_id,),
            ).fetchone()
            self.assertEqual(turn["usage_present"], 0)
            self.assertIsNone(turn["server_reported_total_tokens"])
        strict_id, _ = self._authorize_one(maximum_total_server_tokens=100)
        strict = self._run(strict_id, "director-screen-no-usage")
        self.assertFalse(strict.ok)
        self.assertEqual(strict.inference_starts, 1)

    def test_late_abort_updates_same_incomplete_turn(self) -> None:
        suite_id, _ = self._authorize(three_arms=True)
        result = self._run(
            suite_id, "director-screen-late-abort-second"
        )
        self.assertFalse(result.ok)
        with ComparisonStore(self.database) as store:
            app_rows = list(
                store.connection.execute(
                    """
                    SELECT * FROM app_server_turns
                    WHERE campaign_id=(
                        SELECT campaign_id FROM comparison_runtime_campaigns
                        WHERE suite_id=?
                    )
                    ORDER BY started_at
                    """,
                    (suite_id,),
                )
            )
            self.assertEqual(len(app_rows), 3)
            self.assertIn(
                app_rows[-1]["lifecycle_status"], {"aborted", "timed_out"}
            )
            self.assertEqual(
                len(json.loads(app_rows[-1]["reasoning_item_ids_json"])),
                2,
            )


class ComparisonWorkerMigrationTests(unittest.TestCase):
    def test_campaign_snapshot_import_is_isolated_and_executable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "preserved-source"
            campaign = source / "research-campaigns" / "source-campaign"
            snapshots = campaign / "snapshots"
            snapshots.mkdir(parents=True)
            snapshot = {
                "schema_version": "3.0",
                "snapshot_id": "snapshot-a4",
                "created_at": "2026-07-24T00:00:00Z",
                "campaign": {
                    "campaign_id": "source-campaign",
                    "state": "running",
                    "state_version": 4,
                    "stop_mode": "time_limit",
                    "elapsed_seconds": 30,
                    "remaining_seconds": 570,
                },
                "target": {
                    "target_id": "erdos_gyarfas",
                    "immutable_definition_hash": "a" * 64,
                    "success_authority": "M4_independent_verifier",
                },
                "lanes": [],
                "hypotheses": [],
                "global_best": None,
                "recent_actions": [],
                "available_evidence_ids": [],
            }
            snapshot_bytes = json.dumps(
                snapshot, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            snapshot_path = snapshots / "snapshot-a4.json"
            snapshot_path.write_bytes(snapshot_bytes)
            connection = connect(source / "results.sqlite3")
            try:
                connection.execute(
                    """
                    INSERT INTO research_campaigns
                    (campaign_id, created_at, updated_at, target,
                     target_definition_sha256, state, state_version, stop_mode)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "source-campaign",
                        "2026-07-24T00:00:00Z",
                        "2026-07-24T00:00:00Z",
                        "erdos_gyarfas",
                        "a" * 64,
                        "running",
                        4,
                        "time_limit",
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO director_snapshots
                    (snapshot_id, campaign_id, campaign_state_version,
                     high_water_json, artifact_ref, artifact_sha256,
                     payload_bytes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "snapshot-a4",
                        "source-campaign",
                        4,
                        "{}",
                        "snapshots/snapshot-a4.json",
                        sha256(snapshot_bytes).hexdigest(),
                        len(snapshot_bytes),
                        "2026-07-24T00:00:00Z",
                    ),
                )
                connection.commit()
            finally:
                connection.close()
            (source / "active-research-campaign.json").write_text(
                json.dumps({"campaign_dir": str(campaign)}),
                encoding="utf-8",
            )
            (source / "ai-experiment-report.json").write_text(
                json.dumps(
                    {
                        "campaign_id": "source-campaign",
                        "second_snapshot_id": "snapshot-a4",
                        "model_inferences": 2,
                        "search_batches": 1,
                    }
                ),
                encoding="utf-8",
            )
            source_hash = sha256(snapshot_path.read_bytes()).hexdigest()
            destination = root / "model-comparisons-live"
            result = import_campaign_snapshot_fixture(
                source_workspace=source,
                destination_workspace=destination,
                snapshot_reference="A4",
                display_name="M6 executable preserved A4",
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["schema_version"], SCHEMA_VERSION)
            self.assertFalse(result["synthetic_data"])
            self.assertEqual(
                sha256(snapshot_path.read_bytes()).hexdigest(), source_hash
            )
            self.assertFalse(
                any(
                    path.name.startswith("source-online-backup")
                    for path in destination.iterdir()
                )
            )
            self.assertFalse(
                any(
                    "auth.json" in path.name
                    for path in destination.rglob("*")
                )
            )
            with ComparisonStore(destination / "results.sqlite3") as store:
                fixture = store.connection.execute(
                    """
                    SELECT * FROM comparison_fixtures
                    WHERE fixture_id='m6-executable-preserved-a4'
                    """
                ).fetchone()
                self.assertIsNotNone(fixture)
                self.assertEqual(fixture["fixture_type"], "campaign_snapshot")
                self.assertIsNotNone(fixture["prompt_text"])
                self.assertIsNotNone(fixture["base_instructions_text"])
                self.assertEqual(
                    store.connection.execute(
                        "PRAGMA integrity_check"
                    ).fetchone()[0],
                    "ok",
                )
                self.assertEqual(
                    list(store.connection.execute("PRAGMA foreign_key_check")),
                    [],
                )

    def test_admin_fixture_bundle_install_is_hash_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state, metadata = worker_fixture_material()
            bundle = {
                "schema_version": "1.0",
                "fixture_id": "installed-fixture",
                "display_name": "Installed fixture",
                "fixture_type": "custom_director_state_json",
                "director_state": state,
                "status_timestamp": "2026-07-25T00:00:00Z",
                "target_statement_id": "erdos_gyarfas",
                "materials": metadata["materials"],
            }
            path = root / "fixture.json"
            path.write_text(json.dumps(bundle), encoding="utf-8")
            fixture_id = import_comparison_fixture_bundle(
                root / "results.sqlite3", path
            )
            self.assertEqual(fixture_id, "installed-fixture")
            with ComparisonStore(root / "results.sqlite3") as store:
                row = store.connection.execute(
                    "SELECT * FROM comparison_fixtures WHERE fixture_id=?",
                    (fixture_id,),
                ).fetchone()
                self.assertIsNotNone(row["prompt_text"])
                self.assertEqual(
                    row["output_schema_sha256"],
                    canonical_sha256(metadata["materials"]["output_schema"]),
                )

    def test_v11_online_backup_migrates_to_v15_and_preserves_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.sqlite3"
            connection = sqlite3.connect(source)
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript(BASE_SCHEMA_SQL)
            connection.executescript(ACTIVE_DIRECTOR_SCHEMA_SQL)
            connection.executescript(COMPARISON_SCHEMA_SQL)
            connection.executescript(COMPARISON_WORKER_SCHEMA_SQL)
            connection.execute(
                """
                INSERT INTO comparison_fixtures
                VALUES ('old-fixture', 'Old', 'custom_director_state_json',
                        'inline', ?, '2.0', 'target', 'timestamp', 2, 1, '{}',
                        ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 'created')
                """,
                tuple("a" * 64 for _ in range(10)),
            )
            connection.execute(
                """
                INSERT INTO comparison_suites
                (suite_id, name, description, fixture_type, fixture_reference,
                 fixture_sha256, created_at, created_by, status,
                 measurement_only, execute_decisions, randomized_arm_order,
                 planned_inference_count, maximum_inference_starts,
                 timeout_seconds, fail_closed, authorization_status,
                 read_only, runtime_executed_elsewhere)
                VALUES ('old-suite', 'Old', 'Historical',
                        'custom_director_state_json', 'old-fixture', ?,
                        'created', 'test', 'completed', 1, 0, 0, 0, 0, 300,
                        1, 'historical', 1, 1)
                """,
                ("a" * 64,),
            )
            connection.commit()
            backup_path = root / "snapshot.sqlite3"
            backup = sqlite3.connect(backup_path)
            connection.backup(backup)
            backup.close()
            connection.close()
            migrated = connect(backup_path)
            self.assertEqual(SCHEMA_VERSION, 15)
            self.assertEqual(migrated.execute("PRAGMA user_version").fetchone()[0], 15)
            self.assertEqual(
                migrated.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )
            self.assertEqual(
                migrated.execute("PRAGMA foreign_key_check").fetchall(), []
            )
            preserved = migrated.execute(
                """
                SELECT read_only, runtime_executed_elsewhere,
                       resource_accounting_version, arm_failure_policy
                FROM comparison_suites WHERE suite_id='old-suite'
                """
            ).fetchone()
            self.assertEqual(tuple(preserved), (1, 1, 1, None))
            migrated.close()

    def test_v12_online_backup_migrates_to_v15_without_rewriting_suite(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.sqlite3"
            with ComparisonStore(source) as store:
                seed_worker_fixture(store)
                suite_id = store.create_suite(
                    worker_suite_payload(),
                    created_by="migration-test",
                )
                plan = store.prepare(suite_id)
            raw = sqlite3.connect(source)
            for table, names in (
                (
                    "comparison_suites",
                    (
                        "byte_quota_status",
                        "byte_quota_exceeded",
                        "accounting_status",
                        "symlink_policy_status",
                        "policy_violation_code",
                        "failure_domain",
                        "failure_code",
                        "resource_policy_label",
                    ),
                ),
                (
                    "comparison_resource_samples",
                    (
                        "byte_quota_status",
                        "byte_quota_exceeded",
                        "accounting_status",
                        "symlink_policy_status",
                        "policy_violation_code",
                        "failure_domain",
                        "failure_code",
                        "symlink_observations_json",
                    ),
                ),
                (
                    "comparison_execution_attempts",
                    (
                        "process_reap_status",
                        "process_reaped_at",
                        "process_return_code",
                    ),
                ),
            ):
                for name in names:
                    raw.execute(
                        f"ALTER TABLE {table} DROP COLUMN {name}"
                    )
            raw.execute("PRAGMA user_version=12")
            raw.commit()
            backup_path = root / "snapshot.sqlite3"
            backup = sqlite3.connect(backup_path)
            raw.backup(backup)
            backup.close()
            raw.close()
            migrated = connect(backup_path)
            self.assertEqual(
                migrated.execute("PRAGMA user_version").fetchone()[0],
                15,
            )
            suite = migrated.execute(
                """
                SELECT status, plan_fingerprint, consumed_inference_starts,
                       failure_domain, byte_quota_exceeded
                FROM comparison_suites WHERE suite_id=?
                """,
                (suite_id,),
            ).fetchone()
            self.assertEqual(
                tuple(suite),
                ("prepared", plan["plan_fingerprint"], 0, None, None),
            )
            self.assertEqual(
                migrated.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )
            self.assertEqual(
                migrated.execute("PRAGMA foreign_key_check").fetchall(),
                [],
            )
            migrated.close()

    def test_v13_online_backup_migrates_to_v15_without_rewriting_plan(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.sqlite3"
            with ComparisonStore(source) as store:
                seed_worker_fixture(store)
                suite_id = store.create_suite(
                    worker_suite_payload(),
                    created_by="migration-test",
                )
                with store.connection:
                    store.connection.execute(
                        """
                        UPDATE comparison_suites
                        SET arm_failure_policy=NULL
                        WHERE suite_id=?
                        """,
                        (suite_id,),
                    )
                plan = store.prepare(suite_id)
                self.assertEqual(plan["schema_version"], "2.1")
            raw = sqlite3.connect(source)
            raw.execute(
                "ALTER TABLE comparison_suites DROP COLUMN arm_failure_policy"
            )
            raw.execute("PRAGMA user_version=13")
            raw.commit()
            backup_path = root / "snapshot.sqlite3"
            backup = sqlite3.connect(backup_path)
            raw.backup(backup)
            backup.close()
            raw.close()
            migrated = connect(backup_path)
            self.assertEqual(
                migrated.execute("PRAGMA user_version").fetchone()[0],
                15,
            )
            suite = migrated.execute(
                """
                SELECT status, plan_fingerprint, consumed_inference_starts,
                       arm_failure_policy
                FROM comparison_suites WHERE suite_id=?
                """,
                (suite_id,),
            ).fetchone()
            self.assertEqual(
                tuple(suite),
                ("prepared", plan["plan_fingerprint"], 0, None),
            )
            with ComparisonStore(backup_path) as store:
                recomputed = store.plan_payload(suite_id)
            self.assertEqual(
                canonical_sha256(recomputed),
                plan["plan_fingerprint"],
            )
            self.assertEqual(
                migrated.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )
            self.assertEqual(
                migrated.execute("PRAGMA foreign_key_check").fetchall(),
                [],
            )
            migrated.close()


class ComparisonWorkerHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name).resolve()
        self.database = self.workspace / "results.sqlite3"
        self.fake = (
            Path(__file__).resolve().parent / "fixtures" / "fake_app_server.py"
        )
        self.auth = self.workspace / "synthetic" / "auth.json"
        self.auth.parent.mkdir()
        self.auth.write_text('{"synthetic":true}\n', encoding="utf-8")
        self.old_auth = os.environ.get("SGLAB_CODEX_AUTH_SOURCE")
        self.old_launcher = os.environ.get(
            "SGLAB_COMPARISON_CODEX_LAUNCHER_JSON"
        )
        os.environ["SGLAB_CODEX_AUTH_SOURCE"] = str(self.auth)
        os.environ["SGLAB_COMPARISON_CODEX_LAUNCHER_JSON"] = json.dumps(
            [
                sys.executable,
                str(self.fake),
                "--fake-mode=director-screen-timeout-second",
            ]
        )
        with ComparisonStore(self.database) as store:
            seed_worker_fixture(store)
        self.server = create_server(
            self.workspace, "127.0.0.1", 0, token="comparison-token"
        )
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        if self.old_auth is None:
            os.environ.pop("SGLAB_CODEX_AUTH_SOURCE", None)
        else:
            os.environ["SGLAB_CODEX_AUTH_SOURCE"] = self.old_auth
        if self.old_launcher is None:
            os.environ.pop("SGLAB_COMPARISON_CODEX_LAUNCHER_JSON", None)
        else:
            os.environ[
                "SGLAB_COMPARISON_CODEX_LAUNCHER_JSON"
            ] = self.old_launcher
        for process in list(self.server.comparison_runners.values()):
            if process.poll() is None:
                process.wait(timeout=5)
        self.temporary.cleanup()

    def _request(
        self, method: str, path: str, payload: dict | None = None, *, token: bool = True
    ) -> tuple[int, dict]:
        connection = HTTPConnection(self.host, self.port, timeout=5)
        body = json.dumps(payload or {}) if method == "POST" else None
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer comparison-token"
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        raw = response.read()
        connection.close()
        return response.status, json.loads(raw)

    def test_http_control_plane_launch_progress_fail_closed_and_ratings(self) -> None:
        arms = worker_suite_payload(three_arms=True)["arms"]
        arms.append(
            {
                "display_name": "Blocked after timeout",
                "model": "gpt-5.6-luna",
                "reasoning_effort": "xhigh",
                "context_mode": "stateless_turns",
            }
        )
        payload = worker_suite_payload(three_arms=True)
        payload["arms"] = arms
        payload["maximum_inference_starts"] = 4
        status, created = self._request("POST", "/api/comparisons", payload)
        self.assertEqual(status, 201, created)
        suite_id = created["suite_id"]
        status, prepared = self._request(
            "POST", f"/api/comparisons/{suite_id}/prepare", {}
        )
        self.assertEqual(status, 200, prepared)
        status, _ = self._request(
            "POST",
            f"/api/comparisons/{suite_id}/authorize",
            {"plan_fingerprint": prepared["plan_fingerprint"]},
        )
        self.assertEqual(status, 200)
        status, denied = self._request(
            "POST",
            f"/api/comparisons/{suite_id}/start",
            {},
            token=False,
        )
        self.assertEqual(status, 401, denied)
        status, started = self._request(
            "POST", f"/api/comparisons/{suite_id}/start", {}
        )
        self.assertEqual(status, 202, started)
        status, duplicate = self._request(
            "POST", f"/api/comparisons/{suite_id}/start", {}
        )
        self.assertEqual(status, 409, duplicate)
        deadline = monotonic() + 10
        progress: dict = {}
        while monotonic() < deadline:
            status, progress = self._request(
                "GET", f"/api/comparisons/{suite_id}/progress"
            )
            self.assertEqual(status, 200, progress)
            if progress["suite"]["status"] in {"failed", "completed", "stopped"}:
                break
            sleep(0.05)
        self.assertEqual(progress["suite"]["status"], "failed")
        self.assertEqual(progress["suite"]["consumed_inference_starts"], 3)
        states = [arm["lifecycle_state"] for arm in progress["arms"]]
        self.assertEqual(
            states,
            ["completed", "completed", "timed_out", "blocked"],
        )
        self.assertEqual(len(progress["turns"]), 3)
        deadline = monotonic() + 5
        while (
            monotonic() < deadline
            and suite_id in self.server.comparison_runners
        ):
            sleep(0.02)
        self.assertNotIn(suite_id, self.server.comparison_runners)
        with ComparisonStore(self.database) as store:
            attempt = store.connection.execute(
                """
                SELECT process_reap_status, process_reaped_at,
                       process_return_code
                FROM comparison_execution_attempts
                WHERE suite_id=? ORDER BY started_at DESC LIMIT 1
                """,
                (suite_id,),
            ).fetchone()
            self.assertEqual(attempt["process_reap_status"], "reaped")
            self.assertIsNotNone(attempt["process_reaped_at"])
            self.assertEqual(attempt["process_return_code"], 1)
        valid_turns = [
            turn
            for turn in progress["turns"]
            if turn["lifecycle_status"] == "completed"
        ]
        self.assertEqual(len(valid_turns), 2)
        rating = {
            "comparison_turn_id": valid_turns[0]["comparison_turn_id"],
            "scientific_usefulness": 4,
            "clarity": 4,
            "novelty": 3,
            "would_execute": "uncertain",
            "comment": "deterministic replay rating",
        }
        status, _ = self._request(
            "POST", f"/api/comparisons/{suite_id}/ratings", rating
        )
        self.assertEqual(status, 200)
        pairwise = {
            "left_turn_id": valid_turns[0]["comparison_turn_id"],
            "right_turn_id": valid_turns[1]["comparison_turn_id"],
            "preferred": "equal",
            "comment": "blind deterministic draw",
            "blind_order_seed": 42,
        }
        status, _ = self._request(
            "POST",
            f"/api/comparisons/{suite_id}/pairwise-ratings",
            pairwise,
        )
        self.assertEqual(status, 200)
        status, turns = self._request(
            "GET", f"/api/comparisons/{suite_id}/turns"
        )
        self.assertEqual(status, 200)
        self.assertEqual(len(turns["turns"]), 3)
        with ComparisonStore(self.database) as store:
            self.assertEqual(
                store.connection.execute(
                    "SELECT count(*) FROM research_lanes"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                store.connection.execute(
                    "SELECT count(*) FROM pairwise_ratings WHERE suite_id=?",
                    (suite_id,),
                ).fetchone()[0],
                1,
            )

    def test_successful_wrapper_worker_is_reaped_while_dashboard_runs(
        self,
    ) -> None:
        os.environ["SGLAB_COMPARISON_CODEX_LAUNCHER_JSON"] = json.dumps(
            [
                sys.executable,
                str(self.fake),
                "--fake-mode=director-screen-wrappers",
            ]
        )
        status, created = self._request(
            "POST", "/api/comparisons", worker_suite_payload()
        )
        self.assertEqual(status, 201)
        suite_id = created["suite_id"]
        _, prepared = self._request(
            "POST", f"/api/comparisons/{suite_id}/prepare", {}
        )
        self._request(
            "POST",
            f"/api/comparisons/{suite_id}/authorize",
            {"plan_fingerprint": prepared["plan_fingerprint"]},
        )
        status, started = self._request(
            "POST", f"/api/comparisons/{suite_id}/start", {}
        )
        self.assertEqual(status, 202, started)
        deadline = monotonic() + 10
        progress: dict = {}
        while monotonic() < deadline:
            _, progress = self._request(
                "GET", f"/api/comparisons/{suite_id}/progress"
            )
            if (
                progress["suite"]["status"] == "completed"
                and suite_id not in self.server.comparison_runners
            ):
                break
            sleep(0.05)
        self.assertEqual(progress["suite"]["status"], "completed")
        self.assertNotIn(suite_id, self.server.comparison_runners)
        self.assertFalse(process_is_live(int(started["pid"])))
        with ComparisonStore(self.database) as store:
            attempt = store.connection.execute(
                """
                SELECT process_reap_status, process_return_code
                FROM comparison_execution_attempts
                WHERE suite_id=? ORDER BY started_at DESC LIMIT 1
                """,
                (suite_id,),
            ).fetchone()
            self.assertEqual(tuple(attempt), ("reaped", 0))

    def test_pre_inference_policy_failure_is_reaped_and_not_restartable(
        self,
    ) -> None:
        os.environ["SGLAB_COMPARISON_CODEX_LAUNCHER_JSON"] = json.dumps(
            [
                sys.executable,
                str(self.fake),
                "--fake-mode=director-screen-wrapper-unexpected",
            ]
        )
        status, created = self._request(
            "POST", "/api/comparisons", worker_suite_payload()
        )
        self.assertEqual(status, 201)
        suite_id = created["suite_id"]
        _, prepared = self._request(
            "POST", f"/api/comparisons/{suite_id}/prepare", {}
        )
        self._request(
            "POST",
            f"/api/comparisons/{suite_id}/authorize",
            {"plan_fingerprint": prepared["plan_fingerprint"]},
        )
        status, _ = self._request(
            "POST", f"/api/comparisons/{suite_id}/start", {}
        )
        self.assertEqual(status, 202)
        deadline = monotonic() + 10
        progress: dict = {}
        while monotonic() < deadline:
            _, progress = self._request(
                "GET", f"/api/comparisons/{suite_id}/progress"
            )
            if (
                progress["suite"]["status"] == "failed"
                and suite_id not in self.server.comparison_runners
            ):
                break
            sleep(0.05)
        self.assertEqual(progress["suite"]["status"], "failed")
        self.assertEqual(
            progress["suite"]["failure_domain"], "filesystem_policy"
        )
        self.assertEqual(
            progress["suite"]["consumed_inference_starts"], 0
        )
        self.assertNotIn(suite_id, self.server.comparison_runners)
        status, duplicate = self._request(
            "POST", f"/api/comparisons/{suite_id}/start", {}
        )
        self.assertEqual(status, 409, duplicate)

    def test_stop_endpoint_persists_request_without_pid_input(self) -> None:
        payload = worker_suite_payload()
        status, created = self._request("POST", "/api/comparisons", payload)
        self.assertEqual(status, 201)
        suite_id = created["suite_id"]
        _, prepared = self._request(
            "POST", f"/api/comparisons/{suite_id}/prepare", {}
        )
        self._request(
            "POST",
            f"/api/comparisons/{suite_id}/authorize",
            {"plan_fingerprint": prepared["plan_fingerprint"]},
        )
        status, body = self._request(
            "POST",
            f"/api/comparisons/{suite_id}/stop",
            {"pid": 1},
        )
        self.assertEqual(status, 400, body)
        status, body = self._request(
            "POST", f"/api/comparisons/{suite_id}/stop", {}
        )
        self.assertEqual(status, 200, body)
        self.assertEqual(body["state"], "stopped")

    def test_active_stop_interrupts_drains_and_records_forced_shutdown(self) -> None:
        os.environ["SGLAB_COMPARISON_CODEX_LAUNCHER_JSON"] = json.dumps(
            [
                sys.executable,
                str(self.fake),
                "--fake-mode=director-screen-forced-shutdown",
            ]
        )
        payload = worker_suite_payload()
        payload["arms"] = [payload["arms"][0]]
        payload["maximum_inference_starts"] = 1
        status, created = self._request("POST", "/api/comparisons", payload)
        self.assertEqual(status, 201)
        suite_id = created["suite_id"]
        _, prepared = self._request(
            "POST", f"/api/comparisons/{suite_id}/prepare", {}
        )
        self._request(
            "POST",
            f"/api/comparisons/{suite_id}/authorize",
            {"plan_fingerprint": prepared["plan_fingerprint"]},
        )
        status, started = self._request(
            "POST", f"/api/comparisons/{suite_id}/start", {}
        )
        self.assertEqual(status, 202, started)
        deadline = monotonic() + 5
        while monotonic() < deadline:
            _, progress = self._request(
                "GET", f"/api/comparisons/{suite_id}/progress"
            )
            if progress["suite"]["consumed_inference_starts"] == 1:
                break
            sleep(0.02)
        self.assertEqual(progress["suite"]["consumed_inference_starts"], 1)
        old_process = self.server.comparison_runners[suite_id]
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.server = create_server(
            self.workspace, "127.0.0.1", 0, token="comparison-token"
        )
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host, self.port = self.server.server_address
        status, restarted_progress = self._request(
            "GET", f"/api/comparisons/{suite_id}/progress"
        )
        self.assertEqual(status, 200)
        self.assertIsNotNone(restarted_progress["worker"]["lease"])
        status, duplicate = self._request(
            "POST", f"/api/comparisons/{suite_id}/start", {}
        )
        self.assertEqual(status, 409, duplicate)
        status, stopped = self._request(
            "POST", f"/api/comparisons/{suite_id}/stop", {}
        )
        self.assertEqual(status, 200, stopped)
        deadline = monotonic() + 10
        while monotonic() < deadline:
            _, progress = self._request(
                "GET", f"/api/comparisons/{suite_id}/progress"
            )
            if progress["suite"]["status"] == "stopped":
                break
            sleep(0.05)
        self.assertEqual(progress["suite"]["status"], "stopped")
        stop = progress["worker"]["stop_request"]
        self.assertIn(stop["state"], {"stopped", "forced_termination"})
        if stop["state"] == "forced_termination":
            self.assertEqual(stop["forced_termination"], 1)
        self.assertEqual(progress["arms"][0]["lifecycle_state"], "stopped")
        old_process.wait(timeout=5)
        self.assertFalse(process_is_live(int(started["pid"])))
