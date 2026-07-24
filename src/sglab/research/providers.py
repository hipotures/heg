from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol
import copy

from .director import ActiveDirector, DirectorEvidence
from .validation import DecisionContext, validate_decision
from .store import ResearchStore


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

    def __init__(
        self,
        decisions: dict[str, dict[str, Any]],
        *,
        store: ResearchStore | None = None,
        campaign_id: str | None = None,
    ):
        if (store is None) != (campaign_id is None):
            raise ValueError("durable replay requires store and campaign_id")
        self.decisions = copy.deepcopy(decisions)
        self.store = store
        self.campaign_id = campaign_id
        self._session_recorded = False

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
        turn_record_id = f"replay:{trigger_id}"
        if self.store is not None and self.campaign_id is not None:
            if not self._session_recorded:
                thread_id = f"replay-thread:{self.campaign_id}"
                resumed = (
                    self.store.connection.execute(
                        """
                        SELECT 1 FROM app_server_sessions
                        WHERE campaign_id=? AND thread_id=?
                        """,
                        (self.campaign_id, thread_id),
                    ).fetchone()
                    is not None
                )
                self.store.record_session(
                    record_id=f"replay-session:{self.campaign_id}",
                    campaign_id=self.campaign_id,
                    thread_id=thread_id,
                    session_id=None,
                    thread_path=None,
                    parent_thread_id=None,
                    model="deterministic-replay",
                    effort="low",
                    codex_version="replay",
                    executable_sha256="replay",
                    protocol_schema_sha256="replay",
                    resumed=resumed,
                )
                self._session_recorded = True
            self.store.begin_turn(
                turn_record_id=turn_record_id,
                session_record_id=f"replay-session:{self.campaign_id}",
                campaign_id=self.campaign_id,
                thread_id=f"replay-thread:{self.campaign_id}",
                snapshot_id=snapshot_id,
                trigger_id=trigger_id,
                request_artifact_ref="replay/no-request",
                request_sha256="replay",
                wire_artifact_ref="replay/no-wire",
            )
            self.store.complete_turn(
                turn_record_id,
                turn_id=turn_record_id,
                status="completed_valid",
            )
        return DirectorEvidence(
            decision=decision,
            validation=validation,
            session_record_id="replay",
            turn_record_ids=(turn_record_id,),
            thread_id="replay",
            turn_id=f"replay:{snapshot_id}",
        )
