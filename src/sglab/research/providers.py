from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
import copy

from .director import ActiveDirector, DirectorEvidence
from .validation import DecisionContext, validate_decision


class DecisionProvider(Protocol):
    async def decide(
        self,
        *,
        snapshot: dict[str, Any],
        trigger_id: str,
        context: DecisionContext,
    ) -> DirectorEvidence: ...


@dataclass(slots=True)
class AppServerDecisionProvider:
    """The only production Active Director provider."""

    director: ActiveDirector

    async def decide(
        self,
        *,
        snapshot: dict[str, Any],
        trigger_id: str,
        context: DecisionContext,
    ) -> DirectorEvidence:
        return await self.director.request_decision(
            snapshot=snapshot,
            trigger_id=trigger_id,
            context=context,
        )


class ReplayDecisionProvider:
    """Model-free decision replay for audit and recovery tests only."""

    def __init__(self, decisions: dict[str, dict[str, Any]]):
        self.decisions = copy.deepcopy(decisions)

    async def decide(
        self,
        *,
        snapshot: dict[str, Any],
        trigger_id: str,
        context: DecisionContext,
    ) -> DirectorEvidence:
        snapshot_id = str(snapshot["snapshot_id"])
        decision = copy.deepcopy(self.decisions[snapshot_id])
        validation = validate_decision(decision, context)
        if not validation.accepted:
            raise RuntimeError("recorded replay decision no longer validates")
        return DirectorEvidence(
            decision=decision,
            validation=validation,
            session_record_id="replay",
            turn_record_ids=(f"replay:{trigger_id}",),
            thread_id="replay",
            turn_id=f"replay:{snapshot_id}",
        )
