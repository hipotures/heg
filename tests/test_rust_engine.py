from __future__ import annotations

from pathlib import Path
from random import Random
import json
import subprocess
import tempfile
import unittest

from sglab.locations import rust_engine_path, score_worker_path
from sglab.model import BitGraph
from sglab.research.campaign import prepare_campaign_plan
from sglab.research.lanes import (
    LaneSpec,
    _LaneKernel,
    _NeverStop,
    normalize_engine_backend,
    run_bounded_lane_batch,
)
from sglab.research.operator import load_experiment_config
from sglab.research.store import ResearchStore
from sglab.score_worker import PersistentScoreWorker, ScoreWorkerError
from sglab.targets.erdos_gyarfas import PLUGIN, forbidden_lengths


@unittest.skipUnless(
    rust_engine_path().is_file() and score_worker_path().is_file(),
    "both C++ score worker and Rust engine must be built",
)
class RustEngineParityTests(unittest.TestCase):
    def test_serve_v2_matches_cpp_score_worker_bit_for_bit(self) -> None:
        rng = Random(20261126)
        with (
            PersistentScoreWorker(binary=score_worker_path()) as cpp_worker,
            PersistentScoreWorker(binary=rust_engine_path()) as rust_worker,
        ):
            for order in (4, 8, 16, 32, 50, 64, 96, 128):
                graph = PLUGIN.generate_seed(
                    rng, {"order": order, "mode": "cubic_first"}
                )
                lengths = forbidden_lengths(order)
                for limit, budget in ((2, 1), (17, 4_096), (65, 50_000)):
                    cpp_resp = cpp_worker.score(
                        graph, lengths=lengths, limit=limit, node_budget=budget
                    )
                    rust_resp = rust_worker.score(
                        graph, lengths=lengths, limit=limit, node_budget=budget
                    )
                    self.assertEqual(cpp_resp.dominated, rust_resp.dominated)
                    self.assertEqual(
                        [
                            (r.length, r.count, r.complete, r.nodes)
                            for r in cpp_resp.results
                        ],
                        [
                            (r.length, r.count, r.complete, r.nodes)
                            for r in rust_resp.results
                        ],
                    )

    def test_serve_v2_cutoff_parity_including_budget_exhaustion(self) -> None:
        with (
            PersistentScoreWorker(binary=score_worker_path()) as cpp_worker,
            PersistentScoreWorker(binary=rust_engine_path()) as rust_worker,
        ):
            for order in (30, 50, 64):
                graph = PLUGIN.generate_seed(
                    Random(order + 99), {"order": order, "mode": "cubic_first"}
                )
                lengths = forbidden_lengths(order)
                full = cpp_worker.score(
                    graph, lengths=lengths, limit=65, node_budget=50_000
                )
                score = PLUGIN.score_from_cycle_counts(
                    graph, 64, full.results, None
                )
                cutoff = (
                    sum(count for _, count in score.witness_counts),
                    score.weighted_penalty,
                    score.simplicity,
                )
                for inclusive in (True, False):
                    cpp_r = cpp_worker.score(
                        graph,
                        lengths=lengths,
                        limit=65,
                        node_budget=50_000,
                        cutoff=cutoff,
                        cutoff_inclusive=inclusive,
                    )
                    rust_r = rust_worker.score(
                        graph,
                        lengths=lengths,
                        limit=65,
                        node_budget=50_000,
                        cutoff=cutoff,
                        cutoff_inclusive=inclusive,
                    )
                    self.assertEqual(cpp_r.dominated, rust_r.dominated)
                    self.assertEqual(
                        [
                            (r.length, r.count, r.complete, r.nodes)
                            for r in cpp_r.results
                        ],
                        [
                            (r.length, r.count, r.complete, r.nodes)
                            for r in rust_r.results
                        ],
                    )

    def test_graph6_and_score_cli_match_python_and_cpp(self) -> None:
        with PersistentScoreWorker(binary=score_worker_path()) as cpp_worker:
            for order in (16, 50, 64, 96):
                graph = PLUGIN.generate_seed(
                    Random(order * 13), {"order": order, "mode": "cubic_first"}
                )
                g6 = graph.to_graph6()
                proc = subprocess.run(
                    [
                        str(rust_engine_path()),
                        "score",
                        "--graph6",
                        g6,
                        "--cap",
                        "64",
                        "--node-budget",
                        "50000",
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                rust_payload = json.loads(proc.stdout)
                cpp_resp = cpp_worker.score(
                    graph,
                    lengths=forbidden_lengths(order),
                    limit=65,
                    node_budget=50_000,
                )
                py_score = PLUGIN.score_from_cycle_counts(
                    graph, 64, cpp_resp.results, None
                )
                self.assertEqual(rust_payload["order"], order)
                self.assertEqual(rust_payload["size"], graph.size())
                self.assertEqual(
                    rust_payload["weighted_penalty"], py_score.weighted_penalty
                )
                self.assertEqual(rust_payload["complete"], py_score.complete)
                self.assertEqual(
                    {
                        int(k): int(v)
                        for k, v in rust_payload["witness_counts"].items()
                    },
                    dict(py_score.witness_counts),
                )

    def test_parallel_rust_search_produces_valid_graph6_candidates(self) -> None:
        for mode in ("cubic_first", "minimal_structure_mixed_degree"):
            proc = subprocess.run(
                [
                    str(rust_engine_path()),
                    "search",
                    "--order",
                    "50",
                    "--mode",
                    mode,
                    "--algorithm",
                    "iterated_local_search_tabu",
                    "--evals",
                    "500",
                    "--workers",
                    "4",
                    "--json",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["engine"], "rust")
            self.assertEqual(payload["total_evaluations"], 2000)
            graph = BitGraph.from_graph6(payload["best_graph6"])
            self.assertEqual(graph.n, 50)
            self.assertTrue(PLUGIN.validate_graph(graph).valid)
            if mode == "cubic_first":
                self.assertEqual(set(graph.degree_sequence()), {3})
            else:
                self.assertTrue(PLUGIN._minimal_structure_valid(graph))

    def test_ducoffe_dumitru_structural_filter_blocks_and_degree_fraction(
        self,
    ) -> None:
        # 1) Biconnected mixed-degree seeds for n=5, 6, 10, 50 must pass.
        for order in (5, 6, 10, 50):
            g = PLUGIN.generate_seed(
                Random(order + 7),
                {"order": order, "mode": "minimal_structure_mixed_degree"},
            )
            self.assertTrue(PLUGIN._minimal_structure_valid(g))
            deg3 = sum(g.degree(u) == 3 for u in range(order))
            self.assertGreater(3 * deg3, 2 * order)

        # 2) Two K4 blocks glued at one cut-vertex (7 vertices: 6 of deg 3, 1 of deg 6):
        #    1-clique-sum of two biconnected graphs -> 2 blocks -> VALID.
        edges_2blocks = [
            (0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3),
            (0, 4), (0, 5), (0, 6), (4, 5), (4, 6), (5, 6),
        ]
        g_2blocks = BitGraph.from_edges(7, edges_2blocks)
        self.assertTrue(PLUGIN._has_at_most_two_blocks(g_2blocks))
        self.assertTrue(PLUGIN._minimal_structure_valid(g_2blocks))

        # 3) Three K4 blocks glued at one cut-vertex (10 vertices):
        #    3 blocks -> INVALID under Ducoffe-Dumitru.
        edges_3blocks = edges_2blocks + [
            (0, 7), (0, 8), (0, 9), (7, 8), (7, 9), (8, 9),
        ]
        g_3blocks = BitGraph.from_edges(10, edges_3blocks)
        self.assertFalse(PLUGIN._has_at_most_two_blocks(g_3blocks))
        self.assertFalse(PLUGIN._minimal_structure_valid(g_3blocks))

        # 4) Two K4-minus-edge blocks joined by a bridge (8 vertices):
        #    3 blocks (block1, bridge, block2) -> INVALID.
        edges_bridge = [
            (0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3),
            (4, 5), (4, 6), (4, 7), (5, 6), (5, 7), (6, 7),
            (3, 4),
        ]
        g_bridge = BitGraph.from_edges(8, edges_bridge)
        self.assertFalse(PLUGIN._has_at_most_two_blocks(g_bridge))
        self.assertFalse(PLUGIN._minimal_structure_valid(g_bridge))

        # 5) Exactly 2/3 degree-3 vertices (n=6: 4 of deg 3, 2 non-adj of deg 4):
        #    3 * 4 == 2 * 6 (not strictly > 2/3) -> INVALID.
        #    Octahedron minus two non-adjacent edges? Build K_{2,4} plus matching on the 4-part:
        #    vertices 0,1 (deg 4) connected to 2,3,4,5; edges (2,3) and (4,5) -> 2,3,4,5 have deg 3.
        g_eq_two_thirds = BitGraph.from_edges(
            6,
            [
                (0, 2), (0, 3), (0, 4), (0, 5),
                (1, 2), (1, 3), (1, 4), (1, 5),
                (2, 3), (4, 5),
            ],
        )
        self.assertTrue(PLUGIN._has_at_most_two_blocks(g_eq_two_thirds))
        self.assertFalse(PLUGIN._minimal_structure_valid(g_eq_two_thirds))

    def test_wired_rust_backend_in_lane_kernel_and_campaign_plan(self) -> None:
        spec = LaneSpec(
            lane_id="lane-rust-wired",
            campaign_id="campaign-rust-wired",
            target="erdos_gyarfas",
            algorithm="iterated_local_search_tabu",
            graph_family="connected_cubic",
            seed=20261126,
            parameters={
                "order": 50,
                "batch_candidates": 500,
                "witness_cap": 64,
                "tabu_tenure": 64,
                "perturbation_interval": 200,
                "mutation_weights": {
                    "uniform_two_edge_switch": 0.5,
                    "forbidden_cycle_break_switch": 0.5,
                },
            },
            resource_share=1.0,
        )
        # 1) Full native Rust micro-batch via run_bounded_lane_batch
        res = run_bounded_lane_batch(
            spec,
            max_evaluations=500,
            max_wall_seconds=30.0,
            engine_backend="rust",
        )
        self.assertEqual(res["evaluation_count"], 500)
        self.assertEqual(
            res["metrics"]["score_backend"]["implementation"], "rust"
        )
        best_g = BitGraph.from_graph6(res["best_graph6"])
        self.assertEqual(best_g.n, 50)
        self.assertTrue(PLUGIN.validate_graph(best_g).valid)

        # 2) Multi-batch continuity in _LaneKernel with engine_backend="rust"
        kernel = _LaneKernel(spec, None, None, engine_backend="rust")
        try:
            m1 = kernel.run_batch(_NeverStop(), max_evaluations=250)
            cp = kernel.checkpoint(1)
            m2 = kernel.run_batch(_NeverStop(), max_evaluations=250)
            self.assertEqual(m1["end_high_water"], 250)
            self.assertEqual(m2["end_high_water"], 500)
            self.assertEqual(cp["graph6"], BitGraph.from_graph6(cp["graph6"]).to_graph6())
        finally:
            kernel.close()

        # 3) Drop-in Rust --serve scorer backend inside Python loop
        scorer_res = run_bounded_lane_batch(
            spec,
            max_evaluations=50,
            max_wall_seconds=30.0,
            engine_backend="rust_scorer",
        )
        self.assertEqual(
            scorer_res["metrics"]["score_backend"]["implementation"],
            "rust_scorer",
        )

        # 4) Campaign plan + experiment.toml wiring and fail-closed validation
        with self.assertRaises(ValueError):
            normalize_engine_backend("invalid_backend")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "workspace.json").write_text(
                json.dumps(
                    {
                        "workspace_kind": "first_real_graph_campaign",
                        "synthetic_data": False,
                    }
                ),
                encoding="utf-8",
            )
            with ResearchStore(root / "results.sqlite3"):
                pass
            plan = prepare_campaign_plan(
                root,
                duration_seconds=3600,
                director_mode="passive",
                engine_backend="rust",
            )
            self.assertEqual(
                plan["search_limits"]["engine_backend"], "rust"
            )
            cfg_path = root / "experiment.toml"
            cfg_path.write_text(
                '[experiment]\nid = "rust-exp-01"\n\n[search]\nengine_backend = "rust"\n',
                encoding="utf-8",
            )
            cfg = load_experiment_config(cfg_path)
            self.assertEqual(cfg.engine_backend, "rust")

    def test_rust_json_escapes_backslash_in_graph6(self) -> None:
        # Find a 50-vertex cubic graph whose graph6 string contains '\' (ASCII 92).
        rng = Random(42)
        g = PLUGIN.generate_seed(rng, {"order": 50, "mode": "cubic_first"})
        while "\\" not in g.to_graph6():
            g = PLUGIN.mutate(g, rng, {"mode": "cubic_first"})
        g6 = g.to_graph6()
        self.assertIn("\\", g6)
        proc = subprocess.run(
            [
                str(rust_engine_path()),
                "search",
                "--initial-graph6",
                g6,
                "--algorithm",
                "iterated_local_search_tabu",
                "--evals",
                "10",
                "--workers",
                "1",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(proc.stdout)
        self.assertEqual(BitGraph.from_graph6(payload["best_graph6"]).n, 50)
        self.assertEqual(BitGraph.from_graph6(payload["final_graph6"]).n, 50)


if __name__ == "__main__":
    unittest.main()
