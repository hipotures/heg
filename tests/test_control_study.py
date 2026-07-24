import tempfile
import unittest
from pathlib import Path

from sglab.cli import build_parser
from sglab.research.campaign import ResearchCampaignRunner, campaign_status
from sglab.research.control_study import (
    ControlStudyBudget,
    ControlStudyRunner,
    _trial_metrics,
)


class ControlStudyTests(unittest.TestCase):
    def test_fixed_budget_and_cli_do_not_expose_scientific_tuning(self) -> None:
        ControlStudyBudget(wall_seconds=10, seeds=(1, 2)).validate()
        with self.assertRaises(ValueError):
            ControlStudyBudget(wall_seconds=9, seeds=(1, 2)).validate()
        parser = build_parser()
        parsed = parser.parse_args(
            [
                "benchmark",
                "active-director-controls",
                "--workspace",
                "/tmp/study",
                "--output",
                "/tmp/report",
                "--smoke",
            ]
        )
        self.assertTrue(parsed.smoke)
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "benchmark",
                    "active-director-controls",
                    "--workspace",
                    "/tmp/study",
                    "--output",
                    "/tmp/report",
                    "--algorithm",
                    "simulated_annealing",
                ]
            )

    def test_full_study_requires_explicit_auth_before_any_trial(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "requires.*auth"):
                ControlStudyRunner(
                    workspace=root,
                    output=root / "report",
                    budget=ControlStudyBudget(
                        wall_seconds=10,
                        seeds=(1, 2),
                    ),
                ).run()
            self.assertFalse((root / "results.sqlite3").exists())

    def test_static_control_runs_in_real_lanes_and_retains_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            status = ResearchCampaignRunner(
                workspace=root,
                stop_mode="time_limit",
                duration_seconds=1,
                target="m6_hidden_witness_control_v1",
                controller_mode="static",
                controller_seed=41,
                poll_seconds=0.01,
            ).run()
            campaign_id = str(status["campaign_id"])
            final = campaign_status(root, campaign_id)
            self.assertEqual(final["state"], "completed_deadline_reached")
            self.assertTrue(final["lanes"])
            self.assertTrue(
                all(lane["state"] == "stopped" for lane in final["lanes"])
            )
            metrics = _trial_metrics(
                root / "results.sqlite3",
                campaign_id,
                controller="static",
                seed=41,
            )
            self.assertGreater(metrics["candidate_evaluations"], 0)
            self.assertEqual(metrics["provider"]["total_tokens"], 0)
            self.assertFalse(metrics["certified_witness"])


if __name__ == "__main__":
    unittest.main()
