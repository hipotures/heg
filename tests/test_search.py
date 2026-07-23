import random
import tempfile
import unittest
from pathlib import Path

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

    def test_search_smoke_writes_reproducible_run_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run_dir = run_search(
                SearchConfig(
                    workspace=Path(directory),
                    order=8,
                    workers=1,
                    wall_seconds=0.8,
                    max_candidates=30,
                    state_seconds=0.1,
                    checkpoint_seconds=0.2,
                    min_free_disk_bytes=1,
                )
            )
            self.assertTrue((run_dir / "run.json").is_file())
            self.assertTrue((run_dir / "state.json").is_file())
            self.assertTrue((run_dir / "results.sqlite3").is_file())
            checkpoints = [
                path
                for path in (run_dir / "checkpoints").glob("worker-*.json")
                if not path.name.endswith(".sha256.json")
            ]
            self.assertTrue(checkpoints)
            self.assertTrue(checkpoints[0].with_suffix(".sha256.json").is_file())
            self.assertIn(
                '"status": "NO_RESULT_WITHIN_BUDGET"',
                (run_dir / "state.json").read_text(encoding="utf-8"),
            )

    def test_config_rejects_odd_cubic_order(self) -> None:
        with self.assertRaises(ValueError):
            SearchConfig(workspace=Path("."), order=9).validate()

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
            config = config_from_run(first, wall_seconds=0.2)
            resumed = run_search(config, resume_run=first)
            self.assertEqual(resumed, first)
            self.assertIn(
                '"event":"run_resumed"',
                (first / "events.jsonl").read_text(encoding="utf-8"),
            )
