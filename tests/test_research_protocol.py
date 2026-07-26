from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
import copy
import hashlib
import json
import stat
import tempfile
import unittest
from pathlib import Path

from sglab.research.app_server_client import (
    AppServerError,
    AppServerSession,
    AppServerTurnResult,
    AppServerUsage,
)
from sglab.research.director import ActiveDirector, build_director_prompt
from sglab.research.protocol import (
    action_identity_contract,
    director_decision_schema,
    hypothesis_updates_match_schema_contract,
)
from sglab.research.providers import ReplayDecisionProvider
from sglab.research.store import ResearchStore
from sglab.research.validation import DecisionContext, validate_decision


def valid_decision() -> dict:
    return {
        "schema_version": "1.0",
        "snapshot_id": "snapshot-1",
        "campaign_assessment": "Two complementary lanes should test the current bottleneck.",
        "hypothesis_updates": [
            {
                "hypothesis_id": "hyp-1",
                "operation": "create",
                "statement": "A lower annealing temperature may improve local exploitation.",
                "confidence": 0.5,
                "evidence_for": ["evidence-1"],
                "evidence_against": [],
            }
        ],
        "actions": [
            {
                "action_id": "action-start",
                "type": "start_lane",
                "priority": 80,
                "hypothesis_ids": ["hyp-1"],
                "evidence_ids": ["evidence-1"],
                "rationale": "Start a bounded exploitation lane.",
                "expected_effect": "Improve score slope within one window.",
                "evaluation_window": {
                    "max_wall_seconds": 120,
                    "max_candidate_delta": 10000,
                },
                "idempotency_key": "snapshot-1:start:1",
                "lease_seconds": 300,
                "fallback": {"on_precondition_failure": "replan"},
                "spec": {
                    "algorithm": "simulated_annealing",
                    "graph_family": "connected_cubic",
                    "seed": 17,
                    "parameters": {
                        "order": 32,
                        "batch_candidates": 1000,
                        "witness_cap": 64,
                        "temperature": 0.8,
                        "cooling": 0.999,
                    },
                    "resource_share": 0.5,
                },
            },
            {
                "action_id": "action-patch",
                "type": "patch_lane",
                "priority": 70,
                "hypothesis_ids": ["hyp-1"],
                "evidence_ids": ["evidence-1"],
                "rationale": "Test lower temperature on the existing lane.",
                "expected_effect": "Increase acceptance quality.",
                "evaluation_window": {
                    "max_wall_seconds": 120,
                    "max_candidate_delta": 10000,
                },
                "idempotency_key": "snapshot-1:patch:1",
                "lease_seconds": 300,
                "fallback": {"on_precondition_failure": "reject"},
                "lane_id": "lane-1",
                "expected_lane_version": 3,
                "patch": {"temperature": 0.5},
            },
        ],
        "next_review": {
            "min_wall_seconds": 30,
            "max_wall_seconds": 120,
            "candidate_delta": 10000,
            "events": ["new_global_best", "lane_failure"],
        },
    }


def context() -> DecisionContext:
    return DecisionContext(
        snapshot_id="snapshot-1",
        evidence_ids=frozenset({"evidence-1"}),
        lane_versions={"lane-1": 3},
        lane_algorithms={"lane-1": "simulated_annealing"},
        checkpoint_ids=frozenset({"checkpoint-1"}),
        candidate_ids=frozenset({"candidate-1"}),
    )


class ResearchProtocolTests(unittest.TestCase):
    def test_prompt_supplies_turn_scoped_action_identity_contract(self) -> None:
        prompt = json.loads(
            build_director_prompt(
                {
                    "schema_version": "3.0",
                    "snapshot_id": "snapshot-1",
                    "campaign": {"stop_mode": "time_limit"},
                    "target": {"target_id": "erdos_gyarfas"},
                    "recent_actions": [
                        {"action_id": "action-already-durable"}
                    ],
                }
            )
        )
        contract = prompt["action_identity_contract"]
        self.assertEqual(contract["scope"], "durable_workspace")
        self.assertTrue(contract["recommended_prefix"].startswith("action-"))
        self.assertIn(
            "action-already-durable",
            contract["recent_reserved_action_ids"],
        )

    def test_action_id_must_not_reuse_durable_workspace_identifier(
        self,
    ) -> None:
        decision = valid_decision()
        reserved = frozenset({"action-start"})
        result = validate_decision(
            decision,
            replace(context(), reserved_action_ids=reserved),
        )
        self.assertFalse(result.accepted)
        self.assertTrue(
            any(
                issue.path == "$.actions[0].action_id"
                and "durable workspace" in issue.message
                for issue in result.issues
            )
        )
        contract = action_identity_contract(
            "snapshot-1",
            recent_reserved_action_ids=reserved,
        )
        self.assertIn("action-start", contract["recent_reserved_action_ids"])
        schema = director_decision_schema(
            action_id_prefix=contract["recommended_prefix"]
        )
        description = schema["properties"]["actions"]["items"]["anyOf"][0][
            "properties"
        ]["action_id"]["description"]
        self.assertIn(contract["recommended_prefix"], description)

    def test_create_with_new_hypothesis_id(self) -> None:
        decision = valid_decision()
        result = validate_decision(decision, context())
        self.assertTrue(result.accepted, result.issues)
        self.assertTrue(
            hypothesis_updates_match_schema_contract(
                decision["hypothesis_updates"],
                frozenset(),
            )
        )

    def test_revise_with_existing_hypothesis_id(self) -> None:
        decision = valid_decision()
        update = decision["hypothesis_updates"][0]
        update["hypothesis_id"] = "hyp-existing"
        update["operation"] = "revise"
        for action in decision["actions"]:
            action["hypothesis_ids"] = ["hyp-existing"]
        existing = frozenset({"hyp-existing"})
        result = validate_decision(
            decision,
            replace(context(), hypothesis_ids=existing),
        )
        self.assertTrue(result.accepted, result.issues)
        self.assertTrue(
            hypothesis_updates_match_schema_contract(
                decision["hypothesis_updates"],
                existing,
            )
        )

    def test_revise_with_unknown_hypothesis_id(self) -> None:
        decision = valid_decision()
        update = decision["hypothesis_updates"][0]
        update["hypothesis_id"] = "H0"
        update["operation"] = "revise"
        result = validate_decision(decision, context())
        self.assertFalse(result.accepted)
        self.assertTrue(
            any(
                issue.path == "$.hypothesis_updates[0].hypothesis_id"
                and "existing hypothesis" in issue.message
                for issue in result.issues
            )
        )
        self.assertFalse(
            hypothesis_updates_match_schema_contract(
                decision["hypothesis_updates"],
                frozenset(),
            )
        )
        schema = director_decision_schema(
            existing_hypothesis_ids=frozenset()
        )
        branches = schema["properties"]["hypothesis_updates"]["items"][
            "anyOf"
        ]
        self.assertEqual(
            [
                branch["properties"]["operation"]["const"]
                for branch in branches
            ],
            ["create"],
        )

    def test_duplicate_create_is_invalid(self) -> None:
        decision = valid_decision()
        decision["hypothesis_updates"].append(
            copy.deepcopy(decision["hypothesis_updates"][0])
        )
        result = validate_decision(decision, context())
        self.assertFalse(result.accepted)
        self.assertTrue(
            any(
                issue.path == "$.hypothesis_updates[1].hypothesis_id"
                and issue.message == "already exists"
                for issue in result.issues
            )
        )

    def test_valid_batch_and_schema_are_bounded_json(self) -> None:
        result = validate_decision(valid_decision(), context())
        self.assertTrue(result.accepted, result.issues)
        schema = director_decision_schema()
        encoded = json.dumps(schema, sort_keys=True)
        self.assertIn('"additionalProperties": false', encoded)
        self.assertIn('"idempotency_key"', encoded)
        self.assertIn('"expected_lane_version"', encoded)
        self.assertNotIn('"command"', encoded)

    def test_parameter_semantics_are_normalized_and_unsupported_rejected(
        self,
    ) -> None:
        decision = valid_decision()
        parameters = decision["actions"][0]["spec"]["parameters"]
        parameters["mutation_weights"] = {
            "uniform_two_edge_switch": 2,
            "forbidden_cycle_break_switch": 1,
        }
        result = validate_decision(decision, context())
        self.assertTrue(result.accepted, result.issues)
        action = result.normalized["actions"][0]
        self.assertEqual(
            action["effective_parameters"]["mutation_weights"],
            {
                "uniform_two_edge_switch": 2 / 3,
                "forbidden_cycle_break_switch": 1 / 3,
            },
        )
        self.assertEqual(action["ignored_parameters"], {})
        self.assertEqual(action["rejected_parameters"], {})
        self.assertIn("mutation_weights", action["parameter_effects"])

        unsupported = valid_decision()
        unsupported["actions"][0]["spec"]["algorithm"] = (
            "iterated_local_search_tabu"
        )
        unsupported["actions"][0]["spec"]["parameters"] = {
            "order": 20,
            "batch_candidates": 300,
            "witness_cap": 64,
            "tabu_tenure": 48,
            "perturbation_interval": 200,
            "restart_threshold": 1500,
        }
        rejected = validate_decision(unsupported, context())
        self.assertFalse(rejected.accepted)
        self.assertTrue(
            any(
                issue.path.endswith(".restart_threshold")
                for issue in rejected.issues
            )
        )
        metadata = valid_decision()
        metadata["actions"][0]["spec"]["parameters"][
            "promotion_penalty"
        ] = 10
        self.assertFalse(validate_decision(metadata, context()).accepted)

    def test_structured_output_const_nodes_declare_their_type(self) -> None:
        schema = director_decision_schema()
        pending = [schema]
        while pending:
            node = pending.pop()
            if isinstance(node, dict):
                if "const" in node or "enum" in node:
                    self.assertIn("type", node, node)
                if node.get("type") == "object":
                    self.assertEqual(
                        set(node.get("properties", {})),
                        set(node.get("required", [])),
                        node,
                    )
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)
        encoded = json.dumps(schema, sort_keys=True)
        for unsupported in (
            '"exclusiveMinimum"',
            '"minProperties"',
            '"oneOf"',
            '"uniqueItems"',
        ):
            self.assertNotIn(unsupported, encoded)
        self.assertIn('"anyOf"', encoded)

    def test_nullable_transport_placeholders_are_normalized(self) -> None:
        decision = valid_decision()
        parameters = decision["actions"][0]["spec"]["parameters"]
        parameters.update(
            {
                "restart_threshold": None,
                "tabu_tenure": None,
                "perturbation_interval": None,
            }
        )
        decision["actions"][1]["patch"].update(
            {
                "cooling": None,
                "restart_threshold": None,
                "tabu_tenure": None,
                "perturbation_interval": None,
                "witness_cap": None,
                "batch_candidates": None,
            }
        )
        result = validate_decision(decision, context())
        self.assertTrue(result.accepted, result.issues)
        self.assertNotIn(
            "tabu_tenure",
            result.normalized["actions"][0]["spec"]["parameters"],
        )
        self.assertEqual(
            result.normalized["actions"][1]["patch"],
            {"temperature": 0.5},
        )

    def test_stale_unknown_and_arbitrary_fields_are_rejected(self) -> None:
        stale = valid_decision()
        stale["actions"][1]["expected_lane_version"] = 2
        result = validate_decision(stale, context())
        self.assertFalse(result.accepted)
        self.assertTrue(
            any("stale" in issue.message for issue in result.issues),
            result.issues,
        )

        arbitrary = valid_decision()
        arbitrary["actions"][0]["shell"] = "python dangerous.py"
        result = validate_decision(arbitrary, context())
        self.assertFalse(result.accepted)
        self.assertTrue(
            any(issue.path.endswith(".shell") for issue in result.issues),
            result.issues,
        )
        order_patch = valid_decision()
        order_patch["actions"][1]["patch"] = {"order": 34}
        result = validate_decision(order_patch, context())
        self.assertFalse(result.accepted)
        self.assertTrue(
            any(issue.path.endswith(".order") for issue in result.issues)
        )

    def test_evidence_id_and_resource_envelope_are_strict(self) -> None:
        unknown = valid_decision()
        unknown["actions"][0]["evidence_ids"] = ["invented"]
        result = validate_decision(unknown, context())
        self.assertFalse(result.accepted)
        self.assertTrue(
            any("not admissible" in issue.message for issue in result.issues)
        )

        allocation = copy.deepcopy(valid_decision())
        allocation["actions"] = [
            {
                **{
                    key: allocation["actions"][1][key]
                    for key in (
                        "priority",
                        "hypothesis_ids",
                        "evidence_ids",
                        "rationale",
                        "expected_effect",
                        "evaluation_window",
                        "lease_seconds",
                        "fallback",
                    )
                },
                "action_id": "allocate-1",
                "type": "reallocate_resources",
                "idempotency_key": "snapshot-1:allocate",
                "allocations": [
                    {
                        "lane_id": "lane-1",
                        "expected_lane_version": 3,
                        "resource_share": 1.1,
                    }
                ],
            }
        ]
        result = validate_decision(allocation, context())
        self.assertFalse(result.accepted)
        self.assertTrue(any("resource" in issue.path for issue in result.issues))


class ResearchStoreTests(unittest.TestCase):
    def test_action_id_collision_rejects_whole_batch_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.sqlite3"
            with ResearchStore(path) as store:
                store.create_campaign(
                    campaign_id="campaign-collision",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="time_limit",
                    deadline_at="2026-07-25T00:00:00Z",
                )

                first = valid_decision()
                for index, decision in enumerate(
                    (
                        first,
                        {
                            **copy.deepcopy(first),
                            "snapshot_id": "snapshot-2",
                        },
                    ),
                    start=1,
                ):
                    snapshot_id = f"snapshot-{index}"
                    trigger_id = f"trigger-{index}"
                    state_version = int(
                        store.campaign("campaign-collision")[
                            "state_version"
                        ]
                    )
                    store.record_snapshot(
                        snapshot_id=snapshot_id,
                        campaign_id="campaign-collision",
                        campaign_state_version=state_version,
                        high_water={},
                        artifact_ref=f"snapshots/{snapshot_id}.json",
                        artifact_sha256=str(index) * 64,
                        payload_bytes=100,
                    )
                    store.record_trigger(
                        trigger_id=trigger_id,
                        campaign_id="campaign-collision",
                        campaign_state_version=state_version,
                        reasons=["bootstrap"],
                        first_event_at="2026-07-24T00:00:00Z",
                        snapshot_id=snapshot_id,
                    )
                    if index == 2:
                        for action in decision["actions"]:
                            action["idempotency_key"] += ":new-turn"
                    session_record_id = f"session-record-{index}"
                    store.record_session(
                        record_id=session_record_id,
                        campaign_id="campaign-collision",
                        thread_id=f"thread-{index}",
                        session_id=f"session-{index}",
                        thread_path=f"/private/rollout-{index}.jsonl",
                        parent_thread_id=None,
                        model="replay",
                        effort="none",
                        codex_version="test",
                        executable_sha256="c" * 64,
                        protocol_schema_sha256="d" * 64,
                    )
                    turn = f"turn-record-{index}"
                    store.begin_turn(
                        turn_record_id=turn,
                        session_record_id=session_record_id,
                        campaign_id="campaign-collision",
                        thread_id=f"thread-{index}",
                        snapshot_id=snapshot_id,
                        trigger_id=trigger_id,
                        request_artifact_ref=f"turns/request-{index}.json",
                        request_sha256="e" * 64,
                        wire_artifact_ref=f"turns/wire-{index}.jsonl",
                    )
                    store.complete_turn(
                        turn,
                        turn_id=f"turn-{index}",
                        status="completed_valid",
                        response_artifact_ref=f"turns/response-{index}.json",
                        response_sha256="f" * 64,
                    )
                    statuses = store.commit_decision_batch(
                        decision_batch_id=f"batch-{index}",
                        campaign_id="campaign-collision",
                        snapshot_id=snapshot_id,
                        trigger_id=trigger_id,
                        turn_record_id=turn,
                        decision=decision,
                    )
                    if index == 1:
                        self.assertIn("accepted", statuses.values())
                    else:
                        self.assertEqual(
                            set(statuses.values()),
                            {"rejected_action_id_collision"},
                        )

                self.assertEqual(
                    store.connection.execute(
                        "SELECT count(*) FROM director_actions"
                    ).fetchone()[0],
                    2,
                )
                self.assertEqual(
                    store.connection.execute(
                        """
                        SELECT validation_status
                        FROM director_action_batches
                        WHERE decision_batch_id='batch-2'
                        """
                    ).fetchone()[0],
                    "rejected_action_id_collision",
                )

    def test_campaign_snapshot_session_and_turn_are_durable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "campaign.sqlite3"
            with ResearchStore(path) as store:
                store.create_campaign(
                    campaign_id="campaign-1",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="time_limit",
                    deadline_at="2026-07-25T00:00:00Z",
                )
                store.record_snapshot(
                    snapshot_id="snapshot-1",
                    campaign_id="campaign-1",
                    campaign_state_version=0,
                    high_water={"lane-1": 1},
                    artifact_ref="snapshots/snapshot-1.json",
                    artifact_sha256="b" * 64,
                    payload_bytes=100,
                )
                store.record_trigger(
                    trigger_id="trigger-1",
                    campaign_id="campaign-1",
                    campaign_state_version=0,
                    reasons=["bootstrap"],
                    first_event_at="2026-07-24T00:00:00Z",
                    snapshot_id="snapshot-1",
                )
                store.record_session(
                    record_id="session-record-1",
                    campaign_id="campaign-1",
                    thread_id="thread-1",
                    session_id="session-1",
                    thread_path="/private/rollout.jsonl",
                    parent_thread_id=None,
                    model="model",
                    effort="high",
                    codex_version="0.145.0",
                    executable_sha256="c" * 64,
                    protocol_schema_sha256="d" * 64,
                )
                resumed_record = store.record_session(
                    record_id="must-not-create-second-record",
                    campaign_id="campaign-1",
                    thread_id="thread-1",
                    session_id="session-1",
                    thread_path="/private/rollout.jsonl",
                    parent_thread_id=None,
                    model="model",
                    effort="high",
                    codex_version="0.145.0",
                    executable_sha256="c" * 64,
                    protocol_schema_sha256="d" * 64,
                    resumed=True,
                )
                self.assertEqual(resumed_record, "session-record-1")
                self.assertEqual(
                    store.connection.execute(
                        "SELECT count(*) FROM app_server_sessions"
                    ).fetchone()[0],
                    1,
                )
                store.begin_turn(
                    turn_record_id="turn-record-1",
                    session_record_id="session-record-1",
                    campaign_id="campaign-1",
                    thread_id="thread-1",
                    snapshot_id="snapshot-1",
                    trigger_id="trigger-1",
                    request_artifact_ref="turns/request.json",
                    request_sha256="e" * 64,
                    wire_artifact_ref="turns/wire.jsonl",
                )
                store.complete_turn(
                    "turn-record-1",
                    turn_id="turn-1",
                    status="completed",
                    response_artifact_ref="turns/response.json",
                    response_sha256="f" * 64,
                    wire_sha256="0" * 64,
                    usage={
                        "input_tokens": 10,
                        "cached_input_tokens": 3,
                        "cache_write_input_tokens": 4,
                        "output_tokens": 5,
                        "reasoning_output_tokens": 2,
                        "total_tokens": 15,
                        "raw": {"totalTokens": 15},
                    },
                    final_agent_item_id="item-1",
                    wall_seconds=1.25,
                )
                row = store.connection.execute(
                    "SELECT * FROM app_server_turns"
                ).fetchone()
                self.assertEqual(row["total_tokens"], 15)
                self.assertEqual(row["cache_write_input_tokens"], 4)
                self.assertEqual(row["final_agent_item_id"], "item-1")
                self.assertEqual(row["status"], "completed")
                store.complete_turn(
                    "turn-record-1",
                    turn_id="turn-1",
                    status="completed",
                )
                self.assertEqual(
                    store.connection.execute(
                        "SELECT count(*) FROM app_server_turns"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    store.connection.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )


class StubDecisionClient:
    def __init__(self, decisions: list[dict]):
        self.decisions = decisions
        self.wire_bytes = b'{"bounded":"wire"}\n'
        self.closed = False
        self.thread_count = 0

    async def start(self) -> None:
        return None

    async def start_thread(self, _: str) -> AppServerSession:
        self.thread_count += 1
        return AppServerSession(
            thread_id=f"thread-{self.thread_count}",
            session_id=f"session-{self.thread_count}",
            thread_path=f"/private/rollout-{self.thread_count}.jsonl",
            model="model",
            effort="high",
            resumed=False,
            raw_thread={},
            server_reported_model="model",
            server_reported_effort="high",
        )

    async def resume_thread(self, thread_id: str, _: str) -> AppServerSession:
        session = await self.start_thread("")
        return AppServerSession(
            thread_id=thread_id,
            session_id=session.session_id,
            thread_path=session.thread_path,
            model=session.model,
            effort=session.effort,
            resumed=True,
            raw_thread={},
        )

    async def turn(
        self,
        session,
        prompt,
        *,
        output_schema,
        on_event=None,
    ):
        decision = self.decisions.pop(0)
        return AppServerTurnResult(
            thread_id=session.thread_id,
            turn_id=f"turn-{len(self.decisions)}",
            status="completed",
            text=json.dumps(decision),
            parsed=decision,
            usage=AppServerUsage(
                10,
                3,
                5,
                2,
                15,
                {"totalTokens": 15},
                cache_write_input_tokens=4,
            ),
            deltas=(),
            retrying_errors=(),
            raw_completed_turn={"status": "completed"},
            final_agent_item_id="item-1",
        )

    async def close(self) -> None:
        self.closed = True


class ActiveDirectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_reserved_action_id_gets_one_fresh_repair_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            store.create_campaign(
                campaign_id="campaign-action-id-repair",
                target="erdos_gyarfas",
                target_definition_sha256="a" * 64,
                stop_mode="time_limit",
                deadline_at="2026-07-25T00:00:00Z",
            )
            snapshot = {
                "schema_version": "3.0",
                "snapshot_id": "snapshot-1",
                "campaign": {"stop_mode": "time_limit"},
                "target": {"target_id": "erdos_gyarfas"},
                "resources": {"max_active_lanes": 2},
                "lanes": [
                    {
                        "lane_id": "lane-1",
                        "lane_version": 3,
                        "state": "running",
                        "algorithm": "simulated_annealing",
                    }
                ],
                "available_evidence_ids": ["evidence-1"],
                "recent_actions": [{"action_id": "action-start"}],
            }
            store.record_snapshot(
                snapshot_id="snapshot-1",
                campaign_id="campaign-action-id-repair",
                campaign_state_version=0,
                high_water={},
                artifact_ref="snapshots/snapshot-1.json",
                artifact_sha256="b" * 64,
                payload_bytes=100,
            )
            store.record_trigger(
                trigger_id="trigger-1",
                campaign_id="campaign-action-id-repair",
                campaign_state_version=0,
                reasons=["bootstrap"],
                first_event_at="2026-07-24T00:00:00Z",
                snapshot_id="snapshot-1",
            )
            colliding = valid_decision()
            corrected = copy.deepcopy(colliding)
            for action in (colliding, corrected):
                action["hypothesis_updates"][0]["evidence_for"] = [
                    "snapshot-1"
                ]
                for item in action["actions"]:
                    item["evidence_ids"] = ["snapshot-1"]
            corrected["actions"][0]["action_id"] = "action-fixed-start"
            corrected["actions"][1]["action_id"] = "action-fixed-patch"
            client = StubDecisionClient([colliding, corrected])
            director = ActiveDirector(
                client=client,  # type: ignore[arg-type]
                store=store,
                campaign_id="campaign-action-id-repair",
                campaign_dir=root,
                codex_version="0.145.0",
                executable_sha256="c" * 64,
                protocol_schema_sha256="d" * 64,
            )
            try:
                await director.start()
                evidence = await director.request_decision(
                    snapshot=snapshot,
                    trigger_id="trigger-1",
                    context=replace(
                        context(),
                        reserved_action_ids=frozenset({"action-start"}),
                    ),
                )
                self.assertTrue(evidence.validation.accepted)
                self.assertEqual(len(evidence.turn_record_ids), 2)
                self.assertEqual(client.thread_count, 2)
                self.assertEqual(
                    [
                        row["status"]
                        for row in store.connection.execute(
                            """
                            SELECT status FROM app_server_turns
                            ORDER BY started_at, rowid
                            """
                        )
                    ],
                    ["completed_invalid", "completed_valid"],
                )
                self.assertEqual(
                    evidence.decision["actions"][0]["action_id"],
                    "action-fixed-start",
                )
            finally:
                await director.close()
                store.close()

    async def test_strict_campaign_model_contract_fails_before_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            store.create_campaign(
                campaign_id="campaign-contract",
                target="erdos_gyarfas",
                target_definition_sha256="a" * 64,
                stop_mode="time_limit",
                deadline_at="2026-07-25T00:00:00Z",
            )
            client = StubDecisionClient([valid_decision()])
            client.config = SimpleNamespace(
                model="gpt-5.6-luna",
                effort="high",
            )
            director = ActiveDirector(
                client=client,  # type: ignore[arg-type]
                store=store,
                campaign_id="campaign-contract",
                campaign_dir=root,
                codex_version="0.145.0",
                executable_sha256="c" * 64,
                protocol_schema_sha256="d" * 64,
                enforce_model_contract=True,
            )
            with self.assertRaisesRegex(
                AppServerError,
                "model contract mismatch",
            ):
                await director.start()
            self.assertEqual(
                store.connection.execute(
                    "SELECT count(*) FROM app_server_turns"
                ).fetchone()[0],
                0,
            )
            await director.close()
            store.close()

    async def test_single_turn_request_never_spends_a_repair_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            store.create_campaign(
                campaign_id="campaign-once",
                target="erdos_gyarfas",
                target_definition_sha256="a" * 64,
                stop_mode="time_limit",
                deadline_at="2026-07-25T00:00:00Z",
            )
            snapshot = {
                "schema_version": "3.0",
                "snapshot_id": "snapshot-once",
                "campaign": {"stop_mode": "time_limit"},
                "target": {"target_id": "erdos_gyarfas"},
                "available_evidence_ids": ["evidence-1"],
            }
            store.record_snapshot(
                snapshot_id="snapshot-once",
                campaign_id="campaign-once",
                campaign_state_version=0,
                high_water={},
                artifact_ref="snapshots/snapshot-once.json",
                artifact_sha256="b" * 64,
                payload_bytes=100,
            )
            store.record_trigger(
                trigger_id="trigger-once",
                campaign_id="campaign-once",
                campaign_state_version=0,
                reasons=["bootstrap"],
                first_event_at="2026-07-24T00:00:00Z",
                snapshot_id="snapshot-once",
            )
            client = StubDecisionClient([{"invalid": True}, valid_decision()])
            director = ActiveDirector(
                client=client,  # type: ignore[arg-type]
                store=store,
                campaign_id="campaign-once",
                campaign_dir=root,
                codex_version="0.145.0",
                executable_sha256="c" * 64,
                protocol_schema_sha256="d" * 64,
            )
            await director.start()
            evidence = await director.request_decision_once(
                snapshot=snapshot,
                trigger_id="trigger-once",
                context=context(),
            )
            self.assertFalse(evidence.validation.accepted)
            self.assertEqual(len(evidence.turn_record_ids), 1)
            self.assertEqual(len(client.decisions), 1)
            rows = store.connection.execute(
                "SELECT status FROM app_server_turns"
            ).fetchall()
            self.assertEqual(
                [row["status"] for row in rows], ["completed_invalid"]
            )
            await director.close()
            store.close()

    async def test_one_repair_turn_uses_fresh_stateless_thread(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            store.create_campaign(
                campaign_id="campaign-1",
                target="erdos_gyarfas",
                target_definition_sha256="a" * 64,
                stop_mode="time_limit",
                deadline_at="2026-07-25T00:00:00Z",
            )
            snapshot = {
                "schema_version": "3.0",
                "snapshot_id": "snapshot-1",
                "campaign": {"stop_mode": "time_limit"},
                "target": {"target_id": "erdos_gyarfas"},
                "resources": {"max_active_lanes": 2},
                "lanes": [
                    {
                        "lane_id": "lane-1",
                        "lane_version": 3,
                        "state": "running",
                        "algorithm": "simulated_annealing",
                    }
                ],
                "available_evidence_ids": ["evidence-1"],
            }
            store.record_snapshot(
                snapshot_id="snapshot-1",
                campaign_id="campaign-1",
                campaign_state_version=0,
                high_water={},
                artifact_ref="snapshots/snapshot-1.json",
                artifact_sha256="b" * 64,
                payload_bytes=100,
            )
            store.record_trigger(
                trigger_id="trigger-1",
                campaign_id="campaign-1",
                campaign_state_version=0,
                reasons=["bootstrap"],
                first_event_at="2026-07-24T00:00:00Z",
                snapshot_id="snapshot-1",
            )
            corrected = valid_decision()
            corrected["hypothesis_updates"][0]["evidence_for"] = [
                "snapshot-1"
            ]
            for action in corrected["actions"]:
                action["evidence_ids"] = ["snapshot-1"]
            client = StubDecisionClient([{"invalid": True}, corrected])
            director = ActiveDirector(
                client=client,  # type: ignore[arg-type]
                store=store,
                campaign_id="campaign-1",
                campaign_dir=root,
                codex_version="0.145.0",
                executable_sha256="c" * 64,
                protocol_schema_sha256="d" * 64,
            )
            await director.start()
            evidence = await director.request_decision(
                snapshot=snapshot,
                trigger_id="trigger-1",
                context=context(),
            )
            self.assertTrue(evidence.validation.accepted)
            self.assertEqual(len(evidence.turn_record_ids), 2)
            rows = store.connection.execute(
                """
                SELECT status, request_artifact_ref,
                       evidence_registry_artifact_ref,
                       evidence_registry_sha256
                FROM app_server_turns ORDER BY started_at, rowid
                """
            ).fetchall()
            self.assertEqual(
                [row["status"] for row in rows],
                ["completed_invalid", "completed_valid"],
            )
            for row in rows:
                registry_path = root / row[
                    "evidence_registry_artifact_ref"
                ]
                self.assertTrue(registry_path.is_file())
                self.assertEqual(
                    hashlib.sha256(
                        registry_path.read_bytes().rstrip(b"\n")
                    ).hexdigest(),
                    row["evidence_registry_sha256"],
                )
                request = json.loads(
                    (root / row["request_artifact_ref"]).read_text(
                        encoding="utf-8"
                    )
                )
                for role in (
                    "advisory_target_registry",
                    "executable_target_registry",
                ):
                    role_path = root / request[
                        f"{role}_artifact_ref"
                    ]
                    self.assertTrue(role_path.is_file())
                    self.assertEqual(
                        hashlib.sha256(
                            role_path.read_bytes().rstrip(b"\n")
                        ).hexdigest(),
                        request[f"{role}_sha256"],
                    )
                action_space_path = root / request[
                    "applicable_action_space_artifact_ref"
                ]
                self.assertTrue(action_space_path.is_file())
                self.assertEqual(
                    hashlib.sha256(
                        action_space_path.read_bytes().rstrip(b"\n")
                    ).hexdigest(),
                    request["applicable_action_space_sha256"],
                )
            statuses = store.commit_decision_batch(
                decision_batch_id="batch-1",
                campaign_id="campaign-1",
                snapshot_id="snapshot-1",
                trigger_id="trigger-1",
                turn_record_id=evidence.turn_record_ids[-1],
                decision=evidence.decision,
            )
            self.assertEqual(statuses["action-start"], "accepted")
            self.assertEqual(statuses["action-patch"], "rejected_stale_state")
            self.assertEqual(store.campaign("campaign-1")["state_version"], 1)
            self.assertEqual(client.thread_count, 2)
            self.assertFalse(director.rollover_due(maximum_turns=2))
            sessions = store.connection.execute(
                """
                SELECT thread_id, parent_thread_id, state
                FROM app_server_sessions ORDER BY started_at, rowid
                """
            ).fetchall()
            self.assertEqual(
                [tuple(row) for row in sessions],
                [
                    ("thread-1", None, "rolled_over"),
                    ("thread-2", "thread-1", "active"),
                ],
            )
            self.assertEqual(
                len(list((root / "director" / "rollovers").glob("*.json"))),
                0,
            )
            wire_dir = root / "director" / "wire"
            for index in range(70):
                retained = wire_dir / f"retention-{index:02d}.jsonl"
                retained.write_text(
                    "{}\n", encoding="utf-8"
                )
                retained.chmod(0o600)
            director._prune_wire_artifacts(maximum=64)
            self.assertEqual(len(list(wire_dir.glob("*.jsonl"))), 64)
            for path in (root / "director").glob("*/*"):
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            await director.close()
            self.assertTrue(client.closed)
            store.close()

    async def test_replay_provider_revalidates_recorded_decision(self) -> None:
        decision = valid_decision()
        provider = ReplayDecisionProvider({"snapshot-1": decision})
        evidence = await provider.decide(
            snapshot={"snapshot_id": "snapshot-1"},
            trigger_id="trigger-replay",
            context=context(),
        )
        self.assertTrue(evidence.validation.accepted)
        self.assertEqual(evidence.decision, decision)
        decision["actions"][0]["shell"] = "must not affect replay copy"
        self.assertNotIn("shell", evidence.decision["actions"][0])

    async def test_durable_replay_turn_is_commit_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ResearchStore(Path(directory) / "replay.sqlite3")
            try:
                store.create_campaign(
                    campaign_id="campaign-1",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="until_success",
                    deadline_at=None,
                )
                store.record_snapshot(
                    snapshot_id="snapshot-1",
                    campaign_id="campaign-1",
                    campaign_state_version=0,
                    high_water={},
                    artifact_ref="snapshots/snapshot-1.json",
                    artifact_sha256="b" * 64,
                    payload_bytes=100,
                )
                store.record_trigger(
                    trigger_id="trigger-replay",
                    campaign_id="campaign-1",
                    campaign_state_version=0,
                    reasons=["bootstrap"],
                    first_event_at="2026-07-24T00:00:00Z",
                    snapshot_id="snapshot-1",
                )
                provider = ReplayDecisionProvider(
                    {"snapshot-1": valid_decision()},
                    store=store,
                    campaign_id="campaign-1",
                )
                evidence = await provider.decide(
                    snapshot={"snapshot_id": "snapshot-1"},
                    trigger_id="trigger-replay",
                    context=context(),
                )
                statuses = store.commit_decision_batch(
                    decision_batch_id="batch-replay",
                    campaign_id="campaign-1",
                    snapshot_id="snapshot-1",
                    trigger_id="trigger-replay",
                    turn_record_id=evidence.turn_record_ids[-1],
                    decision=evidence.decision,
                )
                self.assertEqual(statuses["action-start"], "accepted")
                self.assertEqual(
                    store.connection.execute(
                        """
                        SELECT status FROM app_server_turns
                        WHERE turn_record_id='replay:trigger-replay'
                        """
                    ).fetchone()[0],
                    "completed_valid",
                )
            finally:
                store.close()
