import json
import tempfile
import unittest
from pathlib import Path

from sglab.comparisons import ComparisonStore
from sglab.db import SCHEMA_VERSION, connect
from sglab.research.campaign import campaign_status
from sglab.ui_fixture import (
    DEFAULT_UI_FIXTURE_SEED,
    create_ui_fixture,
    inspect_ui_fixture,
)


class UIFixtureTests(unittest.TestCase):
    def test_same_seed_produces_identical_database_and_logical_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = create_ui_fixture(root / "first")
            second = create_ui_fixture(root / "second")
            self.assertEqual(first.fixture_sha256, second.fixture_sha256)
            self.assertEqual(
                (root / "first/results.sqlite3").read_bytes(),
                (root / "second/results.sqlite3").read_bytes(),
            )
            self.assertEqual(first.counts, second.counts)
            different = create_ui_fixture(root / "different", seed=17)
            self.assertNotEqual(first.fixture_sha256, different.fixture_sha256)

    def test_demo_marker_safe_replace_and_production_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            demo = root / "demo"
            first = create_ui_fixture(demo)
            marker = json.loads((demo / "workspace.json").read_text())
            self.assertEqual(marker["workspace_kind"], "ui_demo")
            self.assertTrue(marker["synthetic_data"])
            self.assertEqual(marker["fixture_version"], 1)
            self.assertEqual(marker["generated_by"], "deterministic_fixture")
            with self.assertRaisesRegex(ValueError, "--replace"):
                create_ui_fixture(demo)
            replaced = create_ui_fixture(demo, replace=True)
            self.assertEqual(first.fixture_sha256, replaced.fixture_sha256)

            production = root / "production"
            production.mkdir()
            (production / "workspace.json").write_text(
                json.dumps({"workspace_kind": "production"}),
                encoding="utf-8",
            )
            sentinel = production / "keep-me"
            sentinel.write_text("untouched", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "refusing"):
                create_ui_fixture(production, replace=True)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "untouched")

    def test_full_profile_covers_required_ui_states_and_nulls(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "demo"
            result = create_ui_fixture(workspace)
            self.assertLess(result.generation_seconds, 2.0)
            self.assertLess(result.database_bytes, 5 * 1024 * 1024)
            self.assertEqual(result.schema_version, SCHEMA_VERSION)
            self.assertGreaterEqual(result.counts["research_campaigns"], 8)
            self.assertGreaterEqual(result.counts["director_actions"], 20)
            self.assertGreaterEqual(result.counts["research_lanes"], 12)
            self.assertGreaterEqual(result.counts["campaign_candidates"], 40)
            self.assertGreaterEqual(result.counts["research_hypotheses_v2"], 10)
            self.assertGreaterEqual(result.counts["lane_metric_windows"], 80)

            connection = connect(workspace / "results.sqlite3")
            try:
                campaign_states = {
                    row[0]
                    for row in connection.execute(
                        "SELECT state FROM research_campaigns"
                    )
                }
                self.assertTrue(
                    {
                        "completed_deadline_reached",
                        "running",
                        "paused_by_operator",
                        "stopped_by_operator",
                        "paused_fault",
                        "created",
                    }.issubset(campaign_states)
                )
                actions = {
                    row[0]
                    for row in connection.execute(
                        "SELECT action_type FROM director_actions"
                    )
                }
                self.assertTrue(
                    {
                        "start_lane",
                        "request_diagnostic",
                        "set_review_trigger",
                        "promote_candidate",
                        "schedule_verification",
                        "stop_lane",
                        "patch_lane",
                        "restart_lane",
                    }.issubset(actions)
                )
                lane_states = {
                    row[0]
                    for row in connection.execute(
                        "SELECT state FROM research_lanes"
                    )
                }
                self.assertTrue(
                    {
                        "running",
                        "completed",
                        "paused",
                        "stopped",
                        "failed",
                        "blocked",
                        "starting",
                        "stopping",
                    }.issubset(lane_states)
                )
                effects = " ".join(
                    str(row[0])
                    for row in connection.execute(
                        """
                        SELECT observed_effect_json
                        FROM director_action_outcomes
                        WHERE observed_effect_json IS NOT NULL
                        """
                    )
                )
                for required in (
                    "score_improvement",
                    "no_improvement",
                    "regression",
                    "plateau",
                    "exact_verifier_rejection",
                    "synthetic_demo_exact_pass",
                    "timeout",
                    "mutation_ancestry",
                    "cycle_profile",
                ):
                    self.assertIn(required, effects)
                self.assertGreater(
                    connection.execute(
                        """
                        SELECT max(length(rationale)) FROM director_actions
                        """
                    ).fetchone()[0],
                    500,
                )
                self.assertGreater(
                    connection.execute(
                        """
                        SELECT count(*) FROM app_server_turns
                        WHERE input_tokens IS NULL
                          AND response_artifact_ref IS NULL
                        """
                    ).fetchone()[0],
                    0,
                )
                tool_attempt = connection.execute(
                    """
                    SELECT error_detail FROM app_server_turns
                    WHERE error_kind='synthetic_prohibited_tool_attempt'
                    """
                ).fetchone()
                self.assertIsNotNone(tool_attempt)
                self.assertIn("no tool was invoked", tool_attempt[0])
                self.assertEqual(
                    connection.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )
                self.assertEqual(
                    connection.execute("PRAGMA foreign_key_check").fetchall(),
                    [],
                )
            finally:
                connection.close()

    def test_every_existing_page_has_representative_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "demo"
            create_ui_fixture(workspace)
            status = campaign_status(workspace)
            self.assertEqual(status["campaign_id"], "campaign-demo-running")
            self.assertGreaterEqual(len(status["actions"]), 20)
            self.assertEqual(len(status["lanes"]), 12)
            self.assertGreaterEqual(len(status["hypotheses"]), 10)
            self.assertGreaterEqual(len(status["turns"]), 10)
            self.assertTrue(status["revisions"])
            self.assertIsNotNone(status["assessment"])
            self.assertEqual(len(status["candidates"]), 24)
            self.assertNotIn("graph6", status["candidates"][0])
            self.assertIn("verification_status", status["candidates"][0])

            self.assertGreaterEqual(
                len(list((workspace / "best").glob("*.json"))),
                40,
            )
            self.assertGreaterEqual(
                len(list((workspace / "runs").glob("*/run.json"))),
                8,
            )
            self.assertGreaterEqual(
                len((workspace / "events.jsonl").read_text().splitlines()),
                30,
            )
            with ComparisonStore(workspace / "results.sqlite3") as store:
                suites = store.list_suites()
                statuses = {suite["status"] for suite in suites}
                self.assertTrue(
                    {
                        "draft",
                        "prepared",
                        "authorized",
                        "running",
                        "completed",
                        "failed",
                        "stopped",
                    }.issubset(statuses)
                )
                historical = store.suite_detail(
                    "historical-m6-context-screen"
                )
                self.assertTrue(historical["suite"]["read_only"])
                self.assertTrue(
                    historical["suite"]["runtime_executed_elsewhere"]
                )
                observed = [
                    (
                        turn["display_name"],
                        turn["input_tokens"],
                        turn["server_reported_total_tokens"],
                    )
                    for turn in historical["turns"]
                ]
                self.assertEqual(
                    observed,
                    [
                        ("S2", 9591, 15806),
                        ("P1", 4405, 6498),
                        ("P2", 12754, 16999),
                    ],
                )
                completed = store.suite_detail("comparison-demo-completed")
                self.assertEqual(len(completed["turns"]), 3)
                self.assertEqual(len(completed["ratings"]), 3)
                self.assertEqual(len(completed["pairwise_ratings"]), 1)

    def test_workspace_contains_no_credentials_or_private_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "demo"
            create_ui_fixture(workspace, seed=DEFAULT_UI_FIXTURE_SEED)
            forbidden = (
                b"/home/",
                b"auth.json",
                b"OPENAI_API_KEY",
                b"OPENROUTER_API_KEY",
                b"sk-proj-",
                b"Bearer ",
            )
            for path in workspace.rglob("*"):
                if not path.is_file():
                    continue
                payload = path.read_bytes()
                for needle in forbidden:
                    self.assertNotIn(needle, payload, f"{needle!r} in {path.name}")
            inspection = inspect_ui_fixture(workspace)
            self.assertEqual(
                inspection["fixture_sha256"],
                json.loads(
                    (workspace / "workspace.json").read_text(encoding="utf-8")
                )["fixture_sha256"],
            )
            self.assertEqual(inspection["integrity_check"], "ok")
            self.assertEqual(inspection["foreign_key_check"], [])


if __name__ == "__main__":
    unittest.main()
