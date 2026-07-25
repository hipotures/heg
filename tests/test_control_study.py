import tempfile
import threading
import time
import unittest
from pathlib import Path
from queue import Queue

from sglab.cli import build_parser
from sglab.research.campaign import (
    ResearchCampaignRunner,
    campaign_status,
    request_campaign_control,
)
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
            outcome: Queue[tuple[str, object]] = Queue(maxsize=1)

            def run_campaign() -> None:
                try:
                    result = ResearchCampaignRunner(
                        workspace=root,
                        stop_mode="until_success",
                        target="m6_hidden_witness_control_v1",
                        controller_mode="static",
                        controller_seed=41,
                        poll_seconds=0.01,
                    ).run()
                except BaseException as error:
                    outcome.put(("error", error))
                else:
                    outcome.put(("ok", result))

            started = time.monotonic()
            worker = threading.Thread(target=run_campaign, daemon=True)
            worker.start()
            deadline = started + 8.0
            observed = None
            while time.monotonic() < deadline:
                current = campaign_status(root)
                if any(
                    int(lane["telemetry_high_water"]) > 0
                    for lane in current.get("lanes", [])
                ):
                    observed = current
                    break
                if not worker.is_alive():
                    break
                time.sleep(0.01)
            try:
                self.assertIsNotNone(
                    observed,
                    "real lane did not publish a first evaluation",
                )
            finally:
                if worker.is_alive():
                    request_campaign_control(root, "STOP")
                worker.join(timeout=5)
            self.assertFalse(worker.is_alive(), "campaign did not stop")
            result_kind, result = outcome.get_nowait()
            if result_kind == "error":
                if not isinstance(result, BaseException):
                    raise AssertionError("campaign returned a malformed error")
                raise result
            if not isinstance(result, dict):
                raise AssertionError("campaign returned a malformed result")
            status = result
            campaign_id = str(status["campaign_id"])
            final = campaign_status(root, campaign_id)
            self.assertEqual(final["state"], "stopped_by_operator")
            self.assertTrue(final["lanes"])
            self.assertTrue(
                all(lane["state"] == "paused" for lane in final["lanes"])
            )
            self.assertTrue(
                all(lane["checkpoint_ref"] for lane in final["lanes"])
            )
            self.assertTrue(
                any(
                    int(lane["telemetry_high_water"]) > 0
                    for lane in final["lanes"]
                )
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
            self.assertLess(time.monotonic() - started, 8.0)


if __name__ == "__main__":
    unittest.main()
