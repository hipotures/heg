from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import asyncio

from .actions import LaneActionDispatcher
from .candidates import CandidateArchive
from .effects import EffectEvaluator
from .diagnostics import ScientificActionDispatcher
from .lanes import LaneManager
from .providers import DecisionProvider
from .snapshot import SnapshotBuilder
from .store import ResearchStore, new_id
from .triggers import TriggerBatch, TriggerEngine
from .verification_broker import M4VerificationBroker


@dataclass(frozen=True, slots=True)
class DirectorCycleResult:
    trigger_id: str
    snapshot_id: str
    reasons: tuple[str, ...]
    action_statuses: dict[str, str]
    candidates_during_inference: int


class ActiveResearchOrchestrator:
    """Event-driven coordination while search lanes continue independently."""

    def __init__(
        self,
        *,
        store: ResearchStore,
        manager: LaneManager,
        dispatcher: LaneActionDispatcher,
        snapshots: SnapshotBuilder,
        provider: DecisionProvider,
        triggers: TriggerEngine,
        campaign_id: str,
        candidates: CandidateArchive | None = None,
        verification: M4VerificationBroker | None = None,
        scientific_actions: ScientificActionDispatcher | None = None,
        inference_poll_seconds: float = 0.01,
    ):
        if not 0 < inference_poll_seconds <= 1:
            raise ValueError("inference poll interval must be in (0, 1]")
        self.store = store
        self.manager = manager
        self.dispatcher = dispatcher
        self.snapshots = snapshots
        self.provider = provider
        self.triggers = triggers
        self.campaign_id = campaign_id
        self.candidates = candidates
        self.verification = verification
        self.scientific_actions = scientific_actions
        self.inference_poll_seconds = inference_poll_seconds
        self.effects = EffectEvaluator(store, campaign_id)
        self._cycle_lock = asyncio.Lock()

    def bootstrap(self) -> None:
        self.triggers.offer("bootstrap")

    def pump_events(self, maximum: int = 64) -> list[dict[str, Any]]:
        if maximum < 1:
            raise ValueError("event pump maximum must be positive")
        events: list[dict[str, Any]] = []
        for _ in range(maximum):
            event = self.dispatcher.poll_once(timeout=0)
            if event is None:
                break
            events.append(event)
            if event.get("kind") == "improvement" and self.candidates is not None:
                self.candidates.observe_improvement(event)
            elif event.get("kind") == "checkpoint" and self.candidates is not None:
                candidate_id = self.candidates.observe_checkpoint(event)
                if candidate_id is not None:
                    self.triggers.offer("new_global_best")
            runtime = self.manager.lanes.get(str(event["lane_id"]))
            recent = runtime.telemetry.recent() if runtime is not None else {}
            self.triggers.observe_lane_event(event, recent_metrics=recent)
        for event in self.dispatcher.drain_control_events():
            self.triggers.offer(str(event["reason"]))
        if self.verification is not None:
            for event in self.verification.pump():
                self.triggers.offer(str(event["reason"]))
        if self.scientific_actions is not None:
            self.scientific_actions.dispatch_pending()
            for contract in self.scientific_actions.drain_review_contracts():
                self.triggers.configure(contract)
            for event in self.scientific_actions.drain_events():
                self.triggers.offer(str(event["reason"]))
        for evaluation in self.effects.evaluate_ready():
            met = evaluation["expectation_met"]
            if met is True:
                self.triggers.offer("meaningful_improvement")
            elif met is False:
                self.triggers.offer("regression")
        return events

    async def tick(self) -> DirectorCycleResult | None:
        self.pump_events()
        self.dispatcher.dispatch_pending()
        if not self.triggers.due(
            total_candidates=self.manager.total_candidates()
        ):
            return None
        return await self.run_due_cycle()

    async def run_due_cycle(self) -> DirectorCycleResult:
        async with self._cycle_lock:
            batch = self.triggers.consume(
                total_candidates=self.manager.total_candidates()
            )
            return await self._run_cycle(batch)

    async def _run_cycle(
        self, batch: TriggerBatch
    ) -> DirectorCycleResult:
        snapshot, context = self.snapshots.publish()
        for checkpoint_id in context.checkpoint_ids:
            self.manager.pin_checkpoint(checkpoint_id)
        trigger_id = new_id("trigger")
        campaign_version = int(
            snapshot["campaign"]["state_version"]
        )
        self.store.record_trigger(
            trigger_id=trigger_id,
            campaign_id=self.campaign_id,
            campaign_state_version=campaign_version,
            reasons=list(batch.reasons),
            first_event_at=batch.first_event_at,
            snapshot_id=str(snapshot["snapshot_id"]),
        )
        before = self.manager.total_candidates()
        task = asyncio.create_task(
            self.provider.decide(
                snapshot=snapshot,
                trigger_id=trigger_id,
                context=context,
            )
        )
        try:
            while not task.done():
                self.pump_events()
                self.dispatcher.dispatch_pending()
                await asyncio.sleep(self.inference_poll_seconds)
            evidence = await task
        except BaseException:
            self.store.mark_trigger_status(trigger_id, "failed")
            raise
        if not evidence.validation.accepted:
            self.store.mark_trigger_status(trigger_id, "rejected_invalid")
            raise RuntimeError("Director response remained invalid after repair")
        statuses = self.store.commit_decision_batch(
            decision_batch_id=new_id("decision-batch"),
            campaign_id=self.campaign_id,
            snapshot_id=str(snapshot["snapshot_id"]),
            trigger_id=trigger_id,
            turn_record_id=evidence.turn_record_ids[-1],
            decision=evidence.decision,
        )
        self.triggers.configure(evidence.decision["next_review"])
        if any(
            status in {"rejected_stale_campaign", "rejected_stale_state"}
            for status in statuses.values()
        ):
            self.triggers.offer("stale_action_replan")
        self.dispatcher.dispatch_pending()
        return DirectorCycleResult(
            trigger_id=trigger_id,
            snapshot_id=str(snapshot["snapshot_id"]),
            reasons=batch.reasons,
            action_statuses=statuses,
            candidates_during_inference=max(
                0, self.manager.total_candidates() - before
            ),
        )
