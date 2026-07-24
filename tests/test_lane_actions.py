from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from sglab.research.actions import LaneActionDispatcher
from sglab.research.lanes import LaneManager
from sglab.research.store import ResearchStore


def common(action_id: str, action_type: str, priority: int = 70) -> dict:
    return {
        "action_id": action_id,
        "type": action_type,
        "priority": priority,
        "hypothesis_ids": [],
        "evidence_ids": [],
        "rationale": f"Exercise {action_type} through the durable dispatcher.",
        "expected_effect": "Produce a measurable bounded lane-state change.",
        "evaluation_window": {
            "max_wall_seconds": 60,
            "max_candidate_delta": 10_000,
        },
        "idempotency_key": f"idempotency:{action_id}",
        "lease_seconds": 300,
        "fallback": {"on_precondition_failure": "replan"},
    }


def start_action(action_id: str, algorithm: str, seed: int) -> dict:
    parameters = {
        "order": 8,
        "batch_candidates": 100,
        "witness_cap": 4,
    }
    if algorithm == "simulated_annealing":
        parameters.update(
            {
                "temperature": 1.0,
                "cooling": 0.999,
                "restart_threshold": 1000,
            }
        )
    else:
        parameters.update({"tabu_tenure": 32, "perturbation_interval": 16})
    return {
        **common(action_id, "start_lane"),
        "spec": {
            "algorithm": algorithm,
            "graph_family": "connected_cubic",
            "seed": seed,
            "parameters": parameters,
            "resource_share": 0.5,
        },
    }


def decision(snapshot_id: str, actions: list[dict]) -> dict:
    return {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "campaign_assessment": "Durable integration exercise.",
        "hypothesis_updates": [],
        "actions": actions,
        "next_review": {
            "min_wall_seconds": 10,
            "max_wall_seconds": 60,
            "candidate_delta": 1000,
            "events": ["lane_failure"],
        },
    }


class LaneActionDispatcherTests(unittest.TestCase):
    def test_committed_start_patch_and_fork_apply_at_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            manager = LaneManager(
                root,
                max_active_lanes=4,
                checkpoints_per_lane=4,
                telemetry_windows=8,
            )
            dispatcher = LaneActionDispatcher(
                store=store,
                manager=manager,
                campaign_id="campaign-1",
            )
            try:
                store.create_campaign(
                    campaign_id="campaign-1",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="time_limit",
                    deadline_at="2026-07-25T00:00:00Z",
                )
                self._commit(
                    store,
                    "snapshot-1",
                    "trigger-1",
                    "turn-1",
                    "batch-1",
                    [
                        start_action(
                            "action-start-a", "simulated_annealing", 11
                        ),
                        start_action(
                            "action-start-b", "iterated_local_search", 19
                        ),
                    ],
                )
                self.assertEqual(
                    set(dispatcher.dispatch_pending()),
                    {"action-start-a", "action-start-b"},
                )
                self._poll_until(
                    dispatcher,
                    lambda: self._outcome_count(store) == 2
                    and len(manager.active_lanes()) == 2
                    and manager.total_candidates() >= 200,
                )
                rows = store.connection.execute(
                    """
                    SELECT lane_id, state, algorithm FROM research_lanes
                    ORDER BY algorithm
                    """
                ).fetchall()
                self.assertEqual({row["state"] for row in rows}, {"running"})
                annealing = next(
                    row for row in rows if row["algorithm"] == "simulated_annealing"
                )
                local = next(
                    row
                    for row in rows
                    if row["algorithm"] == "iterated_local_search"
                )
                annealing_runtime = manager.lanes[str(annealing["lane_id"])]
                local_runtime = manager.lanes[str(local["lane_id"])]
                checkpoint_id = str(local_runtime.latest_checkpoint_id)
                parent_before = local_runtime.high_water

                patch = {
                    **common("action-patch-a", "patch_lane"),
                    "lane_id": str(annealing["lane_id"]),
                    "expected_lane_version": 0,
                    "patch": {"temperature": 0.4},
                }
                fork = {
                    **common("action-fork-b", "fork_lane"),
                    "lane_id": str(local["lane_id"]),
                    "expected_lane_version": 0,
                    "checkpoint_id": checkpoint_id,
                    "variants": [
                        {
                            "name": "short-tabu",
                            "patch": {"tabu_tenure": 8},
                            "resource_share": 0.25,
                        }
                    ],
                }
                self._commit(
                    store,
                    "snapshot-2",
                    "trigger-2",
                    "turn-2",
                    "batch-2",
                    [patch, fork],
                )
                self.assertEqual(
                    set(dispatcher.dispatch_pending()),
                    {"action-patch-a", "action-fork-b"},
                )
                self._poll_until(
                    dispatcher,
                    lambda: self._outcome_count(store) == 4
                    and len(manager.active_lanes()) == 3,
                )
                self.assertEqual(annealing_runtime.lane_version, 1)
                self.assertEqual(annealing_runtime.parameters["temperature"], 0.4)
                self.assertGreater(local_runtime.high_water, parent_before)
                children = [
                    lane
                    for lane in manager.lanes.values()
                    if lane.spec.parent_lane_id == str(local["lane_id"])
                ]
                self.assertEqual(len(children), 1)
                self.assertEqual(children[0].parameters["tabu_tenure"], 8)
                self.assertEqual(children[0].spec.parent_checkpoint_id, checkpoint_id)
                child = children[0]
                lane_versions = store.connection.execute(
                    """
                    SELECT algorithm, lane_version FROM research_lanes
                    WHERE parent_lane_id IS NULL ORDER BY algorithm
                    """
                ).fetchall()
                self.assertEqual(
                    {
                        row["algorithm"]: row["lane_version"]
                        for row in lane_versions
                    },
                    {"iterated_local_search": 0, "simulated_annealing": 1},
                )

                allocations = [
                    {
                        "lane_id": annealing_runtime.spec.lane_id,
                        "expected_lane_version": 1,
                        "resource_share": 0.4,
                    },
                    {
                        "lane_id": local_runtime.spec.lane_id,
                        "expected_lane_version": 0,
                        "resource_share": 0.3,
                    },
                    {
                        "lane_id": child.spec.lane_id,
                        "expected_lane_version": 0,
                        "resource_share": 0.3,
                    },
                ]
                self._commit(
                    store,
                    "snapshot-3",
                    "trigger-3",
                    "turn-3",
                    "batch-3",
                    [
                        {
                            **common("action-allocate", "reallocate_resources"),
                            "allocations": allocations,
                        }
                    ],
                )
                self.assertEqual(
                    dispatcher.dispatch_pending(), ["action-allocate"]
                )
                self._poll_until(
                    dispatcher,
                    lambda: self._outcome_count(store) == 5,
                )
                self.assertEqual(
                    {
                        annealing_runtime.resource_share,
                        local_runtime.resource_share,
                        child.resource_share,
                    },
                    {0.4, 0.3},
                )

                restart = {
                    **common("action-restart-a", "restart_lane"),
                    "lane_id": annealing_runtime.spec.lane_id,
                    "expected_lane_version": 2,
                    "restart_spec": {"source": "new_seed", "seed": 12345},
                }
                stop = {
                    **common("action-stop-child", "stop_lane"),
                    "lane_id": child.spec.lane_id,
                    "expected_lane_version": 1,
                }
                self._commit(
                    store,
                    "snapshot-4",
                    "trigger-4",
                    "turn-4",
                    "batch-4",
                    [restart, stop],
                )
                self.assertEqual(
                    set(dispatcher.dispatch_pending()),
                    {"action-restart-a", "action-stop-child"},
                )
                self._poll_until(
                    dispatcher,
                    lambda: self._outcome_count(store) == 7,
                )
                self.assertEqual(annealing_runtime.lane_version, 3)
                self.assertEqual(child.lane_version, 2)
                stopped = store.connection.execute(
                    "SELECT state FROM research_lanes WHERE lane_id=?",
                    (child.spec.lane_id,),
                ).fetchone()
                self.assertEqual(stopped["state"], "stopped")
                self.assertLessEqual(
                    store.connection.execute(
                        "SELECT count(*) FROM lane_metric_windows"
                    ).fetchone()[0],
                    3 * manager.telemetry_windows,
                )
                self.assertEqual(
                    store.connection.execute("PRAGMA integrity_check").fetchone()[0],
                    "ok",
                )
            finally:
                manager.shutdown()
                store.close()

    def _commit(
        self,
        store: ResearchStore,
        snapshot_id: str,
        trigger_id: str,
        turn_id: str,
        batch_id: str,
        actions: list[dict],
    ) -> None:
        version = int(store.campaign("campaign-1")["state_version"])
        store.record_snapshot(
            snapshot_id=snapshot_id,
            campaign_id="campaign-1",
            campaign_state_version=version,
            high_water={},
            artifact_ref=f"snapshots/{snapshot_id}.json",
            artifact_sha256="b" * 64,
            payload_bytes=100,
        )
        store.record_trigger(
            trigger_id=trigger_id,
            campaign_id="campaign-1",
            campaign_state_version=version,
            reasons=["test"],
            first_event_at="2026-07-24T00:00:00Z",
            snapshot_id=snapshot_id,
        )
        if turn_id == "turn-1":
            store.record_session(
                record_id="session-record-1",
                campaign_id="campaign-1",
                thread_id="thread-1",
                session_id="session-1",
                thread_path="/private/rollout.jsonl",
                parent_thread_id=None,
                model="test",
                effort="low",
                codex_version="test",
                executable_sha256="c" * 64,
                protocol_schema_sha256="d" * 64,
            )
        store.begin_turn(
            turn_record_id=turn_id,
            session_record_id="session-record-1",
            campaign_id="campaign-1",
            thread_id="thread-1",
            snapshot_id=snapshot_id,
            trigger_id=trigger_id,
            request_artifact_ref=f"turns/{turn_id}-request.json",
            request_sha256="e" * 64,
            wire_artifact_ref=f"turns/{turn_id}-wire.jsonl",
        )
        store.complete_turn(
            turn_id,
            turn_id=turn_id,
            status="completed_valid",
            response_artifact_ref=f"turns/{turn_id}-response.json",
            response_sha256="f" * 64,
            wire_sha256="0" * 64,
        )
        statuses = store.commit_decision_batch(
            decision_batch_id=batch_id,
            campaign_id="campaign-1",
            snapshot_id=snapshot_id,
            trigger_id=trigger_id,
            turn_record_id=turn_id,
            decision=decision(snapshot_id, actions),
        )
        self.assertEqual(set(statuses.values()), {"accepted"})

    def _poll_until(
        self, dispatcher: LaneActionDispatcher, predicate, timeout: float = 8
    ) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            dispatcher.poll_once(timeout=0.05)
            if predicate():
                return
        raise AssertionError("durable lane action did not complete")

    def _outcome_count(self, store: ResearchStore) -> int:
        return int(
            store.connection.execute(
                "SELECT count(*) FROM director_action_outcomes"
            ).fetchone()[0]
        )
