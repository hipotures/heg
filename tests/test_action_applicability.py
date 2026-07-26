from __future__ import annotations

from pathlib import Path
import hashlib
import json
import tempfile
import unittest

from sglab.research.context import (
    evidence_registry_ids,
    prepare_director_state_v2,
)
from sglab.research.context_screen import (
    build_context_screen_prompt,
    decision_context_for_snapshot,
)
from sglab.research.protocol import (
    director_decision_schema,
)
from sglab.research.store import ResearchStore
from sglab.research.validation import validate_decision
from sglab.state import atomic_write_json


def snapshot(*, active: bool) -> dict:
    lanes = [
        {
            "lane_id": "lane-active",
            "lane_version": 4,
            "state": "running" if active else "stopped",
            "algorithm": "simulated_annealing",
        },
        {
            "lane_id": "lane-history",
            "lane_version": 2,
            "state": "stopped",
            "algorithm": "iterated_local_search_tabu",
        },
    ]
    return {
        "schema_version": "3.0",
        "snapshot_id": "snapshot-applicability",
        "created_at": "2026-07-24T00:00:00Z",
        "campaign": {
            "campaign_id": "campaign-applicability",
            "state": "running",
            "state_version": 1,
            "stop_mode": "time_limit",
            "elapsed_seconds": 1,
            "remaining_seconds": 300,
        },
        "target": {
            "target_id": "erdos_gyarfas",
            "immutable_definition_hash": "a" * 64,
            "success_authority": "M4_independent_verifier",
        },
        "resources": {"max_active_lanes": 2},
        "lanes": lanes,
        "global_best": None,
        "recent_actions": [],
        "hypotheses": [],
        "available_evidence_ids": [],
    }


def stop_decision(lane_id: str, version: int) -> dict:
    return {
        "schema_version": "1.0",
        "snapshot_id": "snapshot-applicability",
        "campaign_assessment": "Stop the selected active lane.",
        "hypothesis_updates": [],
        "actions": [
            {
                "action_id": "action-stop",
                "type": "stop_lane",
                "priority": 50,
                "hypothesis_ids": [],
                "evidence_ids": [],
                "rationale": "The active lane has completed its useful work.",
                "expected_effect": "Release the lane resource allocation.",
                "evaluation_window": {
                    "max_wall_seconds": 30,
                    "max_candidate_delta": 100,
                },
                "idempotency_key": "stop-active-lane",
                "lease_seconds": 60,
                "fallback": {"on_precondition_failure": "reject"},
                "lane_id": lane_id,
                "expected_lane_version": version,
            }
        ],
        "next_review": {
            "min_wall_seconds": 30,
            "max_wall_seconds": 60,
            "candidate_delta": 100,
            "events": ["lane_failure"],
        },
    }


def decision_with_action(action: dict) -> dict:
    return {
        "schema_version": "1.0",
        "snapshot_id": "snapshot-applicability",
        "campaign_assessment": "Choose one applicable bounded action.",
        "hypothesis_updates": [],
        "actions": [action],
        "next_review": {
            "min_wall_seconds": 30,
            "max_wall_seconds": 60,
            "candidate_delta": 100,
            "events": ["lane_failure"],
        },
    }


def common_action(action_type: str) -> dict:
    return {
        "action_id": f"action-{action_type}",
        "type": action_type,
        "priority": 50,
        "hypothesis_ids": [],
        "evidence_ids": [],
        "rationale": "This action is applicable to the submitted state.",
        "expected_effect": "Produce one bounded observable state change.",
        "evaluation_window": {
            "max_wall_seconds": 30,
            "max_candidate_delta": 100,
        },
        "idempotency_key": f"applicable-{action_type}",
        "lease_seconds": 60,
        "fallback": {"on_precondition_failure": "reject"},
    }


def schema_actions(schema: dict) -> set[str]:
    return {
        str(variant["properties"]["type"]["const"])
        for variant in schema["properties"]["actions"]["items"]["anyOf"]
    }


class ActionApplicabilityTests(unittest.TestCase):
    def test_no_active_lane_keeps_history_as_evidence_but_hides_stop(self) -> None:
        source = snapshot(active=False)
        prepared = prepare_director_state_v2(source)
        action_space = prepared.state["allowed_action_space"]
        schema = director_decision_schema(action_space)
        prompt = json.loads(build_context_screen_prompt(source))
        context = decision_context_for_snapshot(source)

        self.assertNotIn("stop_lane", action_space["actions"])
        self.assertNotIn("stop_lane", schema_actions(schema))
        self.assertNotIn(
            "stop_lane",
            prompt["applicable_action_description"]["actions"],
        )
        self.assertIn("lane-history", context.evidence_ids)
        self.assertNotIn("lane-history", context.executable_target_ids)
        rejected = validate_decision(
            stop_decision("lane-history", 2), context
        )
        self.assertFalse(rejected.accepted)
        self.assertTrue(
            any(
                issue.path == "$.actions[0].type"
                and "not applicable" in issue.message
                for issue in rejected.issues
            )
        )

    def test_only_active_lane_is_an_executable_stop_target(self) -> None:
        source = snapshot(active=True)
        prepared = prepare_director_state_v2(source)
        action_space = prepared.state["allowed_action_space"]
        schema = director_decision_schema(action_space)
        context = decision_context_for_snapshot(source)

        self.assertIn("stop_lane", action_space["actions"])
        self.assertEqual(
            action_space["active_executable_lane_ids"], ["lane-active"]
        )
        self.assertEqual(
            next(
                variant
                for variant in schema["properties"]["actions"]["items"][
                    "anyOf"
                ]
                if variant["properties"]["type"]["const"] == "stop_lane"
            )["properties"]["lane_id"]["enum"],
            ["lane-active"],
        )
        accepted = validate_decision(
            stop_decision("lane-active", 4), context
        )
        self.assertTrue(accepted.accepted, accepted.issues)
        rejected = validate_decision(
            stop_decision("lane-history", 2), context
        )
        self.assertFalse(rejected.accepted)

    def test_status_transition_changes_action_and_registry_hashes(self) -> None:
        active = prepare_director_state_v2(snapshot(active=True))
        stopped = prepare_director_state_v2(snapshot(active=False))
        self.assertNotEqual(
            active.applicable_action_space_sha256,
            stopped.applicable_action_space_sha256,
        )
        self.assertNotEqual(
            active.executable_target_registry_sha256,
            stopped.executable_target_registry_sha256,
        )
        self.assertIn(
            "lane-active",
            evidence_registry_ids(active.executable_target_registry),
        )
        self.assertNotIn(
            "lane-active",
            evidence_registry_ids(stopped.executable_target_registry),
        )

    def test_measurement_contract_does_not_expand_or_execute_actions(self) -> None:
        source = snapshot(active=False)
        prompt = json.loads(build_context_screen_prompt(source))
        context = decision_context_for_snapshot(source)
        self.assertTrue(
            prompt["measurement_contract"]["measurement_only"]
        )
        self.assertNotIn("stop_lane", context.applicable_action_types)
        self.assertFalse(
            validate_decision(
                stop_decision("lane-history", 2), context
            ).accepted
        )
        self.assertEqual(source["lanes"][0]["state"], "stopped")

    def test_registry_round_trip_and_sqlite_reconstruction(self) -> None:
        source = snapshot(active=True)
        prepared = prepare_director_state_v2(source)
        rebuilt = prepare_director_state_v2(
            json.loads(json.dumps(source))
        )
        self.assertEqual(
            prepared.evidence_registry, rebuilt.evidence_registry
        )
        self.assertEqual(
            prepared.advisory_target_registry,
            rebuilt.advisory_target_registry,
        )
        self.assertEqual(
            prepared.executable_target_registry,
            rebuilt.executable_target_registry,
        )
        self.assertEqual(
            prepared.applicable_action_space_sha256,
            rebuilt.applicable_action_space_sha256,
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            request = {
                "evidence_registry": prepared.evidence_registry,
                "evidence_registry_sha256": (
                    prepared.evidence_registry_sha256
                ),
                "advisory_target_registry": (
                    prepared.advisory_target_registry
                ),
                "advisory_target_registry_sha256": (
                    prepared.advisory_target_registry_sha256
                ),
                "executable_target_registry": (
                    prepared.executable_target_registry
                ),
                "executable_target_registry_sha256": (
                    prepared.executable_target_registry_sha256
                ),
                "applicable_action_space": prepared.state[
                    "allowed_action_space"
                ],
                "applicable_action_space_sha256": (
                    prepared.applicable_action_space_sha256
                ),
            }
            request_path = root / "requests" / "turn.json"
            atomic_write_json(request_path, request)
            request_bytes = request_path.read_bytes().rstrip(b"\n")
            database = root / "results.sqlite3"
            with ResearchStore(database) as store:
                store.create_campaign(
                    campaign_id="campaign-applicability",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="until_success",
                    deadline_at=None,
                )
                store.record_snapshot(
                    snapshot_id="snapshot-applicability",
                    campaign_id="campaign-applicability",
                    campaign_state_version=0,
                    high_water={},
                    artifact_ref="snapshot.json",
                    artifact_sha256="b" * 64,
                    payload_bytes=1,
                )
                store.record_trigger(
                    trigger_id="trigger-applicability",
                    campaign_id="campaign-applicability",
                    campaign_state_version=0,
                    reasons=["test"],
                    first_event_at="2026-07-24T00:00:00Z",
                    snapshot_id="snapshot-applicability",
                )
                store.record_session(
                    record_id="session-applicability",
                    campaign_id="campaign-applicability",
                    thread_id="thread-applicability",
                    session_id="session-applicability",
                    thread_path="/private/opaque-rollout",
                    parent_thread_id=None,
                    model="test",
                    effort="low",
                    codex_version="test",
                    executable_sha256="c" * 64,
                    protocol_schema_sha256="d" * 64,
                )
                store.begin_turn(
                    turn_record_id="turn-applicability",
                    session_record_id="session-applicability",
                    campaign_id="campaign-applicability",
                    thread_id="thread-applicability",
                    snapshot_id="snapshot-applicability",
                    trigger_id="trigger-applicability",
                    request_artifact_ref="requests/turn.json",
                    request_sha256=hashlib.sha256(request_bytes).hexdigest(),
                    wire_artifact_ref="wire/turn.jsonl",
                    evidence_registry_artifact_ref="requests/turn.json",
                    evidence_registry_sha256=(
                        prepared.evidence_registry_sha256
                    ),
                )
            with ResearchStore(database) as reopened:
                row = reopened.connection.execute(
                    "SELECT request_artifact_ref FROM app_server_turns"
                ).fetchone()
                restored = json.loads(
                    (root / str(row["request_artifact_ref"])).read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(restored, request)
                self.assertEqual(
                    reopened.connection.execute(
                        "PRAGMA integrity_check"
                    ).fetchone()[0],
                    "ok",
                )

    def test_prompt_and_schema_name_the_same_applicable_actions(self) -> None:
        for source in (snapshot(active=False), snapshot(active=True)):
            prepared = prepare_director_state_v2(source)
            prompt = json.loads(build_context_screen_prompt(source))
            schema = director_decision_schema(
                prepared.state["allowed_action_space"]
            )
            prompt_actions = set(
                prompt["applicable_action_description"]["actions"]
            )
            output_actions = schema_actions(schema)
            self.assertEqual(prompt_actions, output_actions)
            for variant in schema["properties"]["actions"]["items"][
                "anyOf"
            ]:
                action = variant["properties"]["type"]["const"]
                if action in {
                    "patch_lane",
                    "fork_lane",
                    "restart_lane",
                    "stop_lane",
                }:
                    self.assertTrue(
                        variant["properties"]["lane_id"]["enum"]
                    )
                if action == "reallocate_resources":
                    lane_schema = variant["properties"]["allocations"][
                        "items"
                    ]["properties"]["lane_id"]
                    self.assertTrue(lane_schema["enum"])

    def test_every_reduced_screen_action_has_one_valid_output(self) -> None:
        source = snapshot(active=False)
        source["global_best"] = {
            "candidate_id": "candidate-best",
            "evidence_id": "candidate-summary:candidate-best",
            "lane_id": "lane-history",
            "score": {
                "ordering_key": [0, 3, 40, 0, 33],
                "witness_counts": {"4": 2, "8": 1},
                "complete": True,
            },
            "order": 22,
            "size": 33,
            "minimum_degree": 3,
            "checkpoint_id": "checkpoint-history",
            "certification_status": "not_submitted",
        }
        prepared = prepare_director_state_v2(source)
        context = decision_context_for_snapshot(source)
        actions = {
            "start_lane": {
                **common_action("start_lane"),
                "spec": {
                    "algorithm": "random_restart",
                    "graph_family": "connected_cubic",
                    "seed": 17,
                    "parameters": {
                        "order": 20,
                        "batch_candidates": 100,
                        "witness_cap": 64,
                    },
                    "resource_share": 1.0,
                },
            },
            "promote_candidate": {
                **common_action("promote_candidate"),
                "candidate_id": "candidate-best",
            },
            "request_diagnostic": {
                **common_action("request_diagnostic"),
                "diagnostic_type": "graph_invariants",
                "subject_ids": ["snapshot-applicability"],
            },
            "schedule_verification": {
                **common_action("schedule_verification"),
                "candidate_ids": ["candidate-best"],
                "verification_priority": 50,
            },
            "set_review_trigger": {
                **common_action("set_review_trigger"),
                "review_trigger": {
                    "min_wall_seconds": 30,
                    "max_wall_seconds": 60,
                    "candidate_delta": 100,
                    "events": ["lane_failure"],
                },
            },
        }
        self.assertEqual(
            set(prepared.state["allowed_action_space"]["actions"]),
            set(actions),
        )
        for action_type, action in actions.items():
            validation = validate_decision(
                decision_with_action(action), context
            )
            self.assertTrue(
                validation.accepted,
                (action_type, validation.issues),
            )

        invalid_verification = {
            **actions["schedule_verification"],
            "candidate_ids": ["candidate-best-truncated"],
        }
        rejected = validate_decision(
            decision_with_action(invalid_verification), context
        )
        self.assertFalse(rejected.accepted)
        self.assertTrue(
            any(
                issue.path == "$.actions[0].candidate_ids[0]"
                and issue.message == "is not an admissible retained candidate"
                for issue in rejected.issues
            )
        )
