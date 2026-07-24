from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from sglab.cli import build_parser
from sglab.research.context_screen import (
    build_context_screen_prompt,
    decision_context_for_snapshot,
    prepare_context_screen_phase_a,
    run_authenticated_context_screen,
    semantic_decision_rubric,
)


def source_snapshot(snapshot_id: str, *, outcome: bool) -> dict:
    actions = []
    if outcome:
        actions.append(
            {
                "action_id": "source-action",
                "type": "start_lane",
                "expected_effect": "Reduce the heuristic witness score.",
                "previous_director_hypothesis_ids": ["source-hypothesis"],
                "expectation_met": False,
                "parameter_effects": {
                    "witness_cap": "Truncates heuristic witness counting."
                },
                "observed_effect": {
                    "action_id": "source-action",
                    "decision_batch_id": "source-batch",
                    "lane_id": "source-lane",
                    "algorithm": "simulated_annealing",
                    "graph_family": "connected_cubic",
                    "graph_order": 20,
                    "seed": 17,
                    "evaluation_count": 30_000,
                    "elapsed_seconds": 30.0,
                    "throughput": 1_000.0,
                    "best_evaluation": 20_000,
                    "plateau_evaluations": 10_000,
                    "accepted": 100,
                    "duplicates": 10,
                    "global_record_count": 8,
                    "diversity": 0.8,
                    "score_counts_truncated_by_witness_cap": True,
                    "best_score": {
                        "ordering_key": [0, 3, 48, 0, 30],
                        "witness_counts": {"4": 3},
                        "complete": False,
                    },
                    "plateau_signal": {
                        "remaining_evaluation_budget": 0,
                    },
                    "operator_statistics": {"mutation_operators": {}},
                    "timing": {
                        "search_loop_seconds": 30.0,
                        "counters_seconds": {"witness_counting": 28.0},
                    },
                    "mutation_ancestry": {
                        "global_record_improvements": [],
                        "final_best_ancestry": [],
                    },
                    "verifier_result": {
                        "status": "REJECTED",
                        "complete": True,
                        "implementation": "python-reference-dfs",
                        "message": "found a forbidden cycle of length 4",
                    },
                    "outcome_artifact_ref": "experiment/outcome.json",
                    "outcome_artifact_sha256": "b" * 64,
                    "termination_reason": "evaluation_limit",
                },
            }
        )
    return {
        "schema_version": "3.0",
        "snapshot_id": snapshot_id,
        "created_at": "2026-07-24T00:00:00Z",
        "campaign": {
            "campaign_id": "source-campaign",
            "state": "running",
            "state_version": 0,
            "stop_mode": "time_limit",
            "elapsed_seconds": 30,
            "remaining_seconds": 570,
        },
        "target": {
            "target_id": "erdos_gyarfas",
            "immutable_definition_hash": "a" * 64,
            "success_authority": "M4_independent_verifier",
        },
        "lanes": [],
        "hypotheses": [],
        "global_best": None,
        "recent_actions": actions,
        "available_evidence_ids": [],
    }


def create_preserved_source(root: Path) -> None:
    campaign_dir = root / "research-campaigns" / "source-campaign"
    request_dir = campaign_dir / "director" / "requests"
    request_dir.mkdir(parents=True)
    turn_ids = ["turn-a1", "turn-a2", "turn-a3", "turn-a4"]
    snapshots = {
        "turn-a1": source_snapshot("snapshot-a1", outcome=False),
        "turn-a2": source_snapshot("snapshot-a2", outcome=False),
        "turn-a3": source_snapshot("snapshot-a3", outcome=True),
        "turn-a4": source_snapshot("snapshot-a4", outcome=True),
    }
    for turn_id, snapshot in snapshots.items():
        (request_dir / f"{turn_id}.json").write_text(
            json.dumps(
                {
                    "prompt": json.dumps(
                        {"committed_research_snapshot": snapshot}
                    )
                }
            ),
            encoding="utf-8",
        )
    (root / "active-research-campaign.json").write_text(
        json.dumps({"campaign_dir": str(campaign_dir)}),
        encoding="utf-8",
    )
    (root / "ai-experiment-report.json").write_text(
        json.dumps(
            {
                "campaign_id": "source-campaign",
                "turn_record_ids": turn_ids,
                "model_inferences": 4,
                "search_batches": 3,
            }
        ),
        encoding="utf-8",
    )


def measurement_decision(snapshot_id: str) -> dict:
    review = {
        "min_wall_seconds": 30,
        "max_wall_seconds": 120,
        "candidate_delta": 1_000,
        "events": ["stagnation"],
    }
    return {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "campaign_assessment": (
            "The truncated heuristic counts are not an exact certification."
        ),
        "hypothesis_updates": [],
        "actions": [
            {
                "action_id": "measurement-review",
                "type": "set_review_trigger",
                "priority": 10,
                "hypothesis_ids": [],
                "evidence_ids": [],
                "rationale": "Retain an inert measurement recommendation.",
                "expected_effect": "No search is executed in this screen.",
                "evaluation_window": {
                    "max_wall_seconds": 120,
                    "max_candidate_delta": 1_000,
                },
                "idempotency_key": "measurement-review-key",
                "lease_seconds": 300,
                "fallback": {"on_precondition_failure": "reject"},
                "review_trigger": review,
            }
        ],
        "next_review": review,
    }


class ContextScreenTests(unittest.TestCase):
    def test_phase_a_has_exactly_four_bounded_no_search_slots(self) -> None:
        with (
            tempfile.TemporaryDirectory() as source_directory,
            tempfile.TemporaryDirectory() as output_directory,
        ):
            source = Path(source_directory)
            output = Path(output_directory)
            create_preserved_source(source)
            report = prepare_context_screen_phase_a(
                output, source_workspace=source
            )
            self.assertTrue(report["ok"])
            self.assertEqual(report["inference_slots"], ["P1", "P2", "S1", "S2"])
            self.assertEqual(report["inference_slot_count"], 4)
            self.assertFalse(report["fifth_inference_slot_exists"])
            self.assertEqual(report["search_batch_slots"], 0)
            self.assertEqual(report["compaction_operations_scheduled"], 0)
            self.assertTrue(report["deterministic_test_flake_fixed"])
            self.assertTrue(
                all(
                    request["measurement_only"]
                    and not request["dispatch_scheduled"]
                    for request in report["requests"]
                )
            )
            self.assertTrue(
                all(report["pairwise_identical_inputs"].values())
            )
            self.assertFalse(
                (
                    output
                    / ".sglab"
                    / "director"
                    / "codex-home"
                    / "auth.json"
                ).exists()
            )

    def test_semantic_rubric_rejects_prohibited_claims(self) -> None:
        snapshot = source_snapshot("snapshot-a4", outcome=True)
        valid = measurement_decision("snapshot-a4")
        context = decision_context_for_snapshot(snapshot)
        accepted = semantic_decision_rubric(
            valid, snapshot=snapshot, context=context
        )
        self.assertTrue(accepted["ok"], accepted)
        invalid = measurement_decision("snapshot-a4")
        invalid["campaign_assessment"] = (
            "This is a counterexample; execute shell command and write a file."
        )
        rejected = semantic_decision_rubric(
            invalid, snapshot=snapshot, context=context
        )
        self.assertFalse(rejected["ok"])
        self.assertFalse(
            rejected["checks"]["no_counterexample_claim"]
        )
        self.assertFalse(
            rejected["checks"]["no_code_tool_file_or_shell_request"]
        )

    def test_run_refuses_before_per_arm_auth_import(self) -> None:
        with (
            tempfile.TemporaryDirectory() as source_directory,
            tempfile.TemporaryDirectory() as output_directory,
        ):
            source = Path(source_directory)
            output = Path(output_directory)
            create_preserved_source(source)
            prepare_context_screen_phase_a(output, source_workspace=source)
            with self.assertRaisesRegex(RuntimeError, "auth is not imported"):
                run_authenticated_context_screen(
                    output,
                    source_workspace=source,
                    codex="must-not-start",
                )
            self.assertFalse(
                (output / "arms" / "persistent" / "results.sqlite3").exists()
            )

    def test_prompt_contains_only_v2_scientific_state(self) -> None:
        prompt = json.loads(
            build_context_screen_prompt(
                source_snapshot("snapshot-a1", outcome=False)
            )
        )
        self.assertIn("director_state_v2", prompt)
        self.assertNotIn("committed_research_snapshot", prompt)
        self.assertTrue(
            prompt["measurement_contract"]["measurement_only"]
        )
        self.assertEqual(prompt["measurement_contract"]["search_batches"], 0)

    def test_cli_exposes_separate_phase_a_and_run_commands(self) -> None:
        parser = build_parser()
        phase_a = parser.parse_args(
            [
                "ai-experiment",
                "context-screen-phase-a",
                "--workspace",
                "/tmp/screen",
                "--source-workspace",
                "/tmp/source",
            ]
        )
        self.assertEqual(
            phase_a.ai_experiment_command, "context-screen-phase-a"
        )
        run = parser.parse_args(
            [
                "ai-experiment",
                "context-screen-run",
                "--workspace",
                "/tmp/screen",
                "--source-workspace",
                "/tmp/source",
            ]
        )
        self.assertEqual(run.ai_experiment_command, "context-screen-run")


if __name__ == "__main__":
    unittest.main()
