from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
import asyncio
import json
import tempfile
import unittest

from sglab.research.campaign import campaign_status, target_definition_sha256
from sglab.research.experiment import (
    OneBatchExperiment,
    _campaign_counts,
    _durable_feedback_proofs,
    _durable_outcomes,
    run_phase_a_audit,
)
from sglab.research.lanes import (
    LaneManager,
    LaneSpec,
    run_bounded_lane_batch,
)
from sglab.research.providers import ReplayDecisionProvider
from sglab.research.store import ResearchStore
from sglab.state import atomic_write_json
from sglab.web import create_server


def _common(action_id: str, action_type: str) -> dict:
    return {
        "action_id": action_id,
        "type": action_type,
        "priority": 50,
        "hypothesis_ids": [],
        "evidence_ids": [],
        "rationale": "Deterministic no-model integration evidence.",
        "expected_effect": "Measure one bounded search batch.",
        "evaluation_window": {
            "max_wall_seconds": 10,
            "max_candidate_delta": 300,
        },
        "idempotency_key": f"phase-a-{action_id}",
        "lease_seconds": 120,
        "fallback": {"on_precondition_failure": "reject"},
    }


def _first_decision(snapshot_id: str) -> dict:
    action = _common("phase-a-start", "start_lane")
    action["spec"] = {
        "algorithm": "simulated_annealing",
        "graph_family": "connected_cubic",
        "seed": 20260724,
        "parameters": {
            "order": 10,
            "batch_candidates": 300,
            "witness_cap": 16,
            "temperature": 1.0,
            "cooling": 0.995,
            "restart_threshold": 1000,
            "mutation_weights": {
                "uniform_two_edge_switch": 1,
                "forbidden_cycle_break_switch": 1,
            },
        },
        "resource_share": 1.0,
    }
    return {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "campaign_assessment": "Run one small deterministic replay batch.",
        "hypothesis_updates": [],
        "actions": [action],
        "next_review": {
            "min_wall_seconds": 10,
            "max_wall_seconds": 30,
            "candidate_delta": 300,
            "events": ["meaningful_improvement"],
        },
    }


def _second_decision(snapshot_id: str, evidence_id: str) -> dict:
    action = _common("phase-a-review", "set_review_trigger")
    action["evidence_ids"] = [evidence_id]
    action["review_trigger"] = {
        "min_wall_seconds": 10,
        "max_wall_seconds": 30,
        "candidate_delta": 300,
        "events": ["meaningful_improvement"],
    }
    return {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "campaign_assessment": (
            "CONTINUE: the measured replay outcome is available for the next "
            "decision, which remains undispatched."
        ),
        "hypothesis_updates": [],
        "actions": [action],
        "next_review": {
            "min_wall_seconds": 10,
            "max_wall_seconds": 30,
            "candidate_delta": 300,
            "events": ["meaningful_improvement"],
        },
    }


class OneBatchExperimentTests(unittest.TestCase):
    def test_adaptive_phase_a_runs_four_turns_three_batches_and_no_fourth(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report = run_phase_a_audit(root)
            store = ResearchStore(root / "results.sqlite3")
            campaign_dir = (
                root / "research-campaigns" / report["campaign_id"]
            )
            counts = _campaign_counts(store, report["campaign_id"])
            outcomes = _durable_outcomes(store, report["campaign_id"])
            proofs = _durable_feedback_proofs(
                store,
                campaign_dir,
                report["campaign_id"],
                outcomes,
            )
            store.close()
        self.assertTrue(report["ok"], report["failures"])
        self.assertEqual(
            report["counts"],
            {"turns": 4, "decision_batches": 4, "search_batches": 3},
        )
        self.assertTrue(report["decision_before_search"])
        self.assertTrue(report["outcomes_serialized_to_next_states"])
        self.assertEqual(len(set(report["thread_ids"])), 1)
        self.assertEqual(report["sqlite_integrity_check"], "ok")
        self.assertEqual(
            report["resume_safe_sequence_state"]["next_safe_transition"],
            "stop",
        )
        self.assertEqual(
            counts, {"turns": 4, "decisions": 4, "batches": 3}
        )
        self.assertEqual(len(outcomes), 3)
        self.assertEqual(proofs, [True] * 6)

    def test_every_allowed_experiment_algorithm_runs_one_bounded_batch(
        self,
    ) -> None:
        parameters = {
            "random_restart": {},
            "simulated_annealing": {
                "temperature": 1.0,
                "cooling": 0.995,
                "restart_threshold": 1000,
            },
            "iterated_local_search_tabu": {
                "tabu_tenure": 32,
                "perturbation_interval": 50,
            },
        }
        for algorithm, extras in parameters.items():
            with self.subTest(algorithm=algorithm):
                result = run_bounded_lane_batch(
                    LaneSpec(
                        lane_id=f"lane-{algorithm}",
                        campaign_id="algorithm-coverage",
                        target="erdos_gyarfas",
                        algorithm=algorithm,
                        graph_family="connected_cubic",
                        seed=17,
                        parameters={
                            "order": 10,
                            "batch_candidates": 100,
                            "witness_cap": 16,
                            **extras,
                        },
                        resource_share=1.0,
                    ),
                    max_evaluations=100,
                    max_wall_seconds=10,
                )
                self.assertEqual(result["evaluation_count"], 100)
                self.assertEqual(
                    result["termination_reason"], "evaluation_limit"
                )

    def test_replay_decision_batch_outcome_feedback_and_dashboard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            store = ResearchStore(workspace / "results.sqlite3")
            campaign_id = "phase-a-campaign"
            deadline = datetime.now(UTC) + timedelta(minutes=5)
            store.create_campaign(
                campaign_id=campaign_id,
                target="erdos_gyarfas",
                target_definition_sha256=target_definition_sha256(),
                stop_mode="time_limit",
                deadline_at=deadline.isoformat().replace("+00:00", "Z"),
            )
            campaign_dir = workspace / "research-campaigns" / campaign_id
            campaign_dir.mkdir(parents=True)
            manager = LaneManager(campaign_dir, max_active_lanes=1)
            replay = ReplayDecisionProvider(
                {},
                store=store,
                campaign_id=campaign_id,
            )
            experiment = OneBatchExperiment(
                store=store,
                manager=manager,
                provider=replay,
                campaign_id=campaign_id,
                campaign_dir=campaign_dir,
                evaluation_cap=500,
                wall_seconds_cap=10,
            )
            try:
                first_state = experiment.publish_state()
                first_snapshot = first_state[0]
                replay.decisions[first_snapshot["snapshot_id"]] = _first_decision(
                    first_snapshot["snapshot_id"]
                )
                first = asyncio.run(
                    experiment.request_first_decision(first_state)
                )
                persisted_action = json.loads(
                    store.connection.execute(
                        """
                        SELECT parameters_json FROM director_actions
                        WHERE action_id='phase-a-start'
                        """
                    ).fetchone()[0]
                )
                for field in (
                    "effective_parameters",
                    "ignored_parameters",
                    "rejected_parameters",
                    "parameter_effects",
                ):
                    self.assertIn(field, persisted_action)
                outcome = experiment.execute_one_batch(first)
                self.assertEqual(outcome["evaluation_count"], 300)
                self.assertEqual(
                    outcome["termination_reason"], "evaluation_limit"
                )
                self.assertGreater(outcome["throughput"], 0)
                self.assertGreater(
                    outcome["timing"]["counters_seconds"][
                        "sqlite_persistence"
                    ],
                    0,
                )
                persisted_metrics = json.loads(
                    store.connection.execute(
                        """
                        SELECT metrics_json FROM lane_metric_windows
                        WHERE metric_window_id=?
                        """,
                        (outcome["metric_window_id"],),
                    ).fetchone()[0]
                )
                self.assertGreater(
                    persisted_metrics["timing"]["counters_seconds"][
                        "sqlite_persistence"
                    ],
                    0,
                )
                self.assertEqual(
                    outcome["decision_before_search"][
                        "first_graph_evaluation_count"
                    ],
                    0,
                )
                second_state = experiment.publish_state()
                second_snapshot = second_state[0]
                observed = second_snapshot["recent_actions"][0]
                self.assertEqual(
                    observed["observed_effect"]["evaluation_count"], 300
                )
                replay.decisions[second_snapshot["snapshot_id"]] = (
                    _second_decision(
                        second_snapshot["snapshot_id"],
                        observed["evidence_id"],
                    )
                )
                second = asyncio.run(
                    experiment.request_second_decision(second_state)
                )
                self.assertEqual(first.thread_id, second.thread_id)

                self.assertEqual(
                    store.connection.execute(
                        "SELECT count(*) FROM director_action_batches"
                    ).fetchone()[0],
                    2,
                )
                self.assertEqual(
                    store.connection.execute(
                        "SELECT count(*) FROM lane_metric_windows"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    store.connection.execute(
                        "SELECT count(*) FROM research_lanes"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    store.connection.execute(
                        "PRAGMA integrity_check"
                    ).fetchone()[0],
                    "ok",
                )
                status = campaign_status(workspace, campaign_id)
                self.assertEqual(status["lanes"][0]["parameters"]["order"], 10)
                self.assertEqual(
                    status["lanes"][0]["telemetry_high_water"], 300
                )
                measured = next(
                    action
                    for action in status["actions"]
                    if action["action_id"] == "phase-a-start"
                )
                self.assertEqual(
                    measured["observed_effect"]["evaluation_count"], 300
                )

                atomic_write_json(
                    workspace / "active-research-campaign.json",
                    {
                        "campaign_id": campaign_id,
                        "campaign_dir": str(campaign_dir),
                    },
                )
                server = create_server(workspace, "127.0.0.1", 0)
                thread = Thread(target=server.serve_forever, daemon=True)
                thread.start()
                connection = HTTPConnection(*server.server_address, timeout=2)
                connection.request("GET", "/api/research-campaign")
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                dashboard = json.loads(response.read())
                self.assertEqual(
                    dashboard["assessment"]["decision_batch_id"],
                    second.decision_batch_id,
                )
                self.assertEqual(
                    dashboard["lanes"][0]["telemetry_high_water"], 300
                )
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
            finally:
                manager.shutdown()
                store.close()


if __name__ == "__main__":
    unittest.main()
