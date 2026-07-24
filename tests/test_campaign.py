import tempfile
import unittest
from pathlib import Path

from sglab.cli import build_parser
from sglab.research.campaign import (
    ResearchCampaignRunner,
    campaign_status,
    parse_duration,
    request_campaign_control,
)
from sglab.research.store import ResearchStore


class CampaignOperatorContractTests(unittest.TestCase):
    def test_normal_start_accepts_exactly_one_stop_mode_and_no_tuning(self) -> None:
        parser = build_parser()
        time_args = parser.parse_args(
            [
                "research-campaign",
                "start",
                "--workspace",
                "/tmp/example",
                "--time-limit",
                "24h",
            ]
        )
        self.assertEqual(time_args.time_limit, "24h")
        success_args = parser.parse_args(
            [
                "research-campaign",
                "start",
                "--workspace",
                "/tmp/example",
                "--until-success",
            ]
        )
        self.assertTrue(success_args.until_success)
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "research-campaign",
                    "start",
                    "--workspace",
                    "/tmp/example",
                    "--time-limit",
                    "1h",
                    "--until-success",
                ]
            )
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "research-campaign",
                    "start",
                    "--workspace",
                    "/tmp/example",
                    "--time-limit",
                    "1h",
                    "--workers",
                    "8",
                ]
            )

    def test_duration_and_control_contracts_are_bounded(self) -> None:
        self.assertEqual(parse_duration("2h"), 7200)
        self.assertEqual(parse_duration("1d"), 86400)
        for invalid in ("", "0s", "366d", "many"):
            with self.assertRaises(ValueError):
                parse_duration(invalid)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            first = request_campaign_control(workspace, "PAUSE")
            second = request_campaign_control(workspace, "RESUME")
            self.assertEqual(first["version"], 1)
            self.assertEqual(second["version"], 2)
            with self.assertRaises(ValueError):
                request_campaign_control(workspace, "SHELL")

    def test_missing_explicit_auth_fails_before_campaign_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "authentication is not imported"):
                ResearchCampaignRunner(
                    workspace=workspace,
                    stop_mode="time_limit",
                    duration_seconds=1,
                ).run()
            self.assertFalse((workspace / "results.sqlite3").exists())


class CampaignStateTests(unittest.TestCase):
    def test_operational_terminal_states_cannot_claim_m4_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            with ResearchStore(workspace / "results.sqlite3") as store:
                store.create_campaign(
                    campaign_id="deadline",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="time_limit",
                    deadline_at="2026-07-24T12:00:00Z",
                )
                self.assertTrue(
                    store.finish_campaign(
                        "deadline",
                        terminal_kind="completed_deadline_reached",
                    )
                )
                self.assertFalse(
                    store.finish_campaign(
                        "deadline",
                        terminal_kind="stopped_by_operator",
                    )
                )
                store.create_campaign(
                    campaign_id="until-success",
                    target="erdos_gyarfas",
                    target_definition_sha256="b" * 64,
                    stop_mode="until_success",
                    deadline_at=None,
                )
                store.create_lane(
                    lane_id="lane-1",
                    campaign_id="until-success",
                    target="erdos_gyarfas",
                    parent_lane_id=None,
                    parent_checkpoint_ref=None,
                    action_id="bootstrap",
                    algorithm="simulated_annealing",
                    graph_family="connected_cubic",
                    parameters={"order": 8},
                    seed_lineage=[1],
                    resource_share=1.0,
                    lease_expires_at=None,
                )
                store.mark_lane_running("lane-1")
                version = store.set_campaign_coordination_state(
                    "until-success",
                    expected_version=0,
                    state="paused_by_operator",
                )
                lane_state = store.connection.execute(
                    "SELECT state FROM research_lanes WHERE lane_id='lane-1'"
                ).fetchone()[0]
                self.assertEqual(lane_state, "paused")
                store.set_campaign_coordination_state(
                    "until-success",
                    expected_version=version,
                    state="running",
                )
                with self.assertRaises(RuntimeError):
                    store.finish_campaign(
                        "until-success",
                        terminal_kind="completed_deadline_reached",
                    )
                with self.assertRaises(ValueError):
                    store.finish_campaign(
                        "until-success",
                        terminal_kind="succeeded_certified_counterexample",
                    )
            status = campaign_status(workspace, "deadline")
            self.assertEqual(status["state"], "completed_deadline_reached")
            self.assertEqual(status["target"], "erdos_gyarfas")
            self.assertEqual(status["verification"]["certified"], 0)


if __name__ == "__main__":
    unittest.main()
