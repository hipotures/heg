import json
import sqlite3
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

from sglab.comparisons import (
    INDEPENDENT_INVALID_CONTINUE_POLICY,
    ComparisonStore,
    ModelCatalog,
    calculate_cost,
    import_m6_context_report,
    pareto_frontier,
    run_replay_dry_run,
)
from sglab.db import SCHEMA_VERSION, connect
from sglab.research.context import DEFAULT_DIRECTOR_CONTEXT_MODE
from sglab.web import create_server


HASH = "a" * 64


def seed_fixture(store: ComparisonStore, fixture_id: str = "fixture") -> None:
    store.seed_fixture(
        fixture_id=fixture_id,
        display_name="Test fixture",
        fixture_type="custom_director_state_json",
        source_artifact_reference="inline",
        director_state={
            "schema_version": "2.0",
            "source_snapshot_id": "snapshot-test",
        },
        metadata={
            "estimated_client_owned_tokens": 100,
            "hashes": {
                key: HASH
                for key in (
                    "prompt",
                    "output_schema",
                    "applicable_action_space",
                    "evidence_registry",
                    "advisory_registry",
                    "executable_registry",
                    "base_instructions",
                    "campaign_budget",
                )
            },
        },
    )


def suite_payload(**changes):
    value = {
        "name": "Controlled test",
        "description": "Deterministic comparison",
        "fixture_id": "fixture",
        "arms": [
            {
                "display_name": "Stateless",
                "model": "gpt-5.6-luna",
                "reasoning_effort": "xhigh",
                "context_mode": "stateless_turns",
                "repetitions": 1,
            },
            {
                "display_name": "Persistent",
                "model": "gpt-5.6-sol",
                "reasoning_effort": "high",
                "context_mode": "persistent_thread",
                "repetitions": 1,
            },
        ],
        "timeout_seconds": 300,
        "ordering": "fixed",
        "ordering_seed": 0,
        "measurement_only": True,
        "execute_decisions": False,
        "fail_closed": True,
        "maximum_inference_starts": 2,
        "maximum_client_owned_tokens_per_turn": 12000,
        "notes": "",
    }
    value.update(changes)
    return value


class ComparisonDatabaseTests(unittest.TestCase):
    def test_schema_v14_tables_foreign_keys_and_integrity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "results.sqlite3"
            connection = connect(database)
            self.assertEqual(SCHEMA_VERSION, 14)
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 14)
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            for table in (
                "comparison_suites",
                "comparison_arms",
                "comparison_turns",
                "manual_ratings",
                "pairwise_ratings",
                "model_cost_profiles",
                "comparison_authorizations",
                "comparison_execution_attempts",
                "comparison_worker_leases",
                "comparison_stop_requests",
                "comparison_inference_reservations",
                "comparison_arm_transitions",
                "comparison_resource_samples",
            ):
                self.assertIn(table, tables)
            self.assertTrue(
                connection.execute("PRAGMA foreign_key_list(comparison_turns)").fetchall()
            )
            self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            connection.close()

    def test_cost_profile_is_snapshotted_for_historical_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with ComparisonStore(Path(directory) / "results.sqlite3") as store:
                seed_fixture(store)
                first = store.create_cost_profile(
                    {
                        "model": "gpt-5.6-luna",
                        "reasoning_effort": "xhigh",
                        "display_name": "baseline",
                        "relative_cost_multiplier": 1.0,
                        "api_input_per_million": None,
                        "api_cached_input_per_million": None,
                        "api_output_per_million": None,
                        "currency": None,
                        "source_label": "local relative baseline",
                        "effective_from": "2026-01-01T00:00:00Z",
                        "enabled": True,
                    }
                )
                suite_id = store.create_suite(
                    suite_payload(
                        arms=[suite_payload()["arms"][0]],
                        maximum_inference_starts=1,
                    )
                )
                arm_id = store.connection.execute(
                    "SELECT arm_id FROM comparison_arms WHERE suite_id=?", (suite_id,)
                ).fetchone()[0]
                store.record_turn(
                    suite_id,
                    arm_id,
                    lifecycle_status="completed",
                    usage={
                        "input_tokens": 80,
                        "cached_input_tokens": 20,
                        "output_tokens": 20,
                        "reasoning_output_tokens": 10,
                        "server_reported_total_tokens": 100,
                    },
                    decision={"actions": []},
                    schema_valid=True,
                    semantic_valid=True,
                )
                store.create_cost_profile(
                    {
                        "model": "gpt-5.6-luna",
                        "reasoning_effort": "xhigh",
                        "display_name": "later edit",
                        "relative_cost_multiplier": 7.0,
                        "api_input_per_million": None,
                        "api_cached_input_per_million": None,
                        "api_output_per_million": None,
                        "currency": None,
                        "source_label": "later profile",
                        "effective_from": "2027-01-01T00:00:00Z",
                        "enabled": True,
                    }
                )
                turn = store.suite_detail(suite_id)["turns"][0]
                self.assertEqual(turn["cost_profile_id"], first)
                self.assertEqual(turn["cost"]["relative_cost_units"], 100.0)

    def test_historical_m6_import_is_exact_and_read_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "results.sqlite3"
            suite_id = import_m6_context_report(
                database,
                root / "docs/reports/M6_REDUCED_CONTEXT_SCREEN_RERUN.json",
            )
            with ComparisonStore(database) as store:
                detail = store.suite_detail(suite_id)
                self.assertTrue(detail["suite"]["read_only"])
                self.assertTrue(detail["suite"]["runtime_executed_elsewhere"])
                observed = [
                    (
                        turn["display_name"],
                        turn["input_tokens"],
                        turn["server_reported_total_tokens"],
                        turn["selected_action"],
                        turn["semantic_valid"],
                    )
                    for turn in detail["turns"]
                ]
                self.assertEqual(
                    observed,
                    [
                        ("S2", 9591, 15806, "request_diagnostic", 1),
                        ("P1", 4405, 6498, "start_lane", 1),
                        ("P2", 12754, 16999, "schedule_verification", 1),
                    ],
                )
                with self.assertRaisesRegex(ValueError, "read-only"):
                    store.add_manual_rating(
                        suite_id,
                        {
                            "comparison_turn_id": detail["turns"][0][
                                "comparison_turn_id"
                            ],
                            "scientific_usefulness": 5,
                            "clarity": 5,
                            "novelty": 5,
                            "would_execute": "yes",
                            "comment": "",
                        },
                    )


class ComparisonPlanningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.store = ComparisonStore(Path(self.temp.name) / "results.sqlite3")
        seed_fixture(self.store)

    def tearDown(self) -> None:
        self.store.close()
        self.temp.cleanup()

    def test_catalog_supports_configured_models_and_rejects_unknown(self) -> None:
        catalog = ModelCatalog.load()
        catalog.validate("gpt-5.6-luna", "medium")
        catalog.validate("gpt-5.6-sol", "xhigh")
        with self.assertRaisesRegex(ValueError, "unsupported model"):
            catalog.validate("arbitrary", "xhigh")
        with self.assertRaisesRegex(ValueError, "combination"):
            catalog.validate("gpt-5.6-luna", "ultra")

    def test_randomized_order_is_reproducible_and_fingerprint_is_stable(self) -> None:
        payload = suite_payload(ordering="randomized", ordering_seed=42)
        first = self.store.create_suite(payload)
        second = self.store.create_suite(payload)
        first_order = [
            row["display_name"]
            for row in self.store.connection.execute(
                "SELECT display_name FROM comparison_arms WHERE suite_id=? "
                "ORDER BY effective_order",
                (first,),
            )
        ]
        second_order = [
            row["display_name"]
            for row in self.store.connection.execute(
                "SELECT display_name FROM comparison_arms WHERE suite_id=? "
                "ORDER BY effective_order",
                (second,),
            )
        ]
        self.assertEqual(first_order, second_order)
        first_plan = self.store.prepare(first)
        second_plan = self.store.prepare(second)
        self.assertTrue(first_plan["fixture_equality"]["all_equal"])
        self.assertNotEqual(
            first_plan["plan_fingerprint"], second_plan["plan_fingerprint"]
        )

    def test_authorization_is_exact_and_plan_mutation_invalidates_start(self) -> None:
        suite_id = self.store.create_suite(suite_payload())
        plan = self.store.prepare(suite_id)
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            self.store.authorize(suite_id, "0" * 64)
        self.store.authorize(suite_id, plan["plan_fingerprint"])
        with self.store.connection:
            self.store.connection.execute(
                "UPDATE comparison_arms SET reasoning_effort='medium' "
                "WHERE suite_id=? AND planned_order=0",
                (suite_id,),
            )
        with self.assertRaisesRegex(ValueError, "changed"):
            self.store.start(suite_id, auth_available=True)
        suite = self.store.suite_detail(suite_id)["suite"]
        self.assertEqual(suite["authorization_status"], "invalidated")

    def test_resource_quota_is_fingerprinted_and_legacy_maps_only_preserved(self) -> None:
        legacy = self.store.create_suite(
            suite_payload(maximum_artifact_directory_bytes=32 * 1024 * 1024)
        )
        legacy_row = self.store._suite_row(legacy)
        self.assertEqual(
            legacy_row["max_preserved_artifact_bytes"], 32 * 1024 * 1024
        )
        self.assertEqual(
            legacy_row["max_runtime_scratch_bytes"], 512 * 1024 * 1024
        )
        suite_id = self.store.create_suite(suite_payload())
        plan = self.store.prepare(suite_id)
        self.assertEqual(plan["resource_accounting_version"], 2)
        self.assertIn("max_runtime_scratch_bytes", plan)
        self.store.authorize(suite_id, plan["plan_fingerprint"])
        with self.store.connection:
            self.store.connection.execute(
                """
                UPDATE comparison_suites
                SET max_runtime_scratch_bytes=max_runtime_scratch_bytes+1
                WHERE suite_id=?
                """,
                (suite_id,),
            )
        with self.assertRaisesRegex(ValueError, "changed"):
            self.store.start(suite_id, auth_available=True)
        self.assertEqual(
            self.store._suite_row(suite_id)["authorization_status"],
            "invalidated",
        )

    def test_independent_invalid_arm_policy_is_persisted_and_fingerprinted(
        self,
    ) -> None:
        suite_id = self.store.create_suite(suite_payload())
        plan = self.store.prepare(suite_id)
        self.assertEqual(plan["schema_version"], "2.2")
        self.assertEqual(
            plan["arm_failure_policy"],
            INDEPENDENT_INVALID_CONTINUE_POLICY,
        )
        self.assertEqual(
            plan["arm_failure_contract"][
                "schema_or_semantic_invalid_independent"
            ],
            "continue",
        )
        self.assertEqual(
            self.store._suite_row(suite_id)["arm_failure_policy"],
            INDEPENDENT_INVALID_CONTINUE_POLICY,
        )
        self.store.authorize(suite_id, plan["plan_fingerprint"])
        with self.store.connection:
            self.store.connection.execute(
                """
                UPDATE comparison_suites
                SET arm_failure_policy=NULL
                WHERE suite_id=?
                """,
                (suite_id,),
            )
        with self.assertRaisesRegex(ValueError, "changed"):
            self.store.start(suite_id, auth_available=True)

    def test_effective_model_effort_contract_aborts_on_mismatch(self) -> None:
        suite_id = self.store.create_suite(
            suite_payload(
                arms=[suite_payload()["arms"][0]],
                maximum_inference_starts=1,
            )
        )
        arm_id = self.store.connection.execute(
            "SELECT arm_id FROM comparison_arms WHERE suite_id=?", (suite_id,)
        ).fetchone()[0]
        self.assertFalse(
            self.store.record_model_contract(
                arm_id,
                effective_model="gpt-5.6-sol",
                effective_reasoning_effort="xhigh",
                effective_context_mode="stateless_turns",
            )
        )
        row = self.store.connection.execute(
            "SELECT * FROM comparison_arms WHERE arm_id=?", (arm_id,)
        ).fetchone()
        self.assertEqual(row["expected_model"], "gpt-5.6-luna")
        self.assertEqual(row["effective_model"], "gpt-5.6-sol")
        self.assertEqual(row["model_contract_matched"], 0)
        self.assertEqual(row["status"], "failed")

    def test_no_start_without_authorization_and_inference_cap(self) -> None:
        suite_id = self.store.create_suite(suite_payload())
        with self.assertRaisesRegex(ValueError, "not authorized"):
            self.store.start(suite_id, auth_available=True)
        arms = list(
            self.store.connection.execute(
                "SELECT arm_id FROM comparison_arms WHERE suite_id=? "
                "ORDER BY effective_order",
                (suite_id,),
            )
        )
        self.store.record_turn(
            suite_id, arms[0][0], lifecycle_status="completed"
        )
        self.store.record_turn(
            suite_id, arms[1][0], lifecycle_status="completed"
        )
        with self.assertRaisesRegex(ValueError, "authorized turn plan"):
            self.store.record_turn(
                suite_id, arms[1][0], lifecycle_status="completed"
            )

    def test_fail_closed_blocks_later_arm(self) -> None:
        suite_id = self.store.create_suite(suite_payload())
        arms = list(
            self.store.connection.execute(
                "SELECT arm_id FROM comparison_arms WHERE suite_id=? "
                "ORDER BY effective_order",
                (suite_id,),
            )
        )
        self.store.record_turn(suite_id, arms[0][0], lifecycle_status="timed_out")
        with self.assertRaisesRegex(ValueError, "fail-closed"):
            self.store.record_turn(
                suite_id, arms[1][0], lifecycle_status="completed"
            )


class ComparisonUsageAndQualityTests(unittest.TestCase):
    def test_usage_arithmetic_does_not_double_count_subsets(self) -> None:
        cost = calculate_cost(
            input_tokens=100,
            cached_input_tokens=40,
            output_tokens=30,
            server_reported_total_tokens=130,
            relative_multiplier=2.0,
            api_input_per_million=10.0,
            api_cached_input_per_million=2.0,
            api_output_per_million=20.0,
            currency="USD",
        )
        self.assertEqual(cost.relative_cost_units, 260.0)
        self.assertAlmostEqual(cost.api_equivalent_input_cost, 0.00068)
        self.assertAlmostEqual(cost.api_equivalent_output_cost, 0.0006)
        self.assertAlmostEqual(cost.api_equivalent_total_cost, 0.00128)
        missing = calculate_cost(
            input_tokens=None,
            cached_input_tokens=None,
            output_tokens=None,
            server_reported_total_tokens=None,
            relative_multiplier=1.0,
            api_input_per_million=None,
            api_cached_input_per_million=None,
            api_output_per_million=None,
            currency=None,
        )
        self.assertIsNone(missing.relative_cost_units)
        self.assertIsNone(missing.api_equivalent_total_cost)

    def test_reasoning_and_cached_subset_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with ComparisonStore(Path(directory) / "results.sqlite3") as store:
                seed_fixture(store)
                suite_id = store.create_suite(
                    suite_payload(
                        arms=[suite_payload()["arms"][0]],
                        maximum_inference_starts=1,
                    )
                )
                arm = store.connection.execute(
                    "SELECT arm_id FROM comparison_arms WHERE suite_id=?",
                    (suite_id,),
                ).fetchone()[0]
                with self.assertRaisesRegex(ValueError, "cached input"):
                    store.record_turn(
                        suite_id,
                        arm,
                        lifecycle_status="completed",
                        usage={"input_tokens": 1, "cached_input_tokens": 2},
                    )
                with self.assertRaisesRegex(ValueError, "reasoning output"):
                    store.record_turn(
                        suite_id,
                        arm,
                        lifecycle_status="completed",
                        usage={"output_tokens": 1, "reasoning_output_tokens": 2},
                    )

    def test_manual_and_blind_ratings_are_append_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with ComparisonStore(Path(directory) / "results.sqlite3") as store:
                seed_fixture(store)
                suite_id = store.create_suite(suite_payload())
                arms = list(
                    store.connection.execute(
                        "SELECT arm_id FROM comparison_arms WHERE suite_id=? "
                        "ORDER BY effective_order",
                        (suite_id,),
                    )
                )
                decision = {"actions": []}
                turns = [
                    store.record_turn(
                        suite_id,
                        row[0],
                        lifecycle_status="completed",
                        decision=decision,
                        schema_valid=True,
                        semantic_valid=True,
                    )
                    for row in arms
                ]
                for usefulness in (3, 5):
                    store.add_manual_rating(
                        suite_id,
                        {
                            "comparison_turn_id": turns[0],
                            "scientific_usefulness": usefulness,
                            "clarity": 4,
                            "novelty": 3,
                            "would_execute": "uncertain",
                            "comment": "",
                        },
                    )
                store.add_pairwise_rating(
                    suite_id,
                    {
                        "left_turn_id": turns[0],
                        "right_turn_id": turns[1],
                        "preferred": "left",
                        "comment": "",
                        "blind_order_seed": 7,
                    },
                )
                self.assertEqual(
                    store.connection.execute(
                        "SELECT count(*) FROM manual_ratings"
                    ).fetchone()[0],
                    2,
                )
                first = store.suite_detail(suite_id, blind=True)
                second = store.suite_detail(suite_id, blind=True)
                self.assertEqual(
                    [turn["comparison_turn_id"] for turn in first["turns"]],
                    [turn["comparison_turn_id"] for turn in second["turns"]],
                )
                self.assertNotIn("model", first["turns"][0])
                self.assertIsNotNone(first["blind_order_seed"])

    def test_pareto_requires_both_cost_and_quality(self) -> None:
        self.assertEqual(
            pareto_frontier(
                [
                    {"id": "cheap", "cost": 1, "quality": 4},
                    {"id": "dominated", "cost": 2, "quality": 3},
                    {"id": "unknown", "cost": 0.5, "quality": None},
                ]
            ),
            {"cheap"},
        )

    def test_replay_dry_run_has_zero_runtime_side_effects(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            report = run_replay_dry_run(Path(directory) / "results.sqlite3")
            self.assertTrue(report["ok"])
            self.assertEqual(report["model_inferences"], 0)
            self.assertEqual(report["auth_access"], 0)
            self.assertEqual(report["search_batches"], 0)
            self.assertTrue(report["measurement_only"])
            self.assertTrue(report["missing_usage_is_null"])

    def test_stateless_is_the_production_default(self) -> None:
        self.assertEqual(DEFAULT_DIRECTOR_CONTEXT_MODE.value, "stateless_turns")


class ComparisonHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp.name)
        with ComparisonStore(self.workspace / "results.sqlite3") as store:
            seed_fixture(store)
        self.server = create_server(
            self.workspace, "127.0.0.1", 0, token="secret"
        )
        self.assertEqual(self.server.server_address[0], "127.0.0.1")
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.connection = HTTPConnection(*self.server.server_address, timeout=3)

    def tearDown(self) -> None:
        self.connection.close()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.assertFalse(self.thread.is_alive())
        self.temp.cleanup()

    def request(self, method, path, body=None, *, authorized=True):
        headers = {"Content-Type": "application/json"}
        if authorized:
            headers["Authorization"] = "Bearer secret"
        self.connection.request(
            method,
            path,
            body=json.dumps(body) if body is not None else None,
            headers=headers,
        )
        response = self.connection.getresponse()
        payload = response.read()
        return response.status, payload

    def test_pages_render_and_bearer_protects_api(self) -> None:
        for path in (
            "/comparisons",
            "/comparisons/new",
            "/model-cost-profiles",
        ):
            status, body = self.request("GET", path)
            self.assertEqual(status, 200)
            self.assertIn(b"Comparisons", body)
            self.assertIn(b"sessionStorage.setItem('sglab-dashboard-token'", body)
            self.assertIn(b"history.replaceState", body)
        status, _ = self.request("GET", "/api/comparisons", authorized=False)
        self.assertEqual(status, 401)

    def test_create_prepare_authorize_and_refuse_start_without_server_auth(self) -> None:
        status, body = self.request("POST", "/api/comparisons", suite_payload())
        self.assertEqual(status, 201, body)
        suite_id = json.loads(body)["suite_id"]
        status, body = self.request(
            "POST", f"/api/comparisons/{suite_id}/prepare", {}
        )
        self.assertEqual(status, 200, body)
        fingerprint = json.loads(body)["plan_fingerprint"]
        status, body = self.request(
            "POST",
            f"/api/comparisons/{suite_id}/authorize",
            {"plan_fingerprint": fingerprint},
        )
        self.assertEqual(status, 200, body)
        status, body = self.request(
            "POST", f"/api/comparisons/{suite_id}/start", {}
        )
        self.assertEqual(status, 409)
        self.assertIn(b"failed preflight", body)

    def test_detail_page_separates_policy_from_byte_quota(self) -> None:
        status, body = self.request(
            "POST", "/api/comparisons", suite_payload()
        )
        self.assertEqual(status, 201, body)
        suite_id = json.loads(body)["suite_id"]
        status, body = self.request("GET", f"/comparisons/{suite_id}")
        self.assertEqual(status, 200, body)
        self.assertIn(b"Filesystem policy violation", body)
        self.assertIn(b"Actual byte quota exceeded", body)
        self.assertIn(b"Runtime scratch exceeded", body)
        self.assertIn(b"safeResourceLabel", body)

    def test_security_rejects_arbitrary_contracts_paths_and_shell_input(self) -> None:
        valid = suite_payload()
        valid["description"] = (
            "Compare reasoning effort on an identical bounded A4 Director "
            "decision using the authenticated M7 comparison worker. "
            "Measurement only; no returned action is executed."
        )
        status, _ = self.request("POST", "/api/comparisons", valid)
        self.assertEqual(status, 201)
        invalid = suite_payload()
        invalid["arms"][0]["model"] = "arbitrary-model"
        status, body = self.request("POST", "/api/comparisons", invalid)
        self.assertEqual(status, 400)
        self.assertIn(b"unsupported model", body)
        invalid = suite_payload()
        invalid["arms"][0]["reasoning_effort"] = "ultra"
        status, _ = self.request("POST", "/api/comparisons", invalid)
        self.assertEqual(status, 400)
        invalid = suite_payload(fixture_id="../../auth.json")
        status, _ = self.request("POST", "/api/comparisons", invalid)
        self.assertEqual(status, 400)
        invalid = suite_payload(name="$(touch unsafe)")
        status, _ = self.request("POST", "/api/comparisons", invalid)
        self.assertEqual(status, 400)
        invalid = suite_payload(auth_path="/home/user/.codex/auth.json")
        status, _ = self.request("POST", "/api/comparisons", invalid)
        self.assertEqual(status, 400)

    def test_cost_profile_rating_and_pairwise_endpoints(self) -> None:
        status, body = self.request(
            "POST",
            "/api/model-cost-profiles",
            {
                "model": "gpt-5.6-luna",
                "reasoning_effort": "xhigh",
                "display_name": "relative baseline",
                "relative_cost_multiplier": 1.0,
                "api_input_per_million": None,
                "api_cached_input_per_million": None,
                "api_output_per_million": None,
                "currency": None,
                "source_label": "user relative configuration",
                "effective_from": "2026-07-25T00:00:00Z",
                "enabled": True,
            },
        )
        self.assertEqual(status, 201, body)
        with ComparisonStore(self.workspace / "results.sqlite3") as store:
            suite_id = store.create_suite(suite_payload())
            arms = list(
                store.connection.execute(
                    "SELECT arm_id FROM comparison_arms WHERE suite_id=? "
                    "ORDER BY effective_order",
                    (suite_id,),
                )
            )
            turns = [
                store.record_turn(
                    suite_id,
                    row[0],
                    lifecycle_status="completed",
                    decision={"actions": []},
                    schema_valid=True,
                    semantic_valid=True,
                )
                for row in arms
            ]
        status, body = self.request(
            "POST",
            f"/api/comparisons/{suite_id}/ratings",
            {
                "comparison_turn_id": turns[0],
                "scientific_usefulness": 4,
                "clarity": 4,
                "novelty": 3,
                "would_execute": "uncertain",
                "comment": "",
            },
        )
        self.assertEqual(status, 200, body)
        status, body = self.request(
            "POST",
            f"/api/comparisons/{suite_id}/pairwise-ratings",
            {
                "left_turn_id": turns[0],
                "right_turn_id": turns[1],
                "preferred": "equal",
                "comment": "",
                "blind_order_seed": 5,
            },
        )
        self.assertEqual(status, 200, body)


if __name__ == "__main__":
    unittest.main()
