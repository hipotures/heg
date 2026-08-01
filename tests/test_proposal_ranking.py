from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from random import Random

from sglab.db import BASE_SCHEMA_SQL, SCHEMA_VERSION, migrate
from sglab.research.lanes import LaneSpec, replay_micro_batches, run_bounded_lane_batch
from sglab.research.proposal_ranking import (
    CATALOG_ID,
    FROZEN_IDENTITY,
    HegPolicyBridge,
    PolicyWorker,
    checkpoint_policy_identity,
    require_checkpoint_identity,
    verify_frozen_policy,
)
from sglab.research.proposal_ranking_replay import (
    build_replay_records,
    run_red_team,
    run_replay,
    run_worker_benchmark,
)
from sglab.targets import TARGETS


def ranking_spec(*, lane_id: str = "ranking-test", catalog: str = CATALOG_ID) -> LaneSpec:
    return LaneSpec(
        lane_id=lane_id,
        campaign_id="ranking-test-campaign",
        target="erdos_gyarfas",
        algorithm="iterated_local_search_tabu",
        graph_family="connected_cubic",
        seed=20260801,
        parameters={
            "order": 14,
            "batch_candidates": 100,
            "witness_cap": 32,
            "tabu_tenure": 48,
            "perturbation_interval": 200,
            "proposal_ranking": catalog,
        },
        resource_share=1.0,
    )


class ProposalRankingTests(unittest.TestCase):
    def test_frozen_source_identity(self) -> None:
        result = verify_frozen_policy()
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["source_sha256"], FROZEN_IDENTITY.source_sha256)
        self.assertEqual(result["normalized_ast_sha256"], FROZEN_IDENTITY.normalized_ast_sha256)

    def test_host_pool_is_deterministic_and_m4_isolated(self) -> None:
        graph = TARGETS["erdos_gyarfas"].generate_seed(
            Random(20260801), {"order": 14, "mode": "cubic_first"}
        )
        with HegPolicyBridge() as left, HegPolicyBridge() as right:
            left_pool = left.generate_pool(graph, policy_seed=21, step=3)
            right_pool = right.generate_pool(graph, policy_seed=21, step=3)
            self.assertEqual(left_pool.pool_hash, right_pool.pool_hash)
            left_context = left.context_for_graph(graph)
            selection = left.select(left_context, left_pool)
            self.assertEqual(selection.rank_order[0], selection.selected_proposal_id)
            self.assertEqual(selection.telemetry["m4_calls"], 0)
            self.assertEqual(selection.telemetry["selected_authoritative_scorer_calls"], 0)
            self.assertEqual({candidate.payload["k"] for candidate in left_pool.candidates}, {2, 3, 4})

    def test_worker_has_no_fallback_and_reaps(self) -> None:
        source = Path("src/sglab/research/assets/mutation_policy_stage4r_v1.py").read_text()
        with self.assertRaises(Exception):
            PolicyWorker(source=source + "\n")

    def test_checkpoint_identity_is_exact_and_disabled_is_refused(self) -> None:
        identity = checkpoint_policy_identity()
        require_checkpoint_identity({"proposal_ranking_identity": identity}, enabled=True)
        tampered = dict(identity, source_sha256="0" * 64)
        with self.assertRaises(Exception):
            require_checkpoint_identity({"proposal_ranking_identity": tampered}, enabled=True)
        with self.assertRaises(Exception):
            require_checkpoint_identity({"proposal_ranking_identity": identity}, enabled=False)

    def test_ranking_lane_checkpoint_and_resume(self) -> None:
        result = run_bounded_lane_batch(
            ranking_spec(), max_evaluations=1, max_wall_seconds=30
        )
        self.assertEqual(result["evaluation_count"], 1)
        self.assertEqual(result["checkpoint"]["proposal_ranking_identity"], checkpoint_policy_identity())
        replay_checkpoint = dict(result["checkpoint"])
        replay_checkpoint["proposal_ranking_identity"] = dict(
            replay_checkpoint["proposal_ranking_identity"], source_sha256="0" * 64
        )
        with self.assertRaises(Exception):
            replay_micro_batches(ranking_spec(), replay_checkpoint)

    def test_random_restart_cannot_activate_ranking(self) -> None:
        with self.assertRaises(ValueError):
            LaneSpec(
                lane_id="bad",
                campaign_id="ranking-test-campaign",
                target="erdos_gyarfas",
                algorithm="random_restart",
                graph_family="connected_cubic",
                seed=1,
                parameters={
                    "order": 14,
                    "batch_candidates": 100,
                    "witness_cap": 32,
                    "proposal_ranking": CATALOG_ID,
                },
                resource_share=1.0,
            ).validate()

    def test_replay_redteam_and_small_benchmark(self) -> None:
        records = build_replay_records(record_count=2_048)
        replay = run_replay(records)
        self.assertTrue(replay.passed, replay.as_dict())
        red_team = run_red_team()
        self.assertEqual(red_team["status"], "passed", red_team)
        benchmark = run_worker_benchmark(records[:1], calls=20)
        self.assertEqual(benchmark.failures, 0)
        self.assertEqual(benchmark.orphan_count, 0)

    def test_online_backup_migration_to_schema_18(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.sqlite3"
            target_path = Path(directory) / "snapshot.sqlite3"
            source = sqlite3.connect(source_path)
            source.executescript(BASE_SCHEMA_SQL)
            source.commit()
            migrate(source)
            source.execute("DROP TABLE IF EXISTS research_lane_policy_identities")
            source.execute("PRAGMA user_version=17")
            source.commit()
            target = sqlite3.connect(target_path)
            source.backup(target)
            target.commit()
            migrate(target)
            self.assertEqual(SCHEMA_VERSION, 18)
            self.assertEqual(target.execute("PRAGMA user_version").fetchone()[0], 18)
            self.assertEqual(target.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(target.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertIsNotNone(
                target.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='research_lane_policy_identities'"
                ).fetchone()
            )
            target.close()
            source.close()


if __name__ == "__main__":
    unittest.main()
