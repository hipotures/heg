import hashlib
import json
import tempfile
import unittest
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

from sglab.model import BitGraph
from sglab.research.store import ResearchStore
from sglab.research.protocol import canonical_json
from sglab.research.visualization import (
    DEFAULT_LIVE_FRONTIER_INTERVAL_SECONDS,
    VisualizationNotFoundError,
    VisualizationUnavailableError,
    campaign_graph_visualization,
    campaign_visualization_series,
)
from sglab.state import atomic_write_json
from sglab.web import create_server


CAMPAIGN_ID = "campaign-visualization-test"


class CampaignVisualizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.campaign_dir = (
            self.workspace / "research-campaigns" / CAMPAIGN_ID
        )
        atomic_write_json(
            self.workspace / "active-research-campaign.json",
            {"campaign_id": CAMPAIGN_ID},
        )
        self.first_graph = BitGraph.from_edges(
            4, {(0, 1), (1, 2), (2, 3), (3, 0)}
        )
        self.second_graph = BitGraph.from_edges(
            4,
            {
                (0, 1),
                (0, 2),
                (0, 3),
                (1, 2),
                (1, 3),
                (2, 3),
            },
        )
        with ResearchStore(self.workspace / "results.sqlite3") as store:
            store.create_campaign(
                campaign_id=CAMPAIGN_ID,
                target="erdos_gyarfas",
                target_definition_sha256="a" * 64,
                stop_mode="until_success",
                deadline_at=None,
            )
            for index in (1, 2):
                store.create_lane(
                    lane_id=f"lane-{index}",
                    campaign_id=CAMPAIGN_ID,
                    target="erdos_gyarfas",
                    parent_lane_id=None,
                    parent_checkpoint_ref=None,
                    action_id=f"action-{index}",
                    algorithm="random_restart",
                    graph_family="connected_cubic",
                    parameters={
                        "order": 4,
                        "batch_candidates": 100,
                        "witness_cap": 8,
                    },
                    seed_lineage=[index],
                    resource_share=0.5,
                    lease_expires_at=None,
                )
                store.mark_lane_running(f"lane-{index}")
            self._retain(
                store,
                "candidate-best",
                "lane-1",
                self.first_graph,
                [0, 1, 16, 0, 4],
                16,
            )
            self._retain(
                store,
                "candidate-running-m4",
                "lane-2",
                self.second_graph,
                [0, 3, 48, 0, 6],
                48,
            )
            store.record_lane_metric_window(
                metric_window_id="window-1",
                lane_id="lane-1",
                campaign_id=CAMPAIGN_ID,
                lane_version=0,
                start_high_water=0,
                end_high_water=100,
                started_at="2026-07-26T00:00:00Z",
                ended_at="2026-07-26T00:00:10Z",
                metrics={
                    "candidates_per_second": 10.0,
                    "best_scalar": 16,
                    "best_score": [0, 1, 16, 0, 4],
                    "diversity": 0.75,
                    "operator_yield": 0.05,
                    "plateau_evaluations": 20,
                },
            )
            self._verification_rows(store)
        self._write_manifest()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _retain(
        self,
        store: ResearchStore,
        candidate_id: str,
        lane_id: str,
        graph: BitGraph,
        ordering: list[int],
        penalty: int,
    ) -> None:
        graph6 = graph.to_graph6()
        graph_sha256 = hashlib.sha256(graph6.encode("ascii")).hexdigest()
        store.retain_campaign_candidate(
            candidate_id=candidate_id,
            campaign_id=CAMPAIGN_ID,
            lane_id=lane_id,
            lane_version=0,
            checkpoint_ref=f"checkpoints/{candidate_id}.json",
            graph6=graph6,
            graph_sha256=graph_sha256,
            score={
                "valid": True,
                "witness_counts": {"4": penalty // 16},
                "weighted_penalty": penalty,
                "complete": False,
                "ordering_key": ordering,
            },
            artifact_ref=f"candidates/{candidate_id}.graph6",
            artifact_sha256=hashlib.sha256(
                (graph6 + "\n").encode("ascii")
            ).hexdigest(),
        )

    def _verification_rows(self, store: ResearchStore) -> None:
        graph6 = self.second_graph.to_graph6()
        graph_sha256 = hashlib.sha256(graph6.encode("ascii")).hexdigest()
        now = "2026-07-26T00:01:00Z"
        with store.transaction() as database:
            database.execute(
                """
                INSERT INTO campaign_candidate_snapshots
                (candidate_snapshot_id, campaign_id, candidate_id, graph6,
                 graph_sha256, artifact_sha256, score_json, score_semantics,
                 lane_id, lane_version, checkpoint_ref,
                 certification_status, source_created_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, NULL, ?, ?)
                """,
                (
                    "snapshot-running-m4",
                    CAMPAIGN_ID,
                    "candidate-running-m4",
                    graph6,
                    graph_sha256,
                    "b" * 64,
                    json.dumps(
                        {
                            "weighted_penalty": 48,
                            "witness_counts": {"4": 3},
                            "complete": False,
                            "ordering_key": [0, 3, 48, 0, 6],
                        },
                        sort_keys=True,
                    ),
                    "heuristic_ordering_key_v1_not_certification",
                    "lane-2",
                    "checkpoints/candidate-running-m4.json",
                    now,
                    now,
                ),
            )
            database.execute(
                """
                INSERT INTO campaign_verification_jobs
                (verification_job_id, campaign_id, candidate_id, priority,
                 state, certification_artifact_ref, certification_status,
                 created_at, started_at, completed_at,
                 candidate_snapshot_id, execution_attempt_id)
                VALUES (?, ?, ?, 10, 'completed', ?, 'INVALID_CANDIDATE',
                        ?, ?, ?, NULL, NULL)
                """,
                (
                    "verification-completed",
                    CAMPAIGN_ID,
                    "candidate-best",
                    "verifications/verification-completed/manifest.json",
                    now,
                    now,
                    now,
                ),
            )
            database.execute(
                """
                INSERT INTO campaign_verification_jobs
                (verification_job_id, campaign_id, candidate_id, priority,
                 state, created_at, started_at, candidate_snapshot_id,
                 execution_attempt_id)
                VALUES (?, ?, ?, 20, 'running', ?, ?, ?, NULL)
                """,
                (
                    "verification-running",
                    CAMPAIGN_ID,
                    "candidate-running-m4",
                    now,
                    now,
                    "snapshot-running-m4",
                ),
            )

    def _write_manifest(self) -> None:
        graph6 = self.first_graph.to_graph6()
        atomic_write_json(
            self.campaign_dir
            / "verifications"
            / "verification-completed"
            / "manifest.json",
            {
                "status": "INVALID_CANDIDATE",
                "graph6_sha256": hashlib.sha256(
                    (graph6 + "\n").encode("ascii")
                ).hexdigest(),
                "verifiers": [
                    {
                        "implementation": "python-reference-dfs",
                        "status": "REJECTED",
                        "witnesses": [
                            {
                                "kind": "cycle_4",
                                "vertices": [0, 1, 2, 3],
                            }
                        ],
                    },
                    {
                        "implementation": "cpp17-bitset-dfs",
                        "status": "FOUND",
                        "length": 4,
                        "witness": [0, 1, 2, 3],
                    },
                ],
            },
        )

    def _write_live_checkpoint(
        self,
        *,
        graph: BitGraph,
        lane_id: str = "lane-2",
        high_water: int = 321,
    ) -> Path:
        graph6 = graph.to_graph6()
        payload = {
            "lane_id": lane_id,
            "lane_version": 3,
            "graph6": graph6,
            "score": {
                "valid": True,
                "witness_counts": {"4": 1},
                "weighted_penalty": 16,
                "novelty": 0.5,
                "simplicity": 4,
                "complete": False,
                "ordering_key": [0, 1, 16, 0, 4],
            },
            "best_graph6": graph6,
            "best_score": {
                "valid": True,
                "witness_counts": {"4": 1},
                "weighted_penalty": 16,
                "novelty": 0.5,
                "simplicity": 4,
                "complete": False,
                "ordering_key": [0, 1, 16, 0, 4],
            },
            "rng_state": "(3, (1, 2, 3), None)",
            "algorithm_evaluated": high_water,
            "stagnation": 9,
            "tabu": [],
            "parameters": {
                "order": graph.n,
                "batch_candidates": 100,
                "witness_cap": 8,
            },
            "high_water": high_water,
            "accepted_ancestry": [],
            "best_ancestry": [],
            "current_candidate_id": "candidate-live-frontier",
            "best_candidate_id": "candidate-live-frontier",
        }
        digest = hashlib.sha256(
            canonical_json(payload, max_bytes=1024 * 1024)
        ).hexdigest()
        checkpoint = {
            **payload,
            "checkpoint_id": f"checkpoint-{digest[:24]}",
            "sha256": digest,
        }
        path = (
            self.campaign_dir
            / "lane-checkpoints"
            / f"checkpoint-{digest[:24]}.json"
        )
        atomic_write_json(path, checkpoint)
        return path

    def _write_live_preview(
        self,
        *,
        graph: BitGraph,
        lane_id: str = "lane-2",
        high_water: int = 654,
    ) -> Path:
        payload = {
            "schema_version": 1,
            "lane_id": lane_id,
            "lane_version": 4,
            "graph6": graph.to_graph6(),
            "score": {
                "valid": True,
                "witness_counts": {"4": 1},
                "weighted_penalty": 16,
                "novelty": 0.5,
                "simplicity": graph.size(),
                "complete": False,
                "ordering_key": [0, 1, 16, 0, graph.size()],
            },
            "current_candidate_id": "candidate-live-preview",
            "high_water": high_water,
            "published_at": "2026-07-26T12:34:56Z",
            "transient": True,
        }
        digest = hashlib.sha256(
            canonical_json(payload, max_bytes=64 * 1024)
        ).hexdigest()
        preview = {
            **payload,
            "preview_id": f"live-frontier-{digest[:24]}",
            "sha256": digest,
        }
        path = (
            self.campaign_dir
            / "lane-checkpoints"
            / "live-frontier-lane-2.json"
        )
        atomic_write_json(path, preview)
        return path

    def test_global_lane_and_exact_witness_projection(self) -> None:
        global_best = campaign_graph_visualization(
            self.workspace, source="global_best"
        )
        self.assertEqual(
            global_best["selection"]["candidate_id"], "candidate-best"
        )
        self.assertEqual(global_best["graph"]["order"], 4)
        self.assertEqual(global_best["graph"]["size"], 4)
        self.assertEqual(
            global_best["cycle_examples"][0]["authority"],
            "heuristic_display_scan",
        )
        exact = global_best["exact_verification"]
        self.assertEqual(exact["integrity_status"], "verified")
        self.assertEqual(len(exact["witnesses"]), 2)
        self.assertEqual(exact["witnesses"][0]["vertices"], [0, 1, 2, 3])
        lane = campaign_graph_visualization(
            self.workspace, source="lane_best", lane_id="lane-2"
        )
        self.assertEqual(
            lane["selection"]["candidate_id"], "candidate-running-m4"
        )
        with self.assertRaises(VisualizationNotFoundError):
            campaign_graph_visualization(
                self.workspace, source="lane_best", lane_id="lane-missing"
            )

    def test_active_m4_uses_immutable_candidate_snapshot(self) -> None:
        replacement = BitGraph.from_edges(
            4, {(0, 1), (1, 2), (2, 0)}
        )
        with ResearchStore(self.workspace / "results.sqlite3") as store:
            store.connection.execute(
                """
                UPDATE campaign_candidates SET graph6=?, graph_sha256=?
                WHERE candidate_id='candidate-running-m4'
                """,
                (
                    replacement.to_graph6(),
                    hashlib.sha256(
                        replacement.to_graph6().encode("ascii")
                    ).hexdigest(),
                ),
            )
            store.connection.commit()
        selected = campaign_graph_visualization(
            self.workspace, source="m4_active"
        )
        self.assertEqual(
            selected["selection"]["candidate_snapshot_id"],
            "snapshot-running-m4",
        )
        self.assertEqual(selected["graph"]["size"], 6)

    def test_live_frontier_uses_verified_nonfollowed_lane_checkpoint(
        self,
    ) -> None:
        self._write_live_checkpoint(graph=self.second_graph)
        selected = campaign_graph_visualization(
            self.workspace,
            source="live_frontier",
            live_frontier_interval_seconds=17,
        )
        self.assertEqual(
            selected["selection"]["candidate_id"],
            "candidate-live-frontier",
        )
        self.assertEqual(selected["selection"]["lane_id"], "lane-2")
        self.assertEqual(selected["selection"]["high_water"], 321)
        self.assertTrue(selected["selection"]["transient"])
        self.assertEqual(selected["selection"]["state"], "live_frontier")
        self.assertEqual(selected["graph"]["size"], 6)
        self.assertFalse(
            selected["display_contract"][
                "live_frontier_is_certification"
            ]
        )
        self.assertEqual(
            selected["display_contract"][
                "live_frontier_interval_seconds"
            ],
            17,
        )
        self.assertEqual(DEFAULT_LIVE_FRONTIER_INTERVAL_SECONDS, 5)

    def test_live_frontier_prefers_transient_preview_and_falls_back(
        self,
    ) -> None:
        self._write_live_checkpoint(
            graph=self.first_graph, high_water=321
        )
        preview_path = self._write_live_preview(
            graph=self.second_graph, high_water=654
        )
        selected = campaign_graph_visualization(
            self.workspace, source="live_frontier"
        )
        self.assertEqual(
            selected["selection"]["candidate_id"],
            "candidate-live-preview",
        )
        self.assertEqual(selected["selection"]["high_water"], 654)
        self.assertEqual(
            selected["selection"]["published_at"],
            "2026-07-26T12:34:56Z",
        )
        preview_path.write_text("{}", encoding="utf-8")
        fallback = campaign_graph_visualization(
            self.workspace, source="live_frontier"
        )
        self.assertEqual(
            fallback["selection"]["candidate_id"],
            "candidate-live-frontier",
        )
        self.assertEqual(fallback["selection"]["high_water"], 321)

    def test_live_frontier_rejects_symlinked_checkpoint_directory(
        self,
    ) -> None:
        outside = self.workspace / "outside-checkpoints"
        outside.mkdir()
        checkpoint_dir = self.campaign_dir / "lane-checkpoints"
        checkpoint_dir.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_dir.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(VisualizationUnavailableError):
            campaign_graph_visualization(
                self.workspace, source="live_frontier"
            )

    def test_series_are_bounded_and_separate_scientific_semantics(self) -> None:
        series = campaign_visualization_series(self.workspace)
        self.assertEqual(len(series["candidate_history"]), 2)
        self.assertEqual(len(series["lane_windows"]), 1)
        self.assertEqual(len(series["verifications"]), 2)
        self.assertEqual(
            series["lane_windows"][0]["end_high_water"], 100
        )
        self.assertTrue(
            next(
                item
                for item in series["verifications"]
                if item["state"] == "running"
            )["immutable_snapshot"]
        )
        self.assertNotIn(
            "graph6", json.dumps(series, sort_keys=True).lower()
        )

    def test_manifest_escape_and_missing_active_m4_fail_safely(self) -> None:
        with ResearchStore(self.workspace / "results.sqlite3") as store:
            store.connection.execute(
                """
                UPDATE campaign_verification_jobs
                SET certification_artifact_ref='../outside.json'
                WHERE verification_job_id='verification-completed'
                """
            )
            store.connection.execute(
                """
                UPDATE campaign_verification_jobs SET state='completed'
                WHERE verification_job_id='verification-running'
                """
            )
            store.connection.commit()
        graph = campaign_graph_visualization(
            self.workspace, source="global_best"
        )
        self.assertEqual(
            graph["exact_verification"]["integrity_status"], "unavailable"
        )
        with self.assertRaises(VisualizationUnavailableError):
            campaign_graph_visualization(
                self.workspace, source="m4_active"
            )

    def test_visualization_http_endpoints_are_protected_and_bounded(self) -> None:
        self._write_live_checkpoint(graph=self.second_graph)
        server = create_server(
            self.workspace, "127.0.0.1", 0, token="visual-secret"
        )
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = HTTPConnection(*server.server_address, timeout=3)
        try:
            connection.request(
                "GET",
                "/api/research-campaign/visualization/graph"
                "?source=global_best",
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 401)
            response.read()
            headers = {"Authorization": "Bearer visual-secret"}
            connection.request(
                "GET",
                "/api/research-campaign/visualization/graph"
                "?source=global_best",
                headers=headers,
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            graph = json.loads(response.read())
            self.assertEqual(
                graph["selection"]["candidate_id"], "candidate-best"
            )
            self.assertNotIn(
                str(self.workspace.resolve()), json.dumps(graph)
            )
            connection.request(
                "GET",
                "/api/research-campaign/visualization/graph"
                "?source=live_frontier",
                headers=headers,
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            live = json.loads(response.read())
            self.assertTrue(live["selection"]["transient"])
            self.assertEqual(
                live["display_contract"][
                    "live_frontier_interval_seconds"
                ],
                5,
            )
            connection.request(
                "GET",
                "/api/research-campaign/visualization/series",
                headers=headers,
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            series = json.loads(response.read())
            self.assertEqual(len(series["candidate_history"]), 2)
            connection.request(
                "GET",
                "/api/research-campaign/visualization/graph"
                "?source=lane_best&lane_id=missing",
                headers=headers,
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 404)
            response.read()
            connection.request(
                "GET",
                "/observatory.js",
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            javascript = response.read()
            self.assertIn(b"createScientificObservatory", javascript)
            self.assertIn(b"Live search frontier", javascript)
            self.assertIn(b"Frontier paused", javascript)
            self.assertIn(
                b"DEFAULT_LIVE_FRONTIER_INTERVAL_SECONDS = 5",
                javascript,
            )
            self.assertIn(b"data-live-frontier-interval", javascript)
            self.assertIn(
                b"LIVE_FRONTIER_INTERVAL_SECONDS = [1, 2, 3, 4, 5]",
                javascript,
            )
            self.assertNotIn(b"last sample", javascript)
            self.assertNotIn(b"sampling \xc2\xb7 sample", javascript)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
