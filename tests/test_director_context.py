from __future__ import annotations

from pathlib import Path
import copy
import json
import tempfile
import unittest

from sglab.research.app_server_client import (
    AppServerSession,
    AppServerTurnResult,
    AppServerUsage,
)
from sglab.research.context import (
    ANCESTRY_MAX_BYTES,
    CLIENT_ESTIMATED_TOKENS_MAX,
    DIRECTOR_STATE_MAX_BYTES,
    HISTORICAL_OUTCOMES_MAX_BYTES,
    DirectorContextBudgetExceeded,
    DirectorContextMode,
    complete_context_size_report,
    director_state_v2_schema,
    evidence_registry_ids,
    prepare_director_state_v2,
)
from sglab.research.director import (
    ActiveDirector,
    base_instructions,
    build_director_prompt,
)
from sglab.research.protocol import (
    action_identity_contract,
    canonical_json,
    director_decision_schema,
)
from sglab.research.store import ResearchStore
from sglab.research.validation import DecisionContext


def ancestry_record(index: int) -> dict:
    return {
        "candidate_id": f"candidate-{index}",
        "parent_candidate_id": f"candidate-{index - 1}",
        "mutation_operator": "uniform_two_edge_switch",
        "evaluation": index,
        "accepted": True,
        "global_record": True,
        "mutated_edges": {
            "removed": [[0, 1], [2, 3]],
            "added": [[0, 2], [1, 3]],
        },
        "score_before": [0, index + 1, 16, 0, 30],
        "score_after": [0, index, 16, 0, 30],
        "witness_counts_before": {"4": index + 1},
        "witness_counts_after": {"4": index},
    }


def batch_action(index: int) -> dict:
    records = [ancestry_record(value) for value in range(16)]
    digest = f"{index:064x}"
    return {
        "action_id": f"A{index}",
        "type": "start_lane",
        "expected_effect": f"signal-{index}",
        "previous_director_hypothesis_ids": [f"H{index}"],
        "parameter_effects": {
            "witness_cap": "Bounded witness enumeration."
        },
        "expectation_met": index % 2 == 0,
        "observed_effect": {
            "action_id": f"A{index}",
            "decision_batch_id": f"decision-{index}",
            "lane_id": f"lane-{index}",
            "algorithm": "iterated_local_search_tabu",
            "graph_family": "connected_cubic",
            "graph_order": 20,
            "seed": index,
            "evaluation_count": 10_000,
            "elapsed_seconds": 10.0,
            "throughput": 1_000.0,
            "best_evaluation": index,
            "plateau_evaluations": 10_000 - index,
            "accepted": 100,
            "duplicates": 10,
            "global_record_count": 16,
            "diversity": 0.99,
            "score_counts_truncated_by_witness_cap": True,
            "initial_score": {
                "ordering_key": [0, 64, 512, 0, 30],
                "witness_counts": {"4": 64},
                "complete": False,
            },
            "best_score": {
                "ordering_key": [0, 3, 48, 0, 30],
                "witness_counts": {"4": 3},
                "complete": True,
            },
            "plateau_signal": {
                "evaluations_since_last_global_record": 9000,
                "accepted_moves_since_last_global_record": 90,
                "diversity": 0.99,
                "remaining_evaluation_budget": max(0, 1_000_000-index*10_000),
            },
            "operator_statistics": {
                "mutation_operators": {
                    "uniform_two_edge_switch": {
                        "uses": 9000,
                        "accepted": 90,
                        "global_records": 7,
                    },
                    "forbidden_cycle_break_switch": {
                        "uses": 1000,
                        "accepted": 10,
                        "global_records": 1,
                    },
                }
            },
            "timing": {
                "search_loop_seconds": 10.0,
                "counters_seconds": {
                    "witness_counting": 9.4,
                    "mutation_generation": 0.4,
                },
            },
            "mutation_ancestry": {
                "global_record_improvements": records,
                "final_best_ancestry": records,
            },
            "verifier_result": {
                "status": "REJECTED",
                "complete": True,
                "implementation": "python-reference-dfs",
                "message": "found a forbidden cycle of length 4",
            },
            "outcome_artifact_ref": f"experiment/outcome-{index}.json",
            "outcome_artifact_sha256": digest,
            "termination_reason": "evaluation_limit",
        },
    }


def snapshot(actions: list[dict] | None = None) -> dict:
    return {
        "schema_version": "3.0",
        "snapshot_id": "snapshot-context",
        "created_at": "2026-07-24T00:00:00Z",
        "campaign": {
            "campaign_id": "campaign-context",
            "state": "running",
            "state_version": 1,
            "stop_mode": "time_limit",
            "elapsed_seconds": 10,
            "remaining_seconds": 100,
        },
        "target": {
            "target_id": "erdos_gyarfas",
            "immutable_definition_hash": "a" * 64,
            "success_authority": "M4_independent_verifier",
        },
        "global_best": None,
        "recent_actions": actions or [],
        "available_evidence_ids": [],
    }


def client_limit_snapshot() -> dict:
    value = snapshot()
    value["resources"] = {"max_active_lanes": 16}
    value["lanes"] = [
        {
            "lane_id": f"lane-{index}",
            "lane_version": 0,
            "state": "running" if index < 7 else "stopped",
            "algorithm": "iterated_local_search",
            "checkpoint_id": (
                f"checkpoint-{index:02d}-" + "c" * 40
            ),
        }
        for index in range(13)
    ]
    value["continuity"] = {
        "current_executable_candidate_ids": [
            f"candidate-{index:02d}-" + "a" * 32
            for index in range(9)
        ],
        "current_executable_checkpoint_ids": [
            f"checkpoint-{index:02d}-" + "c" * 40
            for index in range(21)
        ],
        "hypothesis_ledger": [
            {
                "hypothesis_id": (
                    f"hypothesis-{index:02d}-" + "h" * 24
                ),
                "statement": "s" * 400,
                "status": "active",
            }
            for index in range(64)
        ],
        "candidate_ledger": [
            {
                "candidate_id": (
                    f"candidate-{index:02d}-" + "a" * 32
                ),
                "score": [0, index, 16, 0, 64],
                "lane_id": f"lane-{index % 7}",
            }
            for index in range(11)
        ],
        "lane_and_checkpoint_ledger": [
            {
                "lane_id": f"lane-{index}",
                "checkpoint_id": (
                    f"checkpoint-{index:02d}-" + "c" * 40
                ),
                "parameters": {"detail": "p" * 400},
            }
            for index in range(13)
        ],
        "explored_regions": [
            {"region_id": index, "summary": "e" * 400}
            for index in range(9)
        ],
        "unresolved_scientific_questions": [
            {"question_id": index, "text": "q" * 400}
            for index in range(11)
        ],
        "exact_verifier_outcomes": [
            {
                "candidate_id": "candidate-exact",
                "status": "INVALID_CANDIDATE",
            }
        ],
    }
    return value


class DirectorStateV2Tests(unittest.TestCase):
    def test_prompt_names_operation_specific_hypothesis_contract(self) -> None:
        payload = json.loads(build_director_prompt(snapshot([batch_action(1)])))
        contract = payload["hypothesis_update_contract"]
        self.assertEqual(
            contract["existing_submitted_hypothesis_ids"],
            ["H1"],
        )
        self.assertEqual(contract["create"]["operation"], "create")
        self.assertIn("unique", contract["create"]["hypothesis_id_rule"])
        self.assertIn("revise", contract["existing_operations"])
        self.assertIn("retain", contract["existing_operations"])
        self.assertIn(
            "existing submitted",
            contract["existing_hypothesis_id_rule"],
        )
        self.assertIn(
            "exact IDs",
            contract["evidence_reference_rule"],
        )
        self.assertIn(
            "never prose",
            contract["evidence_reference_rule"],
        )

    def test_schema_and_bounded_sections(self) -> None:
        prepared = prepare_director_state_v2(
            snapshot([batch_action(index) for index in range(10, 0, -1)])
        )
        state = prepared.state
        post = prepared.size_report["post_compaction"]
        self.assertEqual(state["schema_version"], "2.0")
        self.assertLessEqual(len(state["previous_outcomes"]), 2)
        self.assertLessEqual(
            len(state["ancestry"]["global_record_summaries"]), 8
        )
        self.assertLessEqual(
            len(state["ancestry"]["final_best_accepted_ancestors"]), 8
        )
        self.assertLessEqual(
            post["director_state_bytes"], DIRECTOR_STATE_MAX_BYTES
        )
        self.assertLessEqual(post["ancestry_bytes"], ANCESTRY_MAX_BYTES)
        self.assertLessEqual(
            post["historical_outcomes_bytes"],
            HISTORICAL_OUTCOMES_MAX_BYTES,
        )
        encoded = canonical_json(state, max_bytes=DIRECTOR_STATE_MAX_BYTES)
        for forbidden in (
            b"mutated_edges",
            b"graph6",
            b"checkpoint",
            b"rng_state",
            b"raw_outcome",
        ):
            self.assertNotIn(forbidden, encoded)
        schema = director_state_v2_schema()
        self.assertEqual(schema["properties"]["schema_version"]["const"], "2.0")
        documented = json.loads(
            (
                Path(__file__).resolve().parents[1]
                / "docs"
                / "reports"
                / "M6_DIRECTOR_STATE_V2_SCHEMA.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(documented, schema)

    def test_one_hundred_batches_have_bounded_non_linear_state(self) -> None:
        actions: list[dict] = []
        sizes = []
        for index in range(1, 101):
            actions.insert(0, batch_action(index))
            prepared = prepare_director_state_v2(snapshot(actions))
            post = prepared.size_report["post_compaction"]
            sizes.append(post["director_state_bytes"])
            self.assertEqual(post["outcome_count"], 3 if index >= 3 else index)
            self.assertLessEqual(post["director_state_bytes"], 32 * 1024)
            state_hashes = {
                value["sha256"]
                for value in prepared.state["artifact_references"]
                if value["kind"] == "batch_outcome"
            }
            self.assertEqual(
                state_hashes,
                {
                    action["observed_effect"]["outcome_artifact_sha256"]
                    for action in actions[:3]
                },
            )
            rebuilt = prepare_director_state_v2(
                json.loads(json.dumps(snapshot(actions)))
            )
            self.assertEqual(prepared.state, rebuilt.state)
        self.assertLessEqual(max(sizes[-20:]), max(sizes[:20]) + 1024)

    def test_all_modes_submit_same_scientific_state_and_budget(self) -> None:
        prepared = prepare_director_state_v2(
            snapshot([batch_action(3), batch_action(2), batch_action(1)])
        )
        prompt = json.dumps(
            {"director_state_v2": prepared.state},
            sort_keys=True,
            separators=(",", ":"),
        )
        reports = [
            complete_context_size_report(
                prepared,
                prompt=prompt,
                base_instructions=base_instructions(),
                output_schema=director_decision_schema(),
                mode=mode,
            )
            for mode in DirectorContextMode
        ]
        self.assertTrue(
            all(
                value["client_owned_estimated_tokens"]
                <= CLIENT_ESTIMATED_TOKENS_MAX
                for value in reports
            )
        )
        self.assertEqual(
            len(
                {
                    value["post_compaction"]["director_state_bytes"]
                    for value in reports
                }
            ),
            1,
        )

    def test_compact_action_space_preserves_reference_roles(self) -> None:
        prepared = prepare_director_state_v2(client_limit_snapshot())
        action_space = prepared.state["allowed_action_space"]
        self.assertNotIn("reference_objects", action_space)
        executable = evidence_registry_ids(
            prepared.executable_target_registry
        )
        advisory = evidence_registry_ids(
            prepared.advisory_target_registry
        )
        self.assertTrue(
            set(action_space["active_executable_lane_ids"])
            .union(action_space["candidate_target_ids"])
            .union(action_space["checkpoint_target_ids"])
            .issubset(executable)
        )
        self.assertTrue(
            set(action_space["historical_lane_ids"]).issubset(advisory)
        )
        self.assertTrue(
            set(action_space["historical_lane_ids"]).isdisjoint(
                executable
            )
        )


class ModeClient:
    def __init__(self, decision: dict | None = None):
        self.thread_count = 0
        self.compactions = 0
        self.turns = 0
        self.resumes = 0
        self.decision = decision
        self.prompts: list[str] = []
        self.wire_bytes = b'{"bounded":"wire"}\n'

    async def start(self) -> None:
        return None

    async def start_thread(self, _: str) -> AppServerSession:
        self.thread_count += 1
        return AppServerSession(
            thread_id=f"thread-{self.thread_count}",
            session_id=f"session-{self.thread_count}",
            thread_path=f"/private/thread-{self.thread_count}.jsonl",
            model="fake",
            effort="high",
            resumed=False,
            raw_thread={},
        )

    async def compact_thread(self, _: AppServerSession) -> dict:
        self.compactions += 1
        return {}

    async def resume_thread(
        self, thread_id: str, _: str
    ) -> AppServerSession:
        self.resumes += 1
        return AppServerSession(
            thread_id=thread_id,
            session_id=f"resumed-session-{self.resumes}",
            thread_path=f"/private/{thread_id}.jsonl",
            model="fake",
            effort="high",
            resumed=True,
            raw_thread={},
        )

    async def turn(self, session, prompt, **kwargs):
        self.turns += 1
        self.prompts.append(prompt)
        if self.decision is None:
            raise AssertionError("oversized context reached inference")
        return AppServerTurnResult(
            thread_id=session.thread_id,
            turn_id="turn-context-budget",
            status="completed",
            text=json.dumps(self.decision),
            parsed=self.decision,
            usage=AppServerUsage(
                10,
                0,
                5,
                0,
                15,
                {"totalTokens": 15},
            ),
            deltas=(),
            retrying_errors=(),
            raw_completed_turn={"status": "completed"},
            final_agent_item_id="item-context-budget",
        )

    async def close(self) -> None:
        return None


class ContextModeBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_restart_preserves_mode_specific_thread_semantics(
        self,
    ) -> None:
        for mode in DirectorContextMode:
            with (
                self.subTest(mode=mode),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                store = ResearchStore(root / "results.sqlite3")
                store.create_campaign(
                    campaign_id="campaign",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="time_limit",
                    deadline_at="2026-07-25T00:00:00Z",
                )
                client = ModeClient()
                director = ActiveDirector(
                    client=client,  # type: ignore[arg-type]
                    store=store,
                    campaign_id="campaign",
                    campaign_dir=root,
                    codex_version="0.145.0",
                    executable_sha256="c" * 64,
                    protocol_schema_sha256="d" * 64,
                    context_mode=mode,
                )
                session = await director.start(
                    resume_thread_id="prior-thread"
                )
                row = store.connection.execute(
                    """
                    SELECT thread_id, parent_thread_id, last_resumed_at,
                           context_mode
                    FROM app_server_sessions
                    """
                ).fetchone()
                self.assertEqual(row["context_mode"], mode.value)
                if mode is DirectorContextMode.STATELESS_TURNS:
                    self.assertEqual(client.resumes, 0)
                    self.assertEqual(client.thread_count, 1)
                    self.assertNotEqual(session.thread_id, "prior-thread")
                    self.assertEqual(row["parent_thread_id"], "prior-thread")
                    self.assertIsNone(row["last_resumed_at"])
                else:
                    self.assertEqual(client.resumes, 1)
                    self.assertEqual(client.thread_count, 0)
                    self.assertEqual(session.thread_id, "prior-thread")
                    self.assertIsNone(row["parent_thread_id"])
                    self.assertIsNotNone(row["last_resumed_at"])
                await director.close()
                store.close()

    async def test_oversized_context_aborts_before_boundary_or_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "results.sqlite3")
            store.create_campaign(
                campaign_id="campaign",
                target="erdos_gyarfas",
                target_definition_sha256="a" * 64,
                stop_mode="time_limit",
                deadline_at="2026-07-25T00:00:00Z",
            )
            store.record_snapshot(
                snapshot_id="snapshot",
                campaign_id="campaign",
                campaign_state_version=0,
                high_water={},
                artifact_ref="snapshots/snapshot.json",
                artifact_sha256="b" * 64,
                payload_bytes=2,
            )
            store.record_trigger(
                trigger_id="trigger",
                campaign_id="campaign",
                campaign_state_version=0,
                reasons=["bootstrap"],
                first_event_at="2026-07-24T00:00:00Z",
                snapshot_id="snapshot",
            )
            client = ModeClient()
            director = ActiveDirector(
                client=client,  # type: ignore[arg-type]
                store=store,
                campaign_id="campaign",
                campaign_dir=root,
                codex_version="0.145.0",
                executable_sha256="c" * 64,
                protocol_schema_sha256="d" * 64,
                context_mode=DirectorContextMode.COMPACTED_THREAD,
            )
            await director.start()
            current = snapshot()
            prompt = json.dumps(
                {
                    "director_state_v2": prepare_director_state_v2(
                        current
                    ).state,
                    "padding": "x" * (CLIENT_ESTIMATED_TOKENS_MAX * 4),
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            with self.assertRaises(DirectorContextBudgetExceeded):
                await director.request_decision_once(
                    snapshot=current,
                    trigger_id="trigger",
                    context=DecisionContext(
                        snapshot_id="snapshot-context",
                        evidence_ids=frozenset(),
                        lane_versions={},
                        lane_algorithms={},
                        checkpoint_ids=frozenset(),
                        candidate_ids=frozenset(),
                        hypothesis_ids=frozenset(),
                        max_active_lanes=1,
                    ),
                    prompt=prompt,
                )
            self.assertEqual(client.turns, 0)
            self.assertEqual(client.compactions, 0)
            reports = list(
                (root / "director" / "context-budgets").glob("*.json")
            )
            self.assertEqual(len(reports), 1)
            persisted = json.loads(reports[0].read_text(encoding="utf-8"))
            self.assertFalse(persisted["within_client_token_limit"])
            await director.close()
            store.close()

    async def test_total_request_limit_compacts_reducible_state_before_turn(
        self,
    ) -> None:
        current = client_limit_snapshot()
        initial = prepare_director_state_v2(current)
        initial_prompt = build_director_prompt(current)
        initial_hypotheses = evidence_registry_ids(
            initial.evidence_registry,
            kinds=frozenset({"hypothesis"}),
        )
        initial_report = complete_context_size_report(
            initial,
            prompt=initial_prompt,
            base_instructions=base_instructions(),
            output_schema=director_decision_schema(
                initial.state["allowed_action_space"],
                existing_hypothesis_ids=initial_hypotheses,
                action_id_prefix="action-test",
            ),
            mode=DirectorContextMode.STATELESS_TURNS,
        )
        self.assertFalse(initial_report["within_client_token_limit"])
        self.assertNotIn(
            "reference_objects", initial.state["allowed_action_space"]
        )

        decision = {
            "schema_version": "1.0",
            "snapshot_id": "snapshot-context",
            "campaign_assessment": "Continue bounded search.",
            "hypothesis_updates": [],
            "actions": [
                {
                    "action_id": (
                        action_identity_contract("snapshot-context")[
                            "recommended_prefix"
                        ]
                        + "-review"
                    ),
                    "type": "set_review_trigger",
                    "priority": 10,
                    "hypothesis_ids": [],
                    "evidence_ids": [],
                    "rationale": "Continue bounded observation.",
                    "expected_effect": "Review after another bounded window.",
                    "evaluation_window": {
                        "max_wall_seconds": 120,
                        "max_candidate_delta": 10000,
                    },
                    "idempotency_key": "context-budget-review",
                    "lease_seconds": 300,
                    "fallback": {
                        "on_precondition_failure": "reject"
                    },
                    "review_trigger": {
                        "min_wall_seconds": 30,
                        "max_wall_seconds": 120,
                        "candidate_delta": 10000,
                        "events": ["new_global_best"],
                    },
                }
            ],
            "next_review": {
                "min_wall_seconds": 30,
                "max_wall_seconds": 120,
                "candidate_delta": 10000,
                "events": ["new_global_best"],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "results.sqlite3")
            store.create_campaign(
                campaign_id="campaign",
                target="erdos_gyarfas",
                target_definition_sha256="a" * 64,
                stop_mode="time_limit",
                deadline_at="2026-07-25T00:00:00Z",
            )
            store.record_snapshot(
                snapshot_id="snapshot-context",
                campaign_id="campaign",
                campaign_state_version=0,
                high_water={},
                artifact_ref="snapshots/snapshot-context.json",
                artifact_sha256="b" * 64,
                payload_bytes=2,
            )
            store.record_trigger(
                trigger_id="trigger",
                campaign_id="campaign",
                campaign_state_version=0,
                reasons=["bootstrap"],
                first_event_at="2026-07-24T00:00:00Z",
                snapshot_id="snapshot-context",
            )
            client = ModeClient(decision)
            director = ActiveDirector(
                client=client,  # type: ignore[arg-type]
                store=store,
                campaign_id="campaign",
                campaign_dir=root,
                codex_version="0.145.0",
                executable_sha256="c" * 64,
                protocol_schema_sha256="d" * 64,
                context_mode=DirectorContextMode.STATELESS_TURNS,
            )
            await director.start()
            evidence = await director.request_decision_once(
                snapshot=current,
                trigger_id="trigger",
                context=DecisionContext(
                    snapshot_id="snapshot-context",
                    evidence_ids=frozenset(),
                    lane_versions={},
                    lane_algorithms={},
                    checkpoint_ids=frozenset(),
                    candidate_ids=frozenset(),
                    hypothesis_ids=frozenset(),
                    max_active_lanes=16,
                ),
                prompt=initial_prompt,
            )
            self.assertTrue(
                evidence.validation.accepted,
                evidence.validation.issues,
            )
            self.assertEqual(client.turns, 1)
            reports = list(
                (root / "director" / "context-budgets").glob("*.json")
            )
            self.assertEqual(len(reports), 1)
            persisted = json.loads(
                reports[0].read_text(encoding="utf-8")
            )
            self.assertTrue(persisted["within_client_token_limit"])
            self.assertTrue(
                persisted["client_limit_compaction_applied"]
            )
            self.assertTrue(
                persisted["client_limit_state_byte_targets"]
            )
            submitted = json.loads(client.prompts[0])[
                "director_state_v2"
            ]
            submitted_hypotheses = {
                item["hypothesis_id"]
                for item in submitted["continuity"][
                    "hypothesis_ledger"
                ]
            }
            self.assertEqual(
                submitted_hypotheses,
                {
                    f"hypothesis-{index:02d}-" + "h" * 24
                    for index in range(64)
                },
            )
            self.assertEqual(
                submitted["continuity"]["exact_verifier_outcomes"][0][
                    "candidate_id"
                ],
                "candidate-exact",
            )
            await director.close()
            store.close()

    async def test_modes_apply_only_at_completed_turn_boundaries(self) -> None:
        for mode in DirectorContextMode:
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                store = ResearchStore(root / "results.sqlite3")
                store.create_campaign(
                    campaign_id="campaign",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="time_limit",
                    deadline_at="2026-07-25T00:00:00Z",
                )
                store.record_snapshot(
                    snapshot_id="snapshot",
                    campaign_id="campaign",
                    campaign_state_version=0,
                    high_water={},
                    artifact_ref="snapshots/snapshot.json",
                    artifact_sha256="b" * 64,
                    payload_bytes=2,
                )
                store.record_trigger(
                    trigger_id="trigger",
                    campaign_id="campaign",
                    campaign_state_version=0,
                    reasons=["bootstrap"],
                    first_event_at="2026-07-24T00:00:00Z",
                    snapshot_id="snapshot",
                )
                client = ModeClient()
                director = ActiveDirector(
                    client=client,  # type: ignore[arg-type]
                    store=store,
                    campaign_id="campaign",
                    campaign_dir=root,
                    codex_version="0.145.0",
                    executable_sha256="c" * 64,
                    protocol_schema_sha256="d" * 64,
                    context_mode=mode,
                )
                await director.start()
                store.begin_turn(
                    turn_record_id="turn-record",
                    session_record_id=str(director.session_record_id),
                    campaign_id="campaign",
                    thread_id=str(director.session.thread_id),
                    snapshot_id="snapshot",
                    trigger_id="trigger",
                    request_artifact_ref="request.json",
                    request_sha256="e" * 64,
                    wire_artifact_ref="wire.jsonl",
                )
                store.complete_turn(
                    "turn-record",
                    turn_id="turn",
                    status="completed_valid",
                )
                await director._prepare_context_boundary()
                if mode is DirectorContextMode.PERSISTENT_THREAD:
                    self.assertEqual(client.thread_count, 1)
                    self.assertEqual(client.compactions, 0)
                elif mode is DirectorContextMode.COMPACTED_THREAD:
                    self.assertEqual(client.thread_count, 1)
                    self.assertEqual(client.compactions, 1)
                else:
                    self.assertEqual(client.thread_count, 2)
                    states = store.connection.execute(
                        """
                        SELECT state FROM app_server_sessions
                        ORDER BY started_at, rowid
                        """
                    ).fetchall()
                    self.assertEqual(
                        [value["state"] for value in states],
                        ["rolled_over", "active"],
                    )
                await director.close()
                store.close()
