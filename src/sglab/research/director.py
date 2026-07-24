from __future__ import annotations

from dataclasses import dataclass, replace
from importlib.resources import files
from pathlib import Path
from time import perf_counter
from typing import Any
import hashlib
import json
import os

from .app_server_client import (
    AppServerClient,
    AppServerSession,
    AppServerTurnEvent,
    AppServerTurnResult,
    AppServerTurnTimeout,
)
from .context import (
    CLIENT_ESTIMATED_TOKENS_MAX,
    DirectorContextBudgetExceeded,
    DirectorContextMode,
    complete_context_size_report,
    evidence_registry_ids,
    prepare_director_state_v2,
)
from .protocol import (
    DecisionValidation,
    MAX_SNAPSHOT_BYTES,
    canonical_json,
    director_decision_schema,
)
from .store import ResearchStore, new_id
from .validation import DecisionContext, validate_decision


@dataclass(frozen=True, slots=True)
class DirectorEvidence:
    decision: dict[str, Any]
    validation: DecisionValidation
    session_record_id: str
    turn_record_ids: tuple[str, ...]
    thread_id: str
    turn_id: str
    first_item_latency_seconds: float | None = None
    final_answer_latency_seconds: float | None = None


def base_instructions() -> str:
    return (
        files("sglab.research")
        .joinpath("assets/director_base_instructions.txt")
        .read_text(encoding="utf-8")
        .strip()
    )


def build_director_prompt(snapshot: dict[str, Any]) -> str:
    target = snapshot.get("target")
    acceptance_control = (
        {
            "purpose": "M6 active-control demonstration, not a research claim",
            "required_before_verification": [
                "keep at least two search lanes live concurrently",
                "patch one running lane",
                "fork or restart another lane",
                "reallocate resources or replace a lane",
                "use a later turn to evaluate a measured prior intervention",
            ],
            "instruction": (
                "Do not schedule finalist verification until the committed "
                "snapshot evidence demonstrates these interventions."
            ),
        }
        if isinstance(target, dict)
        and target.get("target_id") == "m6_hidden_witness_control_v1"
        else None
    )
    director_state = prepare_director_state_v2(snapshot).state
    payload = {
        "objective": (
            "Actively manage the running concurrent search portfolio. "
            "Search may change while this turn is processed; target explicit "
            "lane versions from this committed snapshot."
        ),
        "immutable_target": target,
        "acceptance_control": acceptance_control,
        "director_state_v2": director_state,
        "required_response": (
            "Assess, update evidence-backed hypotheses, issue concrete typed "
            "interventions with numeric parameters and expected observations, "
            "and set bounded review triggers. Do not declare success."
        ),
    }
    return canonical_json(payload, max_bytes=MAX_SNAPSHOT_BYTES).decode("ascii")


class ActiveDirector:
    def __init__(
        self,
        *,
        client: AppServerClient,
        store: ResearchStore,
        campaign_id: str,
        campaign_dir: Path,
        codex_version: str,
        executable_sha256: str,
        protocol_schema_sha256: str,
        context_mode: DirectorContextMode | str = (
            DirectorContextMode.PERSISTENT_THREAD
        ),
    ):
        self.client = client
        self.store = store
        self.campaign_id = campaign_id
        self.campaign_dir = campaign_dir.resolve()
        self.codex_version = codex_version
        self.executable_sha256 = executable_sha256
        self.protocol_schema_sha256 = protocol_schema_sha256
        self.context_mode = DirectorContextMode(context_mode)
        self.session: AppServerSession | None = None
        self.session_record_id: str | None = None
        self.audit_dir = self.campaign_dir / "director"
        for child in (
            self.audit_dir,
            self.audit_dir / "requests",
            self.audit_dir / "responses",
            self.audit_dir / "wire",
            self.audit_dir / "evidence-registries",
        ):
            child.mkdir(parents=True, exist_ok=True, mode=0o700)
            child.chmod(0o700)

    async def start(
        self,
        *,
        resume_thread_id: str | None = None,
        parent_thread_id: str | None = None,
    ) -> AppServerSession:
        await self.client.start()
        if (
            resume_thread_id is None
            or self.context_mode is DirectorContextMode.STATELESS_TURNS
        ):
            session = await self.client.start_thread(base_instructions())
            if resume_thread_id is not None:
                parent_thread_id = resume_thread_id
        else:
            session = await self.client.resume_thread(
                resume_thread_id, base_instructions()
            )
        record_id = self.store.record_session(
            record_id=new_id("app-session"),
            campaign_id=self.campaign_id,
            thread_id=session.thread_id,
            session_id=session.session_id,
            thread_path=session.thread_path,
            parent_thread_id=parent_thread_id,
            model=session.model,
            effort=session.effort,
            codex_version=self.codex_version,
            executable_sha256=self.executable_sha256,
            protocol_schema_sha256=self.protocol_schema_sha256,
            resumed=(
                resume_thread_id is not None
                and self.context_mode
                is not DirectorContextMode.STATELESS_TURNS
            ),
        )
        self.session = session
        self.session_record_id = record_id
        return session

    def rollover_due(
        self,
        *,
        maximum_turns: int = 24,
        maximum_input_tokens: int = 1_000_000,
    ) -> bool:
        if self.session_record_id is None:
            return False
        row = self.store.connection.execute(
            """
            SELECT count(*) AS turns, COALESCE(sum(input_tokens), 0) AS input
            FROM app_server_turns
            WHERE session_record_id=? AND status LIKE 'completed_%'
            """,
            (self.session_record_id,),
        ).fetchone()
        return (
            int(row["turns"]) >= maximum_turns
            or int(row["input"]) >= maximum_input_tokens
        )

    async def rollover(self) -> AppServerSession:
        if self.session is None or self.session_record_id is None:
            raise RuntimeError("Director session has not been started")
        parent_thread_id = self.session.thread_id
        brief = self._rollover_brief(parent_thread_id)
        relative = (
            Path("director")
            / "rollovers"
            / f"{new_id('rollover-brief')}.json"
        )
        path = self.campaign_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = canonical_json(brief, max_bytes=32 * 1024)
        _write_private(path, payload + b"\n")
        _write_private(
            path.with_suffix(".sha256"),
            (hashlib.sha256(payload).hexdigest() + "\n").encode("ascii"),
        )
        instructions = (
            base_instructions()
            + "\nDurable rollover continuity brief (SQLite and the next "
            "snapshot remain authoritative): "
            + payload.decode("ascii")
        )
        session = await self.client.start_thread(instructions)
        self.store.close_session(self.session_record_id, state="rolled_over")
        record_id = self.store.record_session(
            record_id=new_id("app-session"),
            campaign_id=self.campaign_id,
            thread_id=session.thread_id,
            session_id=session.session_id,
            thread_path=session.thread_path,
            parent_thread_id=parent_thread_id,
            model=session.model,
            effort=session.effort,
            codex_version=self.codex_version,
            executable_sha256=self.executable_sha256,
            protocol_schema_sha256=self.protocol_schema_sha256,
        )
        self.session = session
        self.session_record_id = record_id
        return session

    async def request_decision(
        self,
        *,
        snapshot: dict[str, Any],
        trigger_id: str,
        context: DecisionContext,
    ) -> DirectorEvidence:
        prompt = build_director_prompt(snapshot)
        return await self._request(
            snapshot=snapshot,
            trigger_id=trigger_id,
            context=context,
            prompt=prompt,
            prior_turns=(),
            repair_allowed=True,
        )

    async def request_decision_once(
        self,
        *,
        snapshot: dict[str, Any],
        trigger_id: str,
        context: DecisionContext,
        prompt: str | None = None,
    ) -> DirectorEvidence:
        """Request one structured inference with no model-side repair retry."""

        return await self._request(
            snapshot=snapshot,
            trigger_id=trigger_id,
            context=context,
            prompt=prompt if prompt is not None else build_director_prompt(snapshot),
            prior_turns=(),
            repair_allowed=False,
        )

    async def _request(
        self,
        *,
        snapshot: dict[str, Any],
        trigger_id: str,
        context: DecisionContext,
        prompt: str,
        prior_turns: tuple[str, ...],
        repair_allowed: bool,
    ) -> DirectorEvidence:
        if self.session is None or self.session_record_id is None:
            raise RuntimeError("Director session has not been started")
        snapshot_id = str(snapshot["snapshot_id"])
        turn_record_id = new_id("app-turn")
        request_relative = Path("director") / "requests" / f"{turn_record_id}.json"
        response_relative = Path("director") / "responses" / f"{turn_record_id}.json"
        wire_relative = Path("director") / "wire" / f"{turn_record_id}.jsonl"
        registry_relative = (
            Path("director")
            / "evidence-registries"
            / f"{turn_record_id}.json"
        )
        context_relative = (
            Path("director")
            / "context-budgets"
            / f"{turn_record_id}.json"
        )
        try:
            prepared_state = prepare_director_state_v2(snapshot)
        except DirectorContextBudgetExceeded as error:
            if error.size_report is not None:
                _write_private(
                    self.campaign_dir / context_relative,
                    canonical_json(
                        error.size_report, max_bytes=128 * 1024
                    )
                    + b"\n",
                )
            raise
        parsed_prompt = _json_object(prompt)
        supplied_state = parsed_prompt.get("director_state_v2")
        if supplied_state != prepared_state.state:
            raise RuntimeError(
                "prompt DirectorStateV2 does not match the committed snapshot"
            )
        registry_bytes = canonical_json(
            prepared_state.evidence_registry, max_bytes=128 * 1024
        )
        _write_private(
            self.campaign_dir / registry_relative,
            registry_bytes + b"\n",
        )
        validation_context = replace(
            context,
            snapshot_id=str(prepared_state.state["source_snapshot_id"]),
            evidence_ids=evidence_registry_ids(
                prepared_state.evidence_registry
            ),
            candidate_ids=evidence_registry_ids(
                prepared_state.evidence_registry,
                kinds=frozenset({"candidate"}),
            ),
            checkpoint_ids=evidence_registry_ids(
                prepared_state.evidence_registry,
                kinds=frozenset({"checkpoint"}),
            ),
            hypothesis_ids=evidence_registry_ids(
                prepared_state.evidence_registry,
                kinds=frozenset({"hypothesis"}),
            ),
        )
        context_report = complete_context_size_report(
            prepared_state,
            prompt=prompt,
            base_instructions=base_instructions(),
            output_schema=director_decision_schema(),
            mode=self.context_mode,
        )
        context_bytes = canonical_json(
            context_report, max_bytes=128 * 1024
        )
        _write_private(
            self.campaign_dir / context_relative,
            context_bytes + b"\n",
        )
        if not context_report["within_client_token_limit"]:
            raise DirectorContextBudgetExceeded(
                "client-owned context estimate exceeds "
                f"{CLIENT_ESTIMATED_TOKENS_MAX} tokens"
            )
        if not prior_turns:
            await self._prepare_context_boundary()
        request_payload = {
            "thread_id": self.session.thread_id,
            "snapshot_id": snapshot_id,
            "trigger_id": trigger_id,
            "prompt": prompt,
            "output_schema": director_decision_schema(),
            "evidence_registry_artifact_ref": str(registry_relative),
            "evidence_registry_sha256": (
                prepared_state.evidence_registry_sha256
            ),
        }
        request_bytes = canonical_json(request_payload, max_bytes=1024 * 1024)
        _write_private(self.campaign_dir / request_relative, request_bytes + b"\n")
        self.store.begin_turn(
            turn_record_id=turn_record_id,
            session_record_id=self.session_record_id,
            campaign_id=self.campaign_id,
            thread_id=self.session.thread_id,
            snapshot_id=snapshot_id,
            trigger_id=trigger_id,
            request_artifact_ref=str(request_relative),
            request_sha256=hashlib.sha256(request_bytes).hexdigest(),
            wire_artifact_ref=str(wire_relative),
            evidence_registry_artifact_ref=str(registry_relative),
            evidence_registry_sha256=(
                prepared_state.evidence_registry_sha256
            ),
        )
        def persist_event(event: AppServerTurnEvent) -> None:
            self.store.record_turn_event(
                turn_record_id,
                event_sequence=event.sequence,
                lifecycle_status=event.lifecycle_status,
                request_id=event.request_id,
                thread_id=event.thread_id,
                turn_id=event.turn_id,
                items=event.items,
                terminal_reason=event.terminal_reason,
                usage=(
                    _usage_value(event.usage)
                    if event.usage is not None
                    else None
                ),
            )

        started = perf_counter()
        try:
            result = await self.client.turn(
                self.session,
                prompt,
                output_schema=director_decision_schema(),
                on_event=persist_event,
            )
            if not isinstance(result.parsed, dict):
                raise RuntimeError("Director structured result is not an object")
            response_bytes = canonical_json(result.parsed, max_bytes=128 * 1024)
            _write_private(
                self.campaign_dir / response_relative,
                response_bytes + b"\n",
            )
            take_wire = getattr(self.client, "take_wire_bytes", None)
            wire = take_wire() if callable(take_wire) else self.client.wire_bytes
            _write_private(self.campaign_dir / wire_relative, wire)
            self._prune_wire_artifacts()
            validation = validate_decision(
                result.parsed, validation_context
            )
            self.store.complete_turn(
                turn_record_id,
                turn_id=result.turn_id,
                status=(
                    "completed_valid" if validation.accepted else "completed_invalid"
                ),
                response_artifact_ref=str(response_relative),
                response_sha256=hashlib.sha256(response_bytes).hexdigest(),
                wire_sha256=hashlib.sha256(wire).hexdigest(),
                usage=_usage_payload(result),
                final_agent_item_id=result.final_agent_item_id,
                wall_seconds=perf_counter() - started,
                lifecycle_status="completed",
            )
        except BaseException as error:
            take_wire = getattr(self.client, "take_wire_bytes", None)
            wire = take_wire() if callable(take_wire) else self.client.wire_bytes
            _write_private(self.campaign_dir / wire_relative, wire)
            self._prune_wire_artifacts()
            self.store.complete_turn(
                turn_record_id,
                turn_id=None,
                status="failed",
                wire_sha256=hashlib.sha256(wire).hexdigest(),
                wall_seconds=perf_counter() - started,
                error_kind=type(error).__name__,
                error_detail=str(error)[:4000],
                lifecycle_status=(
                    "timed_out"
                    if isinstance(error, AppServerTurnTimeout)
                    else "failed"
                ),
                terminal_reason=str(error)[:4000],
            )
            raise
        all_turns = (*prior_turns, turn_record_id)
        if not validation.accepted and repair_allowed:
            repair_payload = {
                "repair": (
                    "Return one corrected decision for the exact same committed "
                    "snapshot. Do not change snapshot_id."
                ),
                "director_state_v2": prepared_state.state,
                "invalid_response": result.parsed,
                "validation_errors": [
                    {"path": issue.path, "message": issue.message}
                    for issue in validation.issues
                ],
            }
            repair_prompt = canonical_json(
                repair_payload, max_bytes=MAX_SNAPSHOT_BYTES
            ).decode("ascii")
            return await self._request(
                snapshot=snapshot,
                trigger_id=trigger_id,
                context=context,
                prompt=repair_prompt,
                prior_turns=all_turns,
                repair_allowed=False,
            )
        return DirectorEvidence(
            decision=(
                validation.normalized
                if validation.accepted and validation.normalized is not None
                else result.parsed
            ),
            validation=validation,
            session_record_id=self.session_record_id,
            turn_record_ids=all_turns,
            thread_id=self.session.thread_id,
            turn_id=result.turn_id,
            first_item_latency_seconds=(
                result.first_item_latency_seconds
            ),
            final_answer_latency_seconds=(
                result.final_answer_latency_seconds
            ),
        )

    async def _prepare_context_boundary(self) -> None:
        if self.session is None or self.session_record_id is None:
            raise RuntimeError("Director session has not been started")
        completed = int(
            self.store.connection.execute(
                """
                SELECT count(*) FROM app_server_turns
                WHERE campaign_id=? AND thread_id=?
                  AND status LIKE 'completed_%'
                """,
                (self.campaign_id, self.session.thread_id),
            ).fetchone()[0]
        )
        if completed == 0:
            return
        if self.context_mode is DirectorContextMode.PERSISTENT_THREAD:
            return
        parent_thread_id = self.session.thread_id
        if self.context_mode is DirectorContextMode.COMPACTED_THREAD:
            response = await self.client.compact_thread(self.session)
            relative = (
                Path("director")
                / "compactions"
                / f"{new_id('compaction')}.json"
            )
            payload = {
                "schema_version": "1.0",
                "thread_id": parent_thread_id,
                "boundary": "after_completed_turn_before_next_decision",
                "response": response,
            }
            _write_private(
                self.campaign_dir / relative,
                canonical_json(payload, max_bytes=64 * 1024) + b"\n",
            )
            return
        session = await self.client.start_thread(base_instructions())
        self.store.close_session(
            self.session_record_id, state="rolled_over"
        )
        record_id = self.store.record_session(
            record_id=new_id("app-session"),
            campaign_id=self.campaign_id,
            thread_id=session.thread_id,
            session_id=session.session_id,
            thread_path=session.thread_path,
            parent_thread_id=parent_thread_id,
            model=session.model,
            effort=session.effort,
            codex_version=self.codex_version,
            executable_sha256=self.executable_sha256,
            protocol_schema_sha256=self.protocol_schema_sha256,
        )
        self.session = session
        self.session_record_id = record_id

    async def close(self) -> None:
        await self.client.close()
        if self.session_record_id is not None:
            row = self.store.connection.execute(
                """
                SELECT state FROM app_server_sessions
                WHERE session_record_id=?
                """,
                (self.session_record_id,),
            ).fetchone()
            if row is not None and row["state"] == "active":
                self.store.close_session(self.session_record_id, state="closed")

    def _prune_wire_artifacts(self, maximum: int = 64) -> None:
        paths = sorted(
            (self.audit_dir / "wire").glob("*.jsonl"),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for path in paths[maximum:]:
            path.unlink()

    def _rollover_brief(self, parent_thread_id: str) -> dict[str, Any]:
        campaign = self.store.campaign(self.campaign_id)
        assessment = self.store.connection.execute(
            """
            SELECT campaign_assessment, created_at
            FROM director_action_batches WHERE campaign_id=?
            ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (self.campaign_id,),
        ).fetchone()
        hypotheses = self.store.connection.execute(
            """
            SELECT hypothesis_id, statement, confidence, status, created_at
            FROM research_hypotheses_v2 WHERE campaign_id=?
            ORDER BY created_at DESC, rowid DESC LIMIT 32
            """,
            (self.campaign_id,),
        ).fetchall()
        lanes = self.store.connection.execute(
            """
            SELECT lane_id, lane_version, algorithm, graph_family, state,
                   current_parameters_json, resource_share
            FROM research_lanes WHERE campaign_id=?
            ORDER BY updated_at DESC LIMIT 32
            """,
            (self.campaign_id,),
        ).fetchall()
        return {
            "schema_version": "1.0",
            "campaign_id": self.campaign_id,
            "parent_thread_id": parent_thread_id,
            "target": campaign["target"],
            "stop_mode": campaign["stop_mode"],
            "deadline_at": campaign["deadline_at"],
            "campaign_state_version": campaign["state_version"],
            "latest_assessment": dict(assessment) if assessment else None,
            "hypotheses": [dict(row) for row in hypotheses],
            "lanes": [
                {
                    **dict(row),
                    "parameters": json.loads(row["current_parameters_json"]),
                }
                for row in lanes
            ],
        }


def _usage_payload(result: AppServerTurnResult) -> dict[str, Any] | None:
    usage = result.usage
    if usage is None:
        return None
    return _usage_value(usage)


def _usage_value(usage: Any) -> dict[str, Any]:
    return {
        "input_tokens": usage.input_tokens,
        "cached_input_tokens": usage.cached_input_tokens,
        "cache_write_input_tokens": usage.cache_write_input_tokens,
        "output_tokens": usage.output_tokens,
        "reasoning_output_tokens": usage.reasoning_output_tokens,
        "total_tokens": usage.total_tokens,
        "raw": usage.raw,
    }


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _write_private(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise
    os.replace(temporary, path)
    path.chmod(0o600)
