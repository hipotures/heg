from __future__ import annotations

import copy
import json
import stat
import tempfile
import unittest
from pathlib import Path

from sglab.research.app_server_client import (
    AppServerSession,
    AppServerTurnResult,
    AppServerUsage,
)
from sglab.research.director import ActiveDirector
from sglab.research.protocol import director_decision_schema
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
    def test_valid_batch_and_schema_are_bounded_json(self) -> None:
        result = validate_decision(valid_decision(), context())
        self.assertTrue(result.accepted, result.issues)
        schema = director_decision_schema()
        encoded = json.dumps(schema, sort_keys=True)
        self.assertIn('"additionalProperties": false', encoded)
        self.assertIn('"idempotency_key"', encoded)
        self.assertIn('"expected_lane_version"', encoded)
        self.assertNotIn('"command"', encoded)

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
                with self.assertRaisesRegex(RuntimeError, "duplicated"):
                    store.complete_turn(
                        "turn-record-1",
                        turn_id="turn-1",
                        status="completed",
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

    async def turn(self, session, prompt, *, output_schema):
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
    async def test_one_repair_turn_uses_same_snapshot_and_private_artifacts(self) -> None:
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
            client = StubDecisionClient([{"invalid": True}, valid_decision()])
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
                "SELECT status FROM app_server_turns ORDER BY started_at, rowid"
            ).fetchall()
            self.assertEqual(
                [row["status"] for row in rows],
                ["completed_invalid", "completed_valid"],
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
            self.assertTrue(director.rollover_due(maximum_turns=2))
            rolled = await director.rollover()
            self.assertEqual(rolled.thread_id, "thread-2")
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
                1,
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
