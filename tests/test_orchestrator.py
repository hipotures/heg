from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path

from sglab.research.actions import LaneActionDispatcher
from sglab.research.director import DirectorEvidence
from sglab.research.lanes import LaneManager
from sglab.research.orchestrator import ActiveResearchOrchestrator
from sglab.research.passive import PassiveScheduler, PassiveSchedulerFault
from sglab.research.snapshot import SnapshotBuilder
from sglab.research.store import ResearchStore
from sglab.research.triggers import TriggerEngine
from sglab.research.validation import DecisionContext, validate_decision
from sglab.model import BitGraph


def action_common(action_id: str, kind: str) -> dict:
    return {
        "action_id": action_id,
        "type": kind,
        "priority": 70,
        "hypothesis_ids": [],
        "evidence_ids": [],
        "rationale": f"Deterministic offline exercise for {kind}.",
        "expected_effect": "Improve score slope over the next windows.",
        "evaluation_window": {
            "max_wall_seconds": 10,
            "max_candidate_delta": 100,
        },
        "idempotency_key": f"orchestrator:{action_id}",
        "lease_seconds": 300,
        "fallback": {"on_precondition_failure": "replan"},
    }


def lane_parameters(algorithm: str) -> dict:
    value = {
        "order": 8,
        "batch_candidates": 100,
        "witness_cap": 4,
    }
    if algorithm == "simulated_annealing":
        value.update(
            {
                "temperature": 1.0,
                "cooling": 0.999,
                "restart_threshold": 1000,
            }
        )
    else:
        value.update({"tabu_tenure": 32, "perturbation_interval": 16})
    return value


class DurableScenarioProvider:
    def __init__(self, store: ResearchStore):
        self.store = store
        self.turn = 0
        self.saw_prior_effect = False

    async def decide(
        self,
        *,
        snapshot: dict,
        trigger_id: str,
        context: DecisionContext,
    ) -> DirectorEvidence:
        self.turn += 1
        await asyncio.sleep(0.15 if self.turn == 2 else 0.01)
        if self.turn == 1:
            actions = [
                {
                    **action_common("start-sa", "start_lane"),
                    "spec": {
                        "algorithm": "simulated_annealing",
                        "graph_family": "connected_cubic",
                        "seed": 11,
                        "parameters": lane_parameters("simulated_annealing"),
                        "resource_share": 0.5,
                    },
                },
                {
                    **action_common("start-ils", "start_lane"),
                    "spec": {
                        "algorithm": "iterated_local_search",
                        "graph_family": "connected_cubic",
                        "seed": 19,
                        "parameters": lane_parameters("iterated_local_search"),
                        "resource_share": 0.5,
                    },
                },
            ]
        elif self.turn == 2:
            sa = next(
                lane
                for lane in snapshot["lanes"]
                if lane["algorithm"] == "simulated_annealing"
            )
            ils = next(
                lane
                for lane in snapshot["lanes"]
                if lane["algorithm"] == "iterated_local_search"
            )
            best = snapshot["global_best"]
            if not isinstance(best, dict) or not best.get("checkpoint_id"):
                raise AssertionError(
                    "the real-lane test requires a visible best checkpoint"
                )
            actions = [
                {
                    **action_common("patch-sa", "patch_lane"),
                    "lane_id": sa["lane_id"],
                    "expected_lane_version": sa["lane_version"],
                    "patch": {"temperature": 0.4},
                },
                {
                    **action_common("fork-ils", "fork_lane"),
                    "lane_id": ils["lane_id"],
                    "expected_lane_version": ils["lane_version"],
                    "checkpoint_id": best["checkpoint_id"],
                    "variants": [
                        {
                            "name": "short-tabu",
                            "patch": {"tabu_tenure": 8},
                            "resource_share": 0.25,
                        }
                    ],
                },
            ]
        else:
            self.saw_prior_effect = any(
                action["action_id"] == "patch-sa"
                and action["observed_effect"] is not None
                for action in snapshot["recent_actions"]
            )
            share = 1.0 / len(snapshot["lanes"])
            actions = [
                {
                    **action_common(
                        "reallocate-after-effect", "reallocate_resources"
                    ),
                    "allocations": [
                        {
                            "lane_id": lane["lane_id"],
                            "expected_lane_version": lane["lane_version"],
                            "resource_share": share,
                        }
                        for lane in snapshot["lanes"]
                        if lane["state"] == "running"
                    ],
                }
            ]
        decision = {
            "schema_version": "1.0",
            "snapshot_id": snapshot["snapshot_id"],
            "campaign_assessment": (
                "Offline deterministic provider exercises orchestration only."
            ),
            "hypothesis_updates": [],
            "actions": actions,
            "next_review": {
                "min_wall_seconds": 10,
                "max_wall_seconds": 60,
                "candidate_delta": 100_000_000,
                "events": [
                    "new_global_best",
                    "meaningful_improvement",
                    "regression",
                    "stagnation",
                    "lane_failure",
                ],
            },
        }
        validation = validate_decision(decision, context)
        if not validation.accepted:
            raise AssertionError(validation.issues)
        turn_record = f"scenario-turn-{self.turn}"
        if self.turn == 1:
            self.store.record_session(
                record_id="scenario-session",
                campaign_id="campaign-1",
                thread_id="scenario-thread",
                session_id="scenario",
                thread_path=None,
                parent_thread_id=None,
                model="deterministic-test",
                effort="low",
                codex_version="test",
                executable_sha256="c" * 64,
                protocol_schema_sha256="d" * 64,
            )
        self.store.begin_turn(
            turn_record_id=turn_record,
            session_record_id="scenario-session",
            campaign_id="campaign-1",
            thread_id="scenario-thread",
            snapshot_id=snapshot["snapshot_id"],
            trigger_id=trigger_id,
            request_artifact_ref=f"test/{turn_record}-request.json",
            request_sha256="e" * 64,
            wire_artifact_ref=f"test/{turn_record}-wire.jsonl",
        )
        self.store.complete_turn(
            turn_record,
            turn_id=turn_record,
            status="completed_valid",
            response_artifact_ref=f"test/{turn_record}-response.json",
            response_sha256="f" * 64,
            wire_sha256="0" * 64,
        )
        return DirectorEvidence(
            decision=decision,
            validation=validation,
            session_record_id="scenario-session",
            turn_record_ids=(turn_record,),
            thread_id="scenario-thread",
            turn_id=turn_record,
        )


class StaleCandidateReplanProvider:
    def __init__(self, store: ResearchStore):
        self.store = store
        self.turn = 0
        self.saw_feedback = False

    async def decide(
        self,
        *,
        snapshot: dict,
        trigger_id: str,
        context: DecisionContext,
    ) -> DirectorEvidence:
        self.turn += 1
        if self.turn == 1:
            action = {
                **action_common("verify-now-stale", "schedule_verification"),
                "candidate_ids": ["candidate-stale"],
                "verification_priority": 80,
            }
        else:
            feedback = (
                snapshot.get("scientific_memory_projection", {})
                .get("continuity", {})
                .get("validation_feedback", [])
            )
            self.saw_feedback = bool(
                feedback
                and feedback[0].get("stale_candidate_ids")
                == ["candidate-stale"]
                and feedback[0].get(
                    "current_executable_candidate_ids"
                )
                == []
            )
            action = {
                **action_common("review-after-stale", "set_review_trigger"),
                "review_trigger": {
                    "min_wall_seconds": 10,
                    "max_wall_seconds": 60,
                    "candidate_delta": 100_000,
                    "events": [
                        "new_global_best",
                        "verification_result",
                        "lane_failure",
                        "resource_pressure",
                    ],
                },
            }
        decision = {
            "schema_version": "1.0",
            "snapshot_id": snapshot["snapshot_id"],
            "campaign_assessment": "Recover stale candidate target.",
            "hypothesis_updates": [],
            "actions": [action],
            "next_review": {
                "min_wall_seconds": 10,
                "max_wall_seconds": 60,
                "candidate_delta": 100_000,
                "events": [
                    "new_global_best",
                    "verification_result",
                    "lane_failure",
                    "resource_pressure",
                ],
            },
        }
        validation = validate_decision(decision, context)
        if not validation.accepted:
            raise AssertionError(validation.issues)
        if self.turn == 1:
            self.store.record_session(
                record_id="stale-session",
                campaign_id="campaign-stale",
                thread_id="stale-thread",
                session_id=None,
                thread_path=None,
                parent_thread_id=None,
                model="deterministic-replay",
                effort="none",
                codex_version="test",
                executable_sha256="a" * 64,
                protocol_schema_sha256="b" * 64,
                context_mode="stateless_turns",
            )
            with self.store.transaction() as database:
                database.execute(
                    """
                    DELETE FROM campaign_candidates
                    WHERE candidate_id='candidate-stale'
                    """
                )
        turn_record = f"stale-turn-{self.turn}"
        self.store.begin_turn(
            turn_record_id=turn_record,
            session_record_id="stale-session",
            campaign_id="campaign-stale",
            thread_id=f"fresh-stateless-thread-{self.turn}",
            snapshot_id=snapshot["snapshot_id"],
            trigger_id=trigger_id,
            request_artifact_ref=f"test/{turn_record}-request.json",
            request_sha256="c" * 64,
            wire_artifact_ref=f"test/{turn_record}-wire.jsonl",
        )
        self.store.complete_turn(
            turn_record,
            turn_id=turn_record,
            status="completed_valid",
            response_artifact_ref=f"test/{turn_record}-response.json",
            response_sha256="d" * 64,
            wire_sha256="e" * 64,
        )
        return DirectorEvidence(
            decision=decision,
            validation=validation,
            session_record_id="stale-session",
            turn_record_ids=(turn_record,),
            thread_id=f"fresh-stateless-thread-{self.turn}",
            turn_id=turn_record,
        )


class CampaignRacePassiveScheduler(PassiveScheduler):
    def __init__(self, *, race_count: int, **kwargs):
        super().__init__(**kwargs)
        self.race_count = race_count
        self.decision_count = 0

    async def decide(
        self,
        *,
        snapshot: dict,
        trigger_id: str,
        context: DecisionContext,
    ) -> DirectorEvidence:
        evidence = await super().decide(
            snapshot=snapshot,
            trigger_id=trigger_id,
            context=context,
        )
        self.decision_count += 1
        if self.decision_count <= self.race_count:
            with self.store.transaction() as database:
                database.execute(
                    """
                    UPDATE research_campaigns
                    SET state_version=state_version+1
                    WHERE campaign_id=?
                    """,
                    (self.campaign_id,),
                )
        return evidence


class ActiveResearchOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def test_passive_stale_campaign_gets_one_fresh_replan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            manager = LaneManager(
                root,
                max_active_lanes=2,
                telemetry_windows=8,
            )
            campaign_id = "campaign-passive-race"
            store.create_campaign(
                campaign_id=campaign_id,
                target="erdos_gyarfas",
                target_definition_sha256="a" * 64,
                stop_mode="until_success",
                deadline_at=None,
                director_mode="passive",
            )
            dispatcher = LaneActionDispatcher(
                store=store,
                manager=manager,
                campaign_id=campaign_id,
            )
            provider = CampaignRacePassiveScheduler(
                store=store,
                campaign_id=campaign_id,
                seed=91,
                race_count=1,
            )
            await provider.start()
            orchestrator = ActiveResearchOrchestrator(
                store=store,
                manager=manager,
                dispatcher=dispatcher,
                snapshots=SnapshotBuilder(
                    store=store,
                    manager=manager,
                    campaign_id=campaign_id,
                    campaign_dir=root,
                ),
                provider=provider,
                triggers=TriggerEngine(debounce_seconds=0),
                campaign_id=campaign_id,
                inference_poll_seconds=0.005,
            )
            try:
                orchestrator.bootstrap()
                result = await orchestrator.run_due_cycle()
                self.assertEqual(provider.decision_count, 2)
                self.assertEqual(result.replan_count, 1)
                self.assertFalse(result.replan_exhausted)
                self.assertIn(
                    "rejected_stale_campaign",
                    result.action_statuses.values(),
                )
                self.assertIn("accepted", result.action_statuses.values())
                self.assertEqual(
                    store.connection.execute(
                        """
                        SELECT count(*) FROM passive_scheduler_decisions
                        WHERE validation_status='rejected_batch'
                        """
                    ).fetchone()[0],
                    1,
                )
                self.assertIsNotNone(
                    store.passive_scheduler_state(campaign_id)
                )
            finally:
                manager.shutdown()
                store.close()

    async def test_passive_second_stale_campaign_faults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            manager = LaneManager(
                root,
                max_active_lanes=2,
                telemetry_windows=8,
            )
            campaign_id = "campaign-passive-repeat-race"
            store.create_campaign(
                campaign_id=campaign_id,
                target="erdos_gyarfas",
                target_definition_sha256="a" * 64,
                stop_mode="until_success",
                deadline_at=None,
                director_mode="passive",
            )
            dispatcher = LaneActionDispatcher(
                store=store,
                manager=manager,
                campaign_id=campaign_id,
            )
            provider = CampaignRacePassiveScheduler(
                store=store,
                campaign_id=campaign_id,
                seed=91,
                race_count=2,
            )
            await provider.start()
            orchestrator = ActiveResearchOrchestrator(
                store=store,
                manager=manager,
                dispatcher=dispatcher,
                snapshots=SnapshotBuilder(
                    store=store,
                    manager=manager,
                    campaign_id=campaign_id,
                    campaign_dir=root,
                ),
                provider=provider,
                triggers=TriggerEngine(debounce_seconds=0),
                campaign_id=campaign_id,
                inference_poll_seconds=0.005,
            )
            try:
                orchestrator.bootstrap()
                with self.assertRaisesRegex(
                    PassiveSchedulerFault,
                    "one fresh passive scheduler replan",
                ):
                    await orchestrator.run_due_cycle()
                self.assertEqual(provider.decision_count, 2)
                self.assertEqual(
                    store.connection.execute(
                        """
                        SELECT count(*) FROM director_actions
                        WHERE validation_status='accepted'
                        """
                    ).fetchone()[0],
                    0,
                )
                self.assertIsNone(
                    store.passive_scheduler_state(campaign_id)
                )
                await provider.start()
                orchestrator.bootstrap()
                resumed = await orchestrator.run_due_cycle()
                self.assertIn("accepted", resumed.action_statuses.values())
                self.assertIsNotNone(
                    store.passive_scheduler_state(campaign_id)
                )
            finally:
                manager.shutdown()
                store.close()

    async def test_stale_candidate_gets_one_fresh_replan_and_continues(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            manager = LaneManager(
                root,
                max_active_lanes=2,
                telemetry_windows=8,
            )
            store.create_campaign(
                campaign_id="campaign-stale",
                target="erdos_gyarfas",
                target_definition_sha256="a" * 64,
                stop_mode="until_success",
                deadline_at=None,
            )
            store.create_lane(
                lane_id="lane-stale",
                campaign_id="campaign-stale",
                target="erdos_gyarfas",
                parent_lane_id=None,
                parent_checkpoint_ref=None,
                action_id="bootstrap",
                algorithm="simulated_annealing",
                graph_family="connected_cubic",
                parameters=lane_parameters("simulated_annealing"),
                seed_lineage=[1],
                resource_share=1.0,
                lease_expires_at=None,
            )
            store.mark_lane_running("lane-stale")
            graph6 = BitGraph.from_edges(
                4,
                (
                    (0, 1),
                    (0, 2),
                    (0, 3),
                    (1, 2),
                    (1, 3),
                    (2, 3),
                ),
            ).to_graph6()
            store.retain_campaign_candidate(
                candidate_id="candidate-stale",
                campaign_id="campaign-stale",
                lane_id="lane-stale",
                lane_version=0,
                checkpoint_ref=None,
                graph6=graph6,
                graph_sha256=hashlib.sha256(
                    graph6.encode("ascii")
                ).hexdigest(),
                score={"ordering_key": [0, 0, 0, 0, 0]},
                artifact_ref="candidates/candidate-stale.graph6",
                artifact_sha256="f" * 64,
            )
            dispatcher = LaneActionDispatcher(
                store=store,
                manager=manager,
                campaign_id="campaign-stale",
            )
            provider = StaleCandidateReplanProvider(store)
            orchestrator = ActiveResearchOrchestrator(
                store=store,
                manager=manager,
                dispatcher=dispatcher,
                snapshots=SnapshotBuilder(
                    store=store,
                    manager=manager,
                    campaign_id="campaign-stale",
                    campaign_dir=root,
                ),
                provider=provider,
                triggers=TriggerEngine(debounce_seconds=0),
                campaign_id="campaign-stale",
                inference_poll_seconds=0.005,
            )
            try:
                orchestrator.bootstrap()
                result = await orchestrator.run_due_cycle()
                self.assertEqual(result.replan_count, 1)
                self.assertFalse(result.replan_exhausted)
                self.assertEqual(
                    result.action_statuses["verify-now-stale"],
                    "stale_target",
                )
                self.assertEqual(
                    result.action_statuses["review-after-stale"],
                    "accepted",
                )
                self.assertTrue(provider.saw_feedback)
                self.assertEqual(
                    store.campaign("campaign-stale")["state"], "running"
                )
                stale = store.connection.execute(
                    """
                    SELECT validation_detail FROM director_actions
                    WHERE action_id='verify-now-stale'
                    """
                ).fetchone()
                detail = json.loads(stale["validation_detail"])
                self.assertEqual(
                    detail["current_executable_candidate_ids"], []
                )
                self.assertIsNone(
                    store.connection.execute(
                        """
                        SELECT 1 FROM director_action_outcomes
                        WHERE action_id='verify-now-stale'
                        """
                    ).fetchone()
                )
            finally:
                manager.shutdown()
                store.close()

    async def test_search_continues_and_next_turn_receives_effect(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            manager = LaneManager(
                root,
                max_active_lanes=4,
                telemetry_windows=16,
            )
            dispatcher = LaneActionDispatcher(
                store=store,
                manager=manager,
                campaign_id="campaign-1",
            )
            provider = DurableScenarioProvider(store)
            orchestrator = ActiveResearchOrchestrator(
                store=store,
                manager=manager,
                dispatcher=dispatcher,
                snapshots=SnapshotBuilder(
                    store=store,
                    manager=manager,
                    campaign_id="campaign-1",
                    campaign_dir=root,
                ),
                provider=provider,
                triggers=TriggerEngine(debounce_seconds=0),
                campaign_id="campaign-1",
                inference_poll_seconds=0.005,
            )
            try:
                store.create_campaign(
                    campaign_id="campaign-1",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="until_success",
                    deadline_at=None,
                )
                orchestrator.bootstrap()
                first = await orchestrator.run_due_cycle()
                self.assertEqual(set(first.action_statuses.values()), {"accepted"})
                await self._wait(
                    orchestrator,
                    lambda: self._outcomes(store) == 2
                    and manager.total_candidates() >= 800,
                )

                orchestrator.triggers.offer("lane_failure")
                second = await orchestrator.run_due_cycle()
                self.assertGreater(second.candidates_during_inference, 0)
                await self._wait(
                    orchestrator,
                    lambda: self._outcomes(store) == 4
                    and len(manager.active_lanes()) == 3,
                )
                await self._wait(
                    orchestrator,
                    lambda: store.connection.execute(
                        """
                        SELECT evaluated_at FROM director_action_outcomes
                        WHERE action_id='patch-sa'
                        """
                    ).fetchone()["evaluated_at"]
                    is not None,
                )

                if not orchestrator.triggers.due(
                    total_candidates=manager.total_candidates()
                ):
                    orchestrator.triggers.offer("lane_failure")
                third = await orchestrator.run_due_cycle()
                self.assertEqual(
                    third.action_statuses["reallocate-after-effect"],
                    "accepted",
                )
                self.assertTrue(provider.saw_prior_effect)
                snapshots = store.connection.execute(
                    "SELECT count(*) FROM director_snapshots"
                ).fetchone()[0]
                self.assertEqual(snapshots, 3)
            finally:
                manager.shutdown()
                store.close()

    async def _wait(self, orchestrator, predicate, timeout: float = 8) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            orchestrator.pump_events()
            if predicate():
                return
            await asyncio.sleep(0.01)
        raise AssertionError("orchestrator condition timed out")

    def _outcomes(self, store: ResearchStore) -> int:
        return int(
            store.connection.execute(
                "SELECT count(*) FROM director_action_outcomes"
            ).fetchone()[0]
        )
