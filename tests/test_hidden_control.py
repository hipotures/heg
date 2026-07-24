import tempfile
import unittest
from pathlib import Path
from random import Random

from sglab.certification import certify
from sglab.model import BitGraph
from sglab.research.candidates import CandidateArchive
from sglab.research.store import ResearchStore
from sglab.targets import TARGETS, target_summary


def withheld_control_witness() -> BitGraph:
    edges = {
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 4),
        (0, 4),
        (5, 7),
        (7, 9),
        (6, 9),
        (6, 8),
        (5, 8),
        (0, 5),
        (1, 6),
        (2, 7),
        (3, 8),
        (4, 9),
    }
    return BitGraph.from_edges(10, edges)


class HiddenWitnessControlTests(unittest.TestCase):
    def test_control_target_is_separate_and_search_compatible(self) -> None:
        target = TARGETS["m6_hidden_witness_control_v1"]
        summary = target_summary(target.id)
        self.assertTrue(summary["control_only"])
        self.assertNotEqual(target.id, "erdos_gyarfas")
        graph = target.generate_seed(
            Random(7), {"order": 10, "mode": "cubic_first"}
        )
        self.assertTrue(target.validate_graph(graph).valid)
        self.assertEqual(target.forbidden_lengths(10), (3,))
        self.assertEqual(target.forbidden_lengths(12), ())

    def test_withheld_witness_requires_two_complete_m4_paths(self) -> None:
        graph = withheld_control_witness()
        target = TARGETS["m6_hidden_witness_control_v1"]
        self.assertEqual(target.exact_verify(graph).status, "VERIFIED")
        with tempfile.TemporaryDirectory() as directory:
            manifest = certify(
                graph,
                Path(directory),
                target=target.id,
                timeout_seconds=5,
            )
        self.assertEqual(manifest["target"], target.id)
        self.assertEqual(manifest["status"], "COUNTEREXAMPLE_VERIFIED")
        self.assertEqual(manifest["forbidden_lengths"], [3])
        self.assertEqual(len(manifest["verifiers"]), 2)
        self.assertTrue(all(item["complete"] for item in manifest["verifiers"]))
        self.assertEqual(
            {item["implementation"] for item in manifest["verifiers"]},
            {"python-reference-dfs", "cpp17-bitset-dfs"},
        )

    def test_wrong_order_is_invalid_not_success(self) -> None:
        graph = BitGraph.from_edges(
            4,
            ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)),
        )
        result = TARGETS["m6_hidden_witness_control_v1"].exact_verify(graph)
        self.assertEqual(result.status, "INVALID")

    def test_initial_checkpoint_can_enter_bounded_candidate_archive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            target = "m6_hidden_witness_control_v1"
            store.create_campaign(
                campaign_id="campaign-1",
                target=target,
                target_definition_sha256="a" * 64,
                stop_mode="time_limit",
                deadline_at="2026-07-25T00:00:00Z",
            )
            store.create_lane(
                lane_id="lane-1",
                campaign_id="campaign-1",
                target=target,
                parent_lane_id=None,
                parent_checkpoint_ref=None,
                action_id="start",
                algorithm="simulated_annealing",
                graph_family="connected_cubic",
                parameters={"order": 10},
                seed_lineage=[1],
                resource_share=1,
                lease_expires_at=None,
            )
            graph = withheld_control_witness()
            candidate_id = CandidateArchive(
                store=store,
                campaign_id="campaign-1",
                campaign_dir=root,
            ).observe_checkpoint(
                {
                    "kind": "checkpoint",
                    "lane_id": "lane-1",
                    "checkpoint": {
                        "lane_version": 0,
                        "checkpoint_id": "checkpoint-1",
                        "best_graph6": graph.to_graph6(),
                        "best_score": {
                            "valid": True,
                            "ordering_key": [0, 0, 0, 0, 15],
                        },
                    },
                }
            )
            self.assertIsNotNone(candidate_id)
            self.assertEqual(
                store.campaign_candidate(str(candidate_id))["campaign_id"],
                "campaign-1",
            )
            store.close()


if __name__ == "__main__":
    unittest.main()
