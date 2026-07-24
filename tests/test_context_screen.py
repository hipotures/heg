from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from sglab.cli import build_parser
from sglab.research.context import prepare_director_state_v2
from sglab.research.context_screen import (
    SCREEN_EFFORT,
    SCREEN_MODEL,
    _run_screen_arms,
    build_context_screen_prompt,
    decision_context_for_snapshot,
    prepare_context_screen_phase_a,
    run_authenticated_context_screen,
    semantic_decision_rubric,
)
from sglab.research.validation import validate_decision


FAKE = Path(__file__).parent / "fixtures" / "fake_app_server.py"


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
    def test_phase_a_has_exactly_three_bounded_no_search_slots(self) -> None:
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
            self.assertEqual(report["inference_slots"], ["S2", "P1", "P2"])
            self.assertEqual(SCREEN_MODEL, "gpt-5.6-luna")
            self.assertEqual(SCREEN_EFFORT, "xhigh")
            self.assertEqual(
                report["runtime_contract"]["expected_model"],
                "gpt-5.6-luna",
            )
            self.assertEqual(
                report["runtime_contract"]["expected_reasoning_effort"],
                "xhigh",
            )
            self.assertEqual(report["inference_slot_count"], 3)
            self.assertFalse(report["fourth_inference_slot_exists"])
            self.assertEqual(report["search_batch_slots"], 0)
            self.assertEqual(report["lane_creation_slots"], 0)
            self.assertEqual(report["action_dispatch_slots"], 0)
            self.assertEqual(report["candidate_evaluation_slots"], 0)
            self.assertEqual(report["compaction_operations_scheduled"], 0)
            self.assertTrue(
                all(
                    request["measurement_only"]
                    and not request["dispatch_scheduled"]
                    for request in report["requests"]
                )
            )
            self.assertTrue(
                report["s2_p2_equivalence"]["all_equal"]
            )
            self.assertEqual(
                report["requests"][0]["slot"], "S2"
            )
            self.assertTrue(
                (output / "context-screen-equivalence.json").is_file()
            )
            for request in report["requests"]:
                self.assertLessEqual(request["director_state_bytes"], 32 * 1024)
                self.assertLessEqual(request["ancestry_bytes"], 8 * 1024)
                self.assertLessEqual(
                    request["historical_outcomes_bytes"], 12 * 1024
                )
                self.assertLessEqual(
                    request["client_owned_estimated_tokens"], 12_000
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

    def test_evidence_registry_matches_exact_submitted_v2(self) -> None:
        snapshot = source_snapshot("snapshot-visible", outcome=True)
        snapshot["available_evidence_ids"] = ["database-only-hidden"]
        prepared = prepare_director_state_v2(snapshot)
        rebuilt = prepare_director_state_v2(
            json.loads(json.dumps(snapshot))
        )
        self.assertEqual(
            prepared.evidence_registry, rebuilt.evidence_registry
        )
        self.assertEqual(
            prepared.evidence_registry_sha256,
            rebuilt.evidence_registry_sha256,
        )
        self.assertEqual(
            prepared.evidence_registry,
            json.loads(json.dumps(prepared.evidence_registry)),
        )
        context = decision_context_for_snapshot(snapshot)
        self.assertIn("snapshot-visible", context.evidence_ids)
        self.assertNotIn("database-only-hidden", context.evidence_ids)
        decision = measurement_decision("snapshot-visible")
        decision["actions"][0]["evidence_ids"] = ["snapshot-visible"]
        accepted = validate_decision(decision, context)
        self.assertTrue(accepted.accepted, accepted.issues)
        unknown = json.loads(json.dumps(decision))
        unknown["actions"][0]["evidence_ids"] = ["not-submitted"]
        rejected = validate_decision(unknown, context)
        self.assertFalse(rejected.accepted)
        self.assertIn(
            (
                "$.actions[0].evidence_ids[0]",
                "unknown reference 'not-submitted' is not admissible "
                "in this snapshot",
            ),
            {(issue.path, issue.message) for issue in rejected.issues},
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
            with self.assertRaisesRegex(ValueError, "between 1 and 300"):
                run_authenticated_context_screen(
                    output,
                    source_workspace=source,
                    codex="must-not-start",
                    turn_timeout_seconds=301,
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
        self.assertEqual(run.turn_timeout_seconds, 300.0)


class ContextScreenFailureTests(unittest.IsolatedAsyncioTestCase):
    def arm_result(self, mode: str, *, completed: bool) -> dict:
        return {
            "mode": mode,
            "turns": [],
            "completed": completed,
        }

    async def test_s2_failure_prevents_p1_and_p2(self) -> None:
        failed = AsyncMock(
            return_value=self.arm_result(
                "stateless_turns", completed=False
            )
        )
        with patch(
            "sglab.research.context_screen._run_screen_arm", failed
        ):
            stateless, persistent = await _run_screen_arms(
                arm_roots={
                    "persistent_thread": Path("/tmp/persistent"),
                    "stateless_turns": Path("/tmp/stateless"),
                },
                states={},
                codex="must-not-start",
                preflight={},
                protocol_hash="a" * 64,
                turn_timeout_seconds=10,
            )
        self.assertEqual(failed.await_count, 1)
        self.assertEqual(
            failed.await_args.kwargs["mode"],
            "stateless_turns",
        )
        self.assertFalse(stateless["completed"])
        self.assertEqual(persistent["failure"]["kind"], "not_started")

    async def test_successful_order_is_s2_then_p1_p2(self) -> None:
        completed = AsyncMock(
            side_effect=[
                self.arm_result("stateless_turns", completed=True),
                self.arm_result("persistent_thread", completed=True),
            ]
        )
        with patch(
            "sglab.research.context_screen._run_screen_arm", completed
        ):
            await _run_screen_arms(
                arm_roots={
                    "persistent_thread": Path("/tmp/persistent"),
                    "stateless_turns": Path("/tmp/stateless"),
                },
                states={},
                codex="must-not-start",
                preflight={},
                protocol_hash="a" * 64,
                turn_timeout_seconds=300,
            )
        self.assertEqual(completed.await_count, 2)
        self.assertEqual(
            completed.await_args_list[0].kwargs["slots"],
            (("S2", "A4"),),
        )
        self.assertEqual(
            completed.await_args_list[1].kwargs["slots"],
            (("P1", "A1"), ("P2", "A4")),
        )

    async def run_fake_screen(
        self, mode: str
    ) -> tuple[dict, dict]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            states = {
                "A1": source_snapshot("snapshot-a1", outcome=False),
                "A4": source_snapshot("snapshot-a4", outcome=True),
            }
            return await _run_screen_arms(
                arm_roots={
                    "stateless_turns": root / "stateless",
                    "persistent_thread": root / "persistent",
                },
                states=states,
                codex=(
                    sys.executable,
                    str(FAKE),
                    f"--fake-mode={mode}",
                ),
                preflight={
                    "codex_version_output": "fake",
                    "codex_executable_sha256": "a" * 64,
                },
                protocol_hash="b" * 64,
                turn_timeout_seconds=0.15,
                usage_wait_seconds=0.05,
                timeout_drain_seconds=0.05,
            )

    async def test_fake_server_success_is_three_measurements_only(self) -> None:
        stateless, persistent = await self.run_fake_screen(
            "director-screen-success"
        )
        self.assertTrue(stateless["completed"])
        self.assertTrue(persistent["completed"])
        turns = [*stateless["turns"], *persistent["turns"]]
        self.assertEqual([turn["slot"] for turn in turns], ["S2", "P1", "P2"])
        self.assertTrue(
            all(turn["measurement_only"] and not turn["executed"] for turn in turns)
        )
        self.assertEqual(
            stateless["turns"][0]["director_state_sha256"],
            persistent["turns"][1]["director_state_sha256"],
        )
        self.assertEqual(
            stateless["turns"][0]["evidence_registry_sha256"],
            persistent["turns"][1]["evidence_registry_sha256"],
        )
        self.assertEqual(
            persistent["turns"][0]["thread_id"],
            persistent["turns"][1]["thread_id"],
        )
        for arm in (stateless, persistent):
            self.assertEqual(arm["search_batches"], 0)
            self.assertEqual(arm["search_lanes"], 0)
            self.assertEqual(arm["action_dispatches"], 0)
            self.assertEqual(arm["candidate_evaluations"], 0)
            self.assertEqual(arm["compaction_operations"], 0)
            self.assertEqual(arm["sqlite_integrity_check"], "ok")

    async def test_p1_timeout_prevents_p2(self) -> None:
        stateless, persistent = await self.run_fake_screen(
            "director-screen-timeout-a1"
        )
        self.assertTrue(stateless["completed"])
        self.assertFalse(persistent["completed"])
        self.assertEqual(
            [turn["slot"] for turn in persistent["turns"]], ["P1"]
        )
        self.assertIn(
            persistent["turns"][0]["lifecycle_status"],
            {"timed_out", "aborted"},
        )

    async def test_s2_timeout_prevents_persistent_arm_start(self) -> None:
        stateless, persistent = await self.run_fake_screen(
            "director-screen-timeout-first"
        )
        self.assertFalse(stateless["completed"])
        self.assertEqual(
            [turn["slot"] for turn in stateless["turns"]], ["S2"]
        )
        self.assertEqual(persistent["failure"]["kind"], "not_started")

    async def test_model_contract_mismatch_stops_before_s2_inference(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            states = {
                "A1": source_snapshot("snapshot-a1", outcome=False),
                "A4": source_snapshot("snapshot-a4", outcome=True),
            }
            stateless, persistent = await _run_screen_arms(
                arm_roots={
                    "persistent_thread": root / "persistent",
                    "stateless_turns": root / "stateless",
                },
                states=states,
                codex=(
                    sys.executable,
                    str(FAKE),
                    "director-screen-model-mismatch",
                ),
                preflight={
                    "codex_version_output": "fake-codex 0",
                    "codex_executable_sha256": "a" * 64,
                },
                protocol_hash="b" * 64,
                turn_timeout_seconds=1,
                usage_wait_seconds=0.01,
                timeout_drain_seconds=0.05,
            )
        self.assertFalse(stateless["completed"])
        self.assertEqual(stateless["turns"], [])
        self.assertEqual(
            stateless["model_contract"]["model_contract_matched"], False
        )
        self.assertEqual(persistent["failure"]["kind"], "not_started")
        self.assertEqual(persistent["turns"], [])

    async def test_p2_timeout_and_late_abort_are_durable(self) -> None:
        stateless, persistent = await self.run_fake_screen(
            "director-screen-late-abort-second"
        )
        self.assertTrue(stateless["completed"])
        self.assertFalse(persistent["completed"])
        self.assertEqual(
            [turn["slot"] for turn in persistent["turns"]],
            ["P1", "P2"],
        )
        p2 = persistent["turns"][1]
        self.assertEqual(p2["lifecycle_status"], "aborted")
        self.assertFalse(p2["final_answer_presence"])
        self.assertFalse(p2["usage_presence"])
        self.assertIsNone(p2["usage"]["server_reported_total_tokens"])
        self.assertEqual(len(p2["reasoning_item_ids"]), 2)


if __name__ == "__main__":
    unittest.main()
