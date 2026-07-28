from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from queue import Queue
from unittest.mock import Mock, patch

from sglab.research.lanes import (
    LaneManager,
    LaneRuntime,
    LaneSpec,
    _LaneKernel,
    _publish_live_frontier,
)
from sglab.research.telemetry import TelemetrySeries, compare_effects
from sglab.state import read_json


def lane_spec(lane_id: str, algorithm: str, share: float = 0.5) -> LaneSpec:
    parameters = {
        "order": 8,
        "batch_candidates": 100,
        "witness_cap": 4,
    }
    if algorithm == "simulated_annealing":
        parameters.update(
            {
                "temperature": 1.0,
                "cooling": 0.999,
                "restart_threshold": 1000,
            }
        )
    else:
        parameters.update({"tabu_tenure": 32, "perturbation_interval": 16})
    return LaneSpec(
        lane_id=lane_id,
        campaign_id="campaign-test",
        target="erdos_gyarfas",
        algorithm=algorithm,
        graph_family="connected_cubic",
        seed=11 if lane_id == "lane-a" else 19,
        parameters=parameters,
        resource_share=share,
        seed_lineage=(11 if lane_id == "lane-a" else 19,),
    )


def poll_until(manager: LaneManager, predicate, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        manager.poll(timeout=0.05)
        if predicate():
            return
    raise AssertionError("lane condition was not reached before timeout")


class LaneManagerTests(unittest.TestCase):
    def test_shutdown_closes_owned_multiprocessing_queues(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = LaneManager(Path(directory))
            commands = manager.context.Queue(maxsize=1)
            process = Mock()
            process.is_alive.return_value = False
            manager.lanes["lane-shutdown"] = LaneRuntime(
                spec=lane_spec(
                    "lane-shutdown", "simulated_annealing"
                ),
                process=process,
                commands=commands,
                stop_event=Mock(),
                pause_event=Mock(),
            )

            manager.shutdown()
            manager.shutdown()

            with self.assertRaisesRegex(ValueError, "closed"):
                commands.put_nowait({"kind": "stop"})
            with self.assertRaisesRegex(ValueError, "closed"):
                manager.events.put_nowait({"kind": "exit"})

    def test_live_frontier_publication_reuses_score_and_overwrites_file(
        self,
    ) -> None:
        spec = lane_spec("lane-preview", "iterated_local_search")
        kernel = _LaneKernel(spec, checkpoint=None, fork_seed=None)
        previews = []
        events = Queue(maxsize=1)
        stop = type("Stop", (), {"is_set": lambda self: False})()
        for _ in range(2):
            kernel.run_batch(stop, max_evaluations=1)
            with (
                patch.object(
                    kernel,
                    "_score",
                    side_effect=AssertionError("preview rescored graph"),
                ),
                patch.object(
                    kernel,
                    "checkpoint",
                    side_effect=AssertionError(
                        "preview serialized full checkpoint"
                    ),
                ),
            ):
                _publish_live_frontier(
                    events, spec, kernel, lane_version=0
                )
            previews.append(events.get_nowait()["preview"])
        self.assertEqual(len(previews), 2)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = LaneManager(root)
            runtime = LaneRuntime(
                spec=spec,
                process=None,
                commands=None,
                stop_event=None,
                pause_event=None,
            )
            manager._remember_live_frontier(runtime, previews[0])
            manager._remember_live_frontier(runtime, previews[1])
            paths = list(
                (root / "lane-checkpoints").glob(
                    "live-frontier-*.json"
                )
            )
            self.assertEqual(len(paths), 1)
            self.assertEqual(
                read_json(paths[0])["preview_id"],
                previews[1]["preview_id"],
            )
            self.assertFalse(any(root.glob("*.sqlite*")))

    def test_live_patch_fork_progress_and_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manager = LaneManager(
                Path(directory),
                max_active_lanes=4,
                checkpoints_per_lane=3,
                pinned_checkpoints=2,
            )
            try:
                lane_a = manager.start_lane(
                    lane_spec("lane-a", "simulated_annealing")
                )
                lane_b = manager.start_lane(
                    lane_spec("lane-b", "iterated_local_search")
                )
                poll_until(
                    manager,
                    lambda: (
                        lane_a.state == lane_b.state == "running"
                        and lane_a.high_water >= 100
                        and lane_b.high_water >= 100
                        and lane_a.latest_checkpoint_id is not None
                    ),
                )
                poll_until(
                    manager,
                    lambda: lane_a.latest_live_frontier is not None,
                )
                self.assertTrue(lane_a.process.is_alive())
                self.assertTrue(lane_b.process.is_alive())
                parent_checkpoint = str(lane_a.latest_checkpoint_id)
                parent_before = lane_a.high_water
                child = manager.fork_lane(
                    "lane-a",
                    child_lane_id="lane-child",
                    action_id="action-fork",
                    expected_lane_version=0,
                    checkpoint_id=parent_checkpoint,
                    patch={"temperature": 0.4},
                    resource_share=0.25,
                )
                manager.send_patch(
                    "lane-a",
                    action_id="action-patch",
                    expected_lane_version=0,
                    patch={"temperature": 0.6},
                )
                inference_start_total = manager.total_candidates()
                inference_deadline = time.monotonic() + 0.35
                while time.monotonic() < inference_deadline:
                    manager.poll(timeout=0.02)
                self.assertGreater(
                    manager.total_candidates(),
                    inference_start_total,
                    "search must continue while Director inference is in progress",
                )
                poll_until(
                    manager,
                    lambda: (
                        lane_a.lane_version == 1
                        and child.state == "running"
                        and child.high_water >= 100
                        and lane_a.high_water > parent_before
                    ),
                )
                self.assertEqual(lane_a.parameters["temperature"], 0.6)
                self.assertEqual(child.parameters["temperature"], 0.4)
                self.assertTrue(lane_a.process.is_alive())
                self.assertTrue(child.process.is_alive())
                patch_outcome = next(
                    outcome
                    for outcome in lane_a.action_outcomes
                    if outcome["action_id"] == "action-patch"
                )
                self.assertEqual(patch_outcome["status"], "applied")
                self.assertEqual(patch_outcome["resulting_lane_version"], 1)
                self.assertIn(
                    patch_outcome["checkpoint_id"], manager.checkpoints
                )
                with self.assertRaisesRegex(RuntimeError, "already"):
                    manager.send_patch(
                        "lane-a",
                        action_id="action-patch",
                        expected_lane_version=1,
                        patch={"temperature": 0.7},
                    )
                manager.send_patch(
                    "lane-a",
                    action_id="action-stale",
                    expected_lane_version=0,
                    patch={"temperature": 0.7},
                )
                poll_until(
                    manager,
                    lambda: any(
                        outcome["action_id"] == "action-stale"
                        for outcome in lane_a.action_outcomes
                    ),
                )
                stale = next(
                    outcome
                    for outcome in lane_a.action_outcomes
                    if outcome["action_id"] == "action-stale"
                )
                self.assertEqual(stale["status"], "rejected_stale_state")
                self.assertEqual(lane_a.lane_version, 1)
                restart_checkpoint = str(lane_a.latest_checkpoint_id)
                manager.restart_lane(
                    "lane-a",
                    action_id="action-restart",
                    expected_lane_version=1,
                    seed=1234,
                    checkpoint_id=restart_checkpoint,
                )
                poll_until(manager, lambda: lane_a.lane_version == 2)
                restart_outcome = next(
                    outcome
                    for outcome in lane_a.action_outcomes
                    if outcome["action_id"] == "action-restart"
                )
                self.assertEqual(restart_outcome["status"], "applied")
                self.assertLessEqual(len(lane_a.telemetry.items()), 120)
                poll_until(
                    manager,
                    lambda: len(manager._checkpoint_order["lane-a"]) == 3,
                )
                self.assertLessEqual(
                    len(manager.checkpoints),
                    len(manager.lanes) * manager.checkpoints_per_lane
                    + manager.pinned_checkpoints,
                )
            finally:
                manager.shutdown()

    def test_lane_spec_rejects_float_integer_and_order_patch(self) -> None:
        invalid = lane_spec("lane-invalid", "simulated_annealing")
        invalid.parameters["batch_candidates"] = 100.5
        with self.assertRaisesRegex(ValueError, "integer"):
            invalid.validate()


class TelemetryTests(unittest.TestCase):
    def test_bounded_slope_and_effect_comparison(self) -> None:
        series = TelemetrySeries(maximum=3)
        for index, score in enumerate((10.0, 9.0, 8.0, 7.0)):
            series.append(
                {
                    "end_high_water": index * 100,
                    "best_scalar": score,
                    "candidates_per_second": 1000 + index,
                    "duplicate_rate": 0.2,
                    "diversity": 0.8,
                    "operator_yield": 0.01,
                }
            )
        self.assertEqual(len(series.items()), 3)
        self.assertLess(series.recent()["score_slope"], 0)
        effect = compare_effects(
            [
                {
                    "end_high_water": 100,
                    "best_scalar": 10,
                    "diversity": 0.4,
                },
                {
                    "end_high_water": 200,
                    "best_scalar": 10,
                    "diversity": 0.4,
                },
            ],
            [
                {
                    "end_high_water": 300,
                    "best_scalar": 9,
                    "diversity": 0.6,
                },
                {
                    "end_high_water": 400,
                    "best_scalar": 8,
                    "diversity": 0.6,
                },
            ],
            expected_direction="improve_score_slope",
        )
        self.assertTrue(effect.expectation_met)
        self.assertGreater(effect.diversity_change, 0)
