import random
import json
import tempfile
import unittest
import sqlite3
from pathlib import Path

from sglab.resources import recommended_workers
from sglab.search import SearchConfig, config_from_run, run_search
from sglab.targets.erdos_gyarfas import PLUGIN


class SearchTests(unittest.TestCase):
    def test_cubic_seed_and_swap_preserve_invariants(self) -> None:
        rng = random.Random(7)
        graph = PLUGIN.generate_seed(rng, {"order": 10, "mode": "cubic_first"})
        self.assertEqual(set(graph.degree_sequence()), {3})
        for _ in range(20):
            graph = PLUGIN.mutate(graph, rng, {"mode": "cubic_first"})
            self.assertTrue(graph.is_connected())
            self.assertEqual(set(graph.degree_sequence()), {3})

    def test_mixed_seed_satisfies_named_structural_prior(self) -> None:
        graph = PLUGIN.generate_seed(
            random.Random(9),
            {"order": 10, "mode": "minimal_structure_mixed_degree"},
        )
        self.assertTrue(PLUGIN._minimal_structure_valid(graph))
        self.assertGreater(max(graph.degree_sequence()), 3)

    def test_unrestricted_odd_order_has_a_valid_seed(self) -> None:
        graph = PLUGIN.generate_seed(
            random.Random(11),
            {"order": 9, "mode": "unrestricted_min_degree_3"},
        )
        self.assertEqual(graph.n, 9)
        self.assertTrue(graph.is_connected())
        self.assertGreaterEqual(graph.minimum_degree(), 3)

    def test_search_smoke_writes_reproducible_run_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = run_search(
                SearchConfig(
                    workspace=Path(directory),
                    order=8,
                    workers=4,
                    wall_seconds=0.8,
                    max_candidates=30,
                    archive_top_k=2,
                    state_seconds=0.1,
                    checkpoint_seconds=0.2,
                    min_free_disk_bytes=1,
                )
            )
            self.assertTrue((run_dir / "run.json").is_file())
            self.assertTrue((run_dir / "state.json").is_file())
            self.assertTrue((run_dir / "results.sqlite3").is_file())
            database = sqlite3.connect(run_dir / "results.sqlite3")
            self.assertGreater(
                database.execute("SELECT count(*) FROM candidate_scores").fetchone()[0],
                0,
            )
            self.assertGreater(
                database.execute("SELECT count(*) FROM artifacts").fetchone()[0],
                0,
            )
            self.assertLessEqual(
                database.execute("SELECT count(*) FROM candidates").fetchone()[0],
                2,
            )
            database.close()
            checkpoints = [
                path
                for path in (run_dir / "checkpoints").glob("worker-*.json")
                if not path.name.endswith(".sha256.json")
            ]
            self.assertTrue(checkpoints)
            self.assertTrue(checkpoints[0].with_suffix(".sha256.json").is_file())
            final_state = json.loads(
                (run_dir / "state.json").read_text(encoding="utf-8")
            )
            self.assertGreater(final_state["throughput"]["candidates"], 0)
            self.assertLessEqual(final_state["throughput"]["candidates"], 30)
            self.assertEqual(
                len(final_state["workers"]["items"]),
                recommended_workers(4),
            )
            self.assertIn(
                '"status": "NO_RESULT_WITHIN_BUDGET"',
                (run_dir / "state.json").read_text(encoding="utf-8"),
            )

    def test_config_rejects_odd_cubic_order(self) -> None:
        with self.assertRaises(ValueError):
            SearchConfig(workspace=Path("."), order=9).validate()

    def test_config_rejects_memory_high_above_hard_limit(self) -> None:
        with self.assertRaises(ValueError):
            SearchConfig(
                workspace=Path("."),
                memory_high_bytes=2,
                memory_limit_bytes=1,
            ).validate()
        with tempfile.TemporaryDirectory() as directory:
            run_dir = run_search(
                SearchConfig(
                    workspace=Path(directory),
                    order=8,
                    wall_seconds=0.8,
                    memory_high_bytes=1,
                    state_seconds=0.1,
                    checkpoint_seconds=0.1,
                    min_free_disk_bytes=1,
                )
            )
            self.assertIn(
                '"event":"memory_high_pause"',
                (run_dir / "events.jsonl").read_text(encoding="utf-8"),
            )

    def test_resume_keeps_run_id_and_records_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = run_search(
                SearchConfig(
                    workspace=Path(directory),
                    order=8,
                    wall_seconds=0.7,
                    state_seconds=0.1,
                    checkpoint_seconds=0.1,
                    min_free_disk_bytes=1,
                )
            )
            first_state = json.loads((first / "state.json").read_text(encoding="utf-8"))
            checkpoint = json.loads(
                (first / "checkpoints" / "worker-0.json").read_text(encoding="utf-8")
            )
            self.assertIn("best_graph6", checkpoint)
            self.assertIn("tabu", checkpoint)
            self.assertIn("algorithm_evaluated", checkpoint)
            config = config_from_run(first, wall_seconds=0.2)
            resumed = run_search(config, resume_run=first)
            self.assertEqual(resumed, first)
            resumed_state = json.loads(
                (resumed / "state.json").read_text(encoding="utf-8")
            )
            self.assertGreater(
                resumed_state["throughput"]["candidates"],
                first_state["throughput"]["candidates"],
            )
            self.assertGreater(
                resumed_state["elapsed_seconds"],
                first_state["elapsed_seconds"],
            )
            self.assertIn(
                '"event":"run_resumed"',
                (first / "events.jsonl").read_text(encoding="utf-8"),
            )

    def test_normal_worker_recycling_is_not_treated_as_repeated_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = run_search(
                SearchConfig(
                    workspace=Path(directory),
                    order=8,
                    wall_seconds=0.8,
                    worker_recycle_candidates=10,
                    state_seconds=0.1,
                    checkpoint_seconds=0.1,
                    min_free_disk_bytes=1,
                )
            )
            events = (run_dir / "events.jsonl").read_text(encoding="utf-8")
            self.assertGreater(events.count('"event":"worker_restarted"'), 3)
            self.assertIn('"status":"NO_RESULT_WITHIN_BUDGET"', events)
            final_state = json.loads(
                (run_dir / "state.json").read_text(encoding="utf-8")
            )
            self.assertGreater(final_state["throughput"]["candidates"], 40)
