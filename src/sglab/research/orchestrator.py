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
from .passive import PassiveSchedulerFault
from .snapshot import SnapshotBuilder
from .store import ResearchStore, new_id
from .triggers import TriggerBatch, TriggerEngine
from .verification_broker import M4VerificationBroker
from ..state import utc_now


@dataclass(frozen=True, slots=True)
class DirectorCycleResult:
    trigger_id: str
    snapshot_id: str
    reasons: tuple[str, ...]
    action_statuses: dict[str, str]
    candidates_during_inference: int
    replan_count: int = 0
    replan_exhausted: bool = False


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
            if self.provider_source_kind == "passive_scheduler":
                setattr(
                    self.provider,
                    "review_boundary_evaluations",
                    int(
                        getattr(
                            self.triggers,
                            "last_review_evaluations",
                            self.manager.total_candidates(),
                        )
                    ),
                )
            first = await self._run_cycle(batch)
            if self.provider_source_kind == "passive_scheduler":
                if not first.action_statuses or set(
                    first.action_statuses.values()
                ) != {"rejected_stale_campaign"}:
                    return first
                rewind = getattr(
                    self.provider,
                    "rewind_after_stale_campaign",
                    None,
                )
                if not callable(rewind):
                    raise PassiveSchedulerFault(
                        "passive scheduler cannot restore committed state "
                        "for stale-campaign recovery"
                    )
                rewind()
                second = await self._run_cycle(
                    TriggerBatch(
                        reasons=("passive_stale_campaign_replan",),
                        first_event_at=utc_now(),
                    )
                )
                if set(second.action_statuses.values()) == {
                    "rejected_stale_campaign"
                }:
                    detail = ", ".join(
                        f"{action_id}={status}"
                        for action_id, status in sorted(
                            second.action_statuses.items()
                        )
                    )
                    raise PassiveSchedulerFault(
                        "one fresh passive scheduler replan was also "
                        "rejected as stale; no action was dispatched: "
                        f"{detail}"
                    )
                return DirectorCycleResult(
                    trigger_id=second.trigger_id,
                    snapshot_id=second.snapshot_id,
                    reasons=tuple(
                        dict.fromkeys((*first.reasons, *second.reasons))
                    ),
                    action_statuses={
                        **first.action_statuses,
                        **second.action_statuses,
                    },
                    candidates_during_inference=(
                        first.candidates_during_inference
                        + second.candidates_during_inference
                    ),
                    replan_count=1,
                    replan_exhausted=False,
                )
            replan_statuses = {
                "stale_target",
                "rejected_action_id_collision",
            }
            if not (
                replan_statuses & set(first.action_statuses.values())
            ):
                return first
            second = await self._run_cycle(
                TriggerBatch(
                    reasons=(
                        (
                            "action_id_collision_replan"
                            if "rejected_action_id_collision"
                            in first.action_statuses.values()
                            else "stale_action_replan"
                        ),
                    ),
                    first_event_at=utc_now(),
                )
            )
            statuses = {**first.action_statuses, **second.action_statuses}
            exhausted = bool(
                replan_statuses & set(second.action_statuses.values())
            )
            if exhausted:
                self.store.finish_campaign(
                    self.campaign_id,
                    terminal_kind="director_replan_exhausted",
                    detail=(
                        "one fresh stateless replan also returned an invalid "
                        "action target or identifier; no invalid action was "
                        "executed"
                    ),
                )
            return DirectorCycleResult(
                trigger_id=second.trigger_id,
                snapshot_id=second.snapshot_id,
                reasons=tuple(
                    dict.fromkeys((*first.reasons, *second.reasons))
                ),
                action_statuses=statuses,
                candidates_during_inference=(
                    first.candidates_during_inference
                    + second.candidates_during_inference
                ),
                replan_count=1,
                replan_exhausted=exhausted,
            )

    async def _run_cycle(
        self, batch: TriggerBatch
    ) -> DirectorCycleResult:
        snapshot, context = self.snapshots.publish()
        self.manager.pin_checkpoints(
            tuple(
                sorted(
                    context.checkpoint_ids
                    & context.executable_target_ids
                )
            )
        )
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
        passive_provider = (
            self.provider_source_kind == "passive_scheduler"
        )
        try:
            if passive_provider:
                # Keep the host-local review on the snapshot's coordinator
                # step; pumping here would make queued lane progress stale it.
                evidence = await self.provider.decide(
                    snapshot=snapshot,
                    trigger_id=trigger_id,
                    context=context,
                )
            else:
                task = asyncio.create_task(
                    self.provider.decide(
                        snapshot=snapshot,
                        trigger_id=trigger_id,
                        context=context,
                    )
                )
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
            if evidence.source_kind == "passive_scheduler":
                detail = "; ".join(
                    f"{issue.path}: {issue.message}"
                    for issue in evidence.validation.issues
                )
                if (
                    evidence.source_record_id is None
                    or evidence.source_metadata is None
                ):
                    raise PassiveSchedulerFault(
                        "invalid passive decision lacks durable provenance"
                    )
                self.store.record_passive_scheduler_fault(
                    scheduler_decision_id=evidence.source_record_id,
                    campaign_id=self.campaign_id,
                    snapshot_id=str(snapshot["snapshot_id"]),
                    metadata=evidence.source_metadata,
                    decision=evidence.decision,
                    detail=detail,
                )
                raise PassiveSchedulerFault(
                    f"passive scheduler generated an invalid action: {detail}"
                )
            raise RuntimeError("Director response remained invalid after repair")
        passive = evidence.source_kind == "passive_scheduler"
        statuses = self.store.commit_decision_batch(
            decision_batch_id=new_id("decision-batch"),
            campaign_id=self.campaign_id,
            snapshot_id=str(snapshot["snapshot_id"]),
            trigger_id=trigger_id,
            turn_record_id=(
                None if passive else evidence.turn_record_ids[-1]
            ),
            decision=evidence.decision,
            scheduler_decision_id=(
                evidence.source_record_id if passive else None
            ),
            scheduler_metadata=(
                evidence.source_metadata if passive else None
            ),
        )
        if (
            passive
            and statuses
            and set(statuses.values()) == {"rejected_stale_campaign"}
        ):
            return DirectorCycleResult(
                trigger_id=trigger_id,
                snapshot_id=str(snapshot["snapshot_id"]),
                reasons=batch.reasons,
                action_statuses=statuses,
                candidates_during_inference=max(
                    0, self.manager.total_candidates() - before
                ),
            )
        if passive and any(
            status != "accepted" for status in statuses.values()
        ):
            detail = ", ".join(
                f"{action_id}={status}"
                for action_id, status in sorted(statuses.items())
            )
            raise PassiveSchedulerFault(
                "passive scheduler batch was rejected; no action was "
                f"dispatched: {detail}"
            )
        self.triggers.configure(evidence.decision["next_review"])
        if any(
            status in {
                "rejected_stale_campaign",
                "rejected_stale_state",
            }
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

    @property
    def provider_source_kind(self) -> str:
        return str(
            getattr(self.provider, "source_kind", "app_server")
        )
