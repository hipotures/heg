from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
import asyncio
import json
import os
import signal
import tempfile

from .auth import prepare_private_directories


DISABLED_FEATURES = (
    "apps",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "in_app_browser",
    "image_generation",
    "multi_agent",
    "multi_agent_v2",
    "plugins",
    "remote_plugin",
    "plugin_sharing",
    "skill_search",
    "skill_mcp_dependency_install",
    "shell_tool",
    "shell_snapshot",
    "unified_exec",
    "code_mode_host",
    "goals",
    "hooks",
    "memories",
    "tool_suggest",
    "workspace_dependencies",
)


class AppServerError(RuntimeError):
    pass


class AppServerTurnTimeout(AppServerError):
    pass


@dataclass(frozen=True, slots=True)
class AppServerConfig:
    application_data: Path
    launcher: tuple[str, ...] = ("codex",)
    model: str | None = None
    effort: str = "high"
    request_timeout_seconds: float = 30.0
    turn_timeout_seconds: float = 900.0
    timeout_drain_seconds: float = 2.0
    usage_wait_seconds: float = 3.0
    graceful_shutdown_seconds: float = 2.0
    termination_timeout_seconds: float = 2.0
    stderr_limit_bytes: int = 256 * 1024
    wire_limit_bytes: int = 8 * 1024 * 1024
    max_jsonl_bytes: int = 2 * 1024 * 1024
    allow_retrying_errors: bool = True
    disabled_features: tuple[str, ...] = DISABLED_FEATURES
    environment: dict[str, str] = field(default_factory=dict)
    environment_exclusions: tuple[str, ...] = ()

    def validate(self) -> None:
        if not self.launcher:
            raise ValueError("launcher cannot be empty")
        for value in (
            self.request_timeout_seconds,
            self.turn_timeout_seconds,
            self.timeout_drain_seconds,
            self.usage_wait_seconds,
            self.graceful_shutdown_seconds,
            self.termination_timeout_seconds,
        ):
            if value < 0:
                raise ValueError("timeouts cannot be negative")
        if min(
            self.stderr_limit_bytes,
            self.wire_limit_bytes,
            self.max_jsonl_bytes,
        ) < 1024:
            raise ValueError("diagnostic bounds must be at least 1024 bytes")


@dataclass(frozen=True, slots=True)
class AppServerUsage:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_output_tokens: int
    total_tokens: int
    raw: dict[str, Any]
    cache_write_input_tokens: int = 0

    @classmethod
    def from_notification(cls, payload: dict[str, Any]) -> AppServerUsage:
        token_usage = dict(payload.get("tokenUsage") or {})
        last = dict(token_usage.get("last") or {})
        return cls(
            input_tokens=int(last.get("inputTokens", 0)),
            cached_input_tokens=int(last.get("cachedInputTokens", 0)),
            cache_write_input_tokens=int(last.get("cacheWriteInputTokens", 0)),
            output_tokens=int(last.get("outputTokens", 0)),
            reasoning_output_tokens=int(last.get("reasoningOutputTokens", 0)),
            total_tokens=int(last.get("totalTokens", 0)),
            raw=token_usage,
        )


@dataclass(frozen=True, slots=True)
class AppServerSession:
    thread_id: str
    session_id: str | None
    thread_path: str | None
    model: str | None
    effort: str
    resumed: bool
    raw_thread: dict[str, Any]
    server_reported_model: str | None = None
    server_reported_effort: str | None = None


@dataclass(frozen=True, slots=True)
class AppServerTurnResult:
    thread_id: str
    turn_id: str
    status: str
    text: str
    parsed: Any
    usage: AppServerUsage | None
    deltas: tuple[str, ...]
    retrying_errors: tuple[dict[str, Any], ...]
    raw_completed_turn: dict[str, Any]
    final_agent_item_id: str | None = None
    request_id: str | int | None = None
    item_ids: tuple[str, ...] = ()
    item_types: tuple[tuple[str, str], ...] = ()
    reasoning_item_ids: tuple[str, ...] = ()
    latest_event_sequence: int = 0
    first_item_latency_seconds: float | None = None
    final_answer_latency_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class AppServerTurnEvent:
    sequence: int
    lifecycle_status: str
    request_id: str | int | None
    thread_id: str
    turn_id: str | None
    method: str
    items: tuple[tuple[str, str], ...] = ()
    terminal_reason: str | None = None
    usage: AppServerUsage | None = None


class _BoundedBytes:
    def __init__(self, limit: int):
        self.limit = limit
        self.parts: deque[bytes] = deque()
        self.size = 0

    def append(self, value: bytes) -> None:
        if len(value) >= self.limit:
            self.parts.clear()
            self.parts.append(value[-self.limit :])
            self.size = self.limit
            return
        self.parts.append(value)
        self.size += len(value)
        while self.size > self.limit and self.parts:
            removed = self.parts.popleft()
            self.size -= len(removed)

    def value(self) -> bytes:
        return b"".join(self.parts)

    def take(self) -> bytes:
        value = self.value()
        self.parts.clear()
        self.size = 0
        return value


class AppServerClient:
    """One persistent, isolated JSON-RPC connection over app-server stdio."""

    def __init__(self, config: AppServerConfig):
        config.validate()
        self.config = config
        self.home, self.sqlite_home, self.work = prepare_private_directories(
            config.application_data
        )
        self.process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()
        self._turn_lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=2048
        )
        self._next_id = 0
        self._fatal: BaseException | None = None
        self._stderr = _BoundedBytes(config.stderr_limit_bytes)
        self._wire = _BoundedBytes(config.wire_limit_bytes)
        self.disabled_skill_paths: tuple[str, ...] = ()
        self.skill_list_before: dict[str, Any] | None = None
        self.skill_list_after: dict[str, Any] | None = None
        self.skills_isolated = False
        self.unsupported_server_requests = 0
        self.last_shutdown_mode: str | None = None
        self._active_request_id: str | int | None = None
        self._active_thread_id: str | None = None
        self._active_turn_id: str | None = None
        self._active_event_sequence = 0
        self._active_event_callback: (
            Callable[[AppServerTurnEvent], None] | None
        ) = None
        self._closing = False

    def _command(self) -> list[str]:
        command = [
            *self.config.launcher,
            "app-server",
            "--stdio",
            "--strict-config",
        ]
        for feature in self.config.disabled_features:
            command.extend(("--disable", feature))
        for override in (
            "project_doc_max_bytes=0",
            "project_doc_fallback_filenames=[]",
            'web_search="disabled"',
            "mcp_servers={}",
        ):
            command.extend(("-c", override))
        return command

    async def start(self) -> None:
        if self.process is not None:
            raise AppServerError("app-server is already started")
        environment = os.environ.copy()
        for name in self.config.environment_exclusions:
            environment.pop(name, None)
        environment.update(self.config.environment)
        environment["CODEX_HOME"] = str(self.home)
        environment["CODEX_SQLITE_HOME"] = str(self.sqlite_home)
        self.process = await asyncio.create_subprocess_exec(
            *self._command(),
            cwd=self.work,
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            limit=self.config.max_jsonl_bytes + 1,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        await self._rpc(
            "initialize",
            {
                "clientInfo": {
                    "name": "sglab-active-director",
                    "title": "Structural Graph Lab Active Director",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        await self._notify("initialized", {})
        await self._disable_all_skills()

    async def _disable_all_skills(self) -> None:
        before = await self._rpc(
            "skills/list",
            {"cwds": [str(self.work)], "forceReload": True},
        )
        if not isinstance(before, dict):
            raise AppServerError("skills/list returned a non-object result")
        self.skill_list_before = before
        self._persist_skill_audit("skills-before.json", before)
        paths: set[str] = set()
        data = before.get("data")
        if not isinstance(data, list):
            raise AppServerError("skills/list omitted data array")
        for entry in data:
            if not isinstance(entry, dict) or not isinstance(entry.get("skills"), list):
                raise AppServerError("skills/list returned malformed data")
            errors = entry.get("errors")
            if not isinstance(errors, list):
                raise AppServerError("skills/list entry omitted errors array")
            if errors:
                raise AppServerError(f"skills/list returned errors: {errors}")
            for skill in entry["skills"]:
                if not isinstance(skill, dict) or not isinstance(
                    skill.get("path"), str
                ):
                    raise AppServerError("skills/list returned a skill without path")
                path = skill["path"]
                if not Path(path).is_absolute():
                    raise AppServerError(f"skill path is not absolute: {path}")
                paths.add(path)
        for path in sorted(paths):
            response = await self._rpc(
                "skills/config/write",
                {"path": path, "enabled": False},
            )
            if response.get("effectiveEnabled") is not False:
                raise AppServerError(f"skill remained enabled: {path}")
        self.disabled_skill_paths = tuple(sorted(paths))
        after = await self._rpc(
            "skills/list",
            {"cwds": [str(self.work)], "forceReload": True},
        )
        if not isinstance(after, dict):
            raise AppServerError("post-disable skills/list returned a non-object")
        self.skill_list_after = after
        self._persist_skill_audit("skills-after.json", after)
        active: list[str] = []
        for entry in after.get("data", []):
            if not isinstance(entry, dict) or not isinstance(entry.get("skills"), list):
                raise AppServerError("post-disable skills/list returned malformed data")
            errors = entry.get("errors")
            if not isinstance(errors, list) or errors:
                raise AppServerError(f"post-disable skills/list errors: {errors}")
            for skill in entry["skills"]:
                path = skill.get("path") if isinstance(skill, dict) else None
                if not isinstance(path, str) or not Path(path).is_absolute():
                    raise AppServerError("post-disable skill path is not absolute")
                if skill.get("enabled") is True:
                    active.append(path)
        if active:
            raise AppServerError(f"skills remained active after reload: {active}")
        self.skills_isolated = True

    def _persist_skill_audit(self, name: str, payload: dict[str, Any]) -> None:
        audit_dir = self.config.application_data.resolve() / "director" / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        audit_dir.chmod(0o700)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{name}.", dir=audit_dir
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o600)
            os.replace(temporary, audit_dir / name)
        finally:
            temporary.unlink(missing_ok=True)

    def _thread_params(self, base_instructions: str) -> dict[str, Any]:
        params: dict[str, Any] = {
            "cwd": str(self.work),
            "sandbox": "read-only",
            "approvalPolicy": "never",
            "baseInstructions": base_instructions,
            "developerInstructions": "",
            "personality": "none",
            "config": {"model_reasoning_effort": self.config.effort},
        }
        if self.config.model:
            params["model"] = self.config.model
        return params

    async def start_thread(self, base_instructions: str) -> AppServerSession:
        if not self.skills_isolated:
            raise AppServerError("refusing thread/start before skill isolation proof")
        params = self._thread_params(base_instructions)
        params.update(
            {
                "ephemeral": False,
                "environments": [],
                "dynamicTools": [],
                "selectedCapabilityRoots": [],
                "runtimeWorkspaceRoots": [],
            }
        )
        result = await self._rpc("thread/start", params)
        return self._session(result, resumed=False)

    async def resume_thread(
        self, thread_id: str, base_instructions: str
    ) -> AppServerSession:
        if not self.skills_isolated:
            raise AppServerError("refusing thread/resume before skill isolation proof")
        params = self._thread_params(base_instructions)
        params["threadId"] = thread_id
        params["runtimeWorkspaceRoots"] = []
        result = await self._rpc("thread/resume", params)
        return self._session(result, resumed=True)

    async def compact_thread(
        self, session: AppServerSession
    ) -> dict[str, Any]:
        """Compact only at an application-selected completed-turn boundary."""

        if not self.skills_isolated:
            raise AppServerError(
                "refusing thread compaction before skill isolation proof"
            )
        result = await self._rpc(
            "thread/compact/start",
            {"threadId": session.thread_id},
        )
        if not isinstance(result, dict):
            raise AppServerError(
                "thread/compact/start returned a non-object result"
            )
        return result

    def _session(self, result: dict[str, Any], *, resumed: bool) -> AppServerSession:
        thread = result.get("thread")
        if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
            raise AppServerError("thread response omitted thread.id")
        reported_model = result.get("model")
        reported_effort = result.get("reasoningEffort")
        return AppServerSession(
            thread_id=thread["id"],
            session_id=thread.get("sessionId"),
            thread_path=thread.get("path"),
            model=(
                str(reported_model)
                if reported_model is not None
                else None
            ),
            effort=str(reported_effort or self.config.effort),
            resumed=resumed,
            raw_thread=thread,
            server_reported_model=(
                str(reported_model)
                if reported_model is not None
                else None
            ),
            server_reported_effort=(
                str(reported_effort)
                if reported_effort is not None
                else None
            ),
        )

    async def turn(
        self,
        session: AppServerSession,
        text: str,
        *,
        output_schema: dict[str, Any] | None = None,
        on_delta: Callable[[str], None] | None = None,
        on_event: Callable[[AppServerTurnEvent], None] | None = None,
    ) -> AppServerTurnResult:
        async with self._turn_lock:
            self._active_request_id = None
            self._active_thread_id = session.thread_id
            self._active_turn_id = None
            self._active_event_sequence = 0
            self._active_event_callback = on_event
            try:
                return await asyncio.wait_for(
                    self._turn(
                        session,
                        text,
                        output_schema,
                        on_delta,
                    ),
                    timeout=self.config.turn_timeout_seconds,
                )
            except TimeoutError as error:
                self._emit_turn_event(
                    "timed_out",
                    method="client/timeout",
                    terminal_reason=(
                        f"wall timeout after "
                        f"{self.config.turn_timeout_seconds:g} seconds"
                    ),
                )
                await self._interrupt_and_drain_timeout(session)
                await self.close(force=True)
                self._drain_queued_timeout_events(session)
                raise AppServerTurnTimeout(
                    "app-server turn timed out"
                ) from error
            finally:
                self._active_event_callback = None
                self._active_request_id = None
                self._active_thread_id = None
                self._active_turn_id = None

    async def _turn(
        self,
        session: AppServerSession,
        text: str,
        output_schema: dict[str, Any] | None,
        on_delta: Callable[[str], None] | None,
    ) -> AppServerTurnResult:
        loop = asyncio.get_running_loop()
        turn_started = loop.time()
        first_item_latency: float | None = None
        final_answer_latency: float | None = None
        params: dict[str, Any] = {
            "threadId": session.thread_id,
            "input": [{"type": "text", "text": text}],
            "cwd": str(self.work),
            "effort": self.config.effort,
            "environments": [],
            "runtimeWorkspaceRoots": [],
        }
        if self.config.model:
            params["model"] = self.config.model
        if output_schema is not None:
            params["outputSchema"] = output_schema
        request_id, response = await self._rpc_with_id(
            "turn/start",
            params,
            on_sent=lambda identifier: self._turn_request_sent(
                session, identifier
            ),
        )
        turn = response.get("turn")
        if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
            raise AppServerError("turn/start omitted turn.id")
        turn_id = turn["id"]
        self._active_turn_id = turn_id
        turn_items = turn.get("items", [])
        if not isinstance(turn_items, list):
            raise AppServerError("turn/start returned malformed items")
        final_messages: list[str] = []
        fallback_messages: list[str] = []
        deltas: list[str] = []
        retrying_errors: list[dict[str, Any]] = []
        started_item_ids: set[str] = set()
        item_types: dict[str, str] = {}
        for item in turn_items:
            item_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(item_id, str) or not item_id:
                raise AppServerError("turn/start item omitted id")
            if item_id in started_item_ids:
                raise AppServerError(f"duplicate turn/start itemId: {item_id}")
            started_item_ids.add(item_id)
            item_types[item_id] = str(item.get("type") or "unknown")
        if item_types:
            first_item_latency = loop.time() - turn_started
        self._emit_turn_event(
            "started",
            method="turn/start",
            items=tuple(sorted(item_types.items())),
        )
        delta_item_ids: set[str] = set()
        completed_item_ids: set[str] = set()
        final_agent_item_id: str | None = None
        usage: AppServerUsage | None = None
        completed_turn: dict[str, Any] | None = None
        while completed_turn is None:
            message = await self._next_notification()
            method = message.get("method")
            payload = message.get("params")
            if not isinstance(payload, dict):
                continue
            if payload.get("threadId") not in (None, session.thread_id):
                continue
            correlated_turn = payload.get("turnId")
            if method == "turn/completed":
                correlated_turn = payload.get("turn", {}).get("id")
            if correlated_turn not in (None, turn_id):
                continue
            if method == "item/agentMessage/delta":
                item_id = payload.get("itemId")
                if not isinstance(item_id, str) or not item_id:
                    raise AppServerError("agent message delta omitted itemId")
                if started_item_ids and item_id not in started_item_ids:
                    raise AppServerError(f"delta references unknown itemId: {item_id}")
                delta_item_ids.add(item_id)
                item_types.setdefault(item_id, "agentMessage")
                if first_item_latency is None:
                    first_item_latency = loop.time() - turn_started
                self._emit_turn_event(
                    "in_progress",
                    method=method,
                    items=((item_id, item_types[item_id]),),
                )
                delta = payload.get("delta")
                if isinstance(delta, str):
                    deltas.append(delta)
                    if on_delta is not None:
                        on_delta(delta)
            elif method == "item/started":
                item = payload.get("item")
                item_id = item.get("id") if isinstance(item, dict) else None
                if not isinstance(item_id, str) or not item_id:
                    raise AppServerError("item/started omitted item.id")
                if item_id in completed_item_ids:
                    raise AppServerError(f"item restarted after completion: {item_id}")
                started_item_ids.add(item_id)
                item_type = str(item.get("type") or "unknown")
                item_types[item_id] = item_type
                if first_item_latency is None:
                    first_item_latency = loop.time() - turn_started
                self._emit_turn_event(
                    "in_progress",
                    method=method,
                    items=((item_id, item_type),),
                )
            elif method == "item/completed":
                item = payload.get("item")
                item_id = item.get("id") if isinstance(item, dict) else None
                if not isinstance(item_id, str) or not item_id:
                    raise AppServerError("item/completed omitted item.id")
                if item_id in completed_item_ids:
                    raise AppServerError(f"duplicate item completion: {item_id}")
                if started_item_ids and item_id not in started_item_ids:
                    raise AppServerError(f"completion references unknown itemId: {item_id}")
                completed_item_ids.add(item_id)
                item_type = str(item.get("type") or "unknown")
                item_types[item_id] = item_type
                if first_item_latency is None:
                    first_item_latency = loop.time() - turn_started
                self._emit_turn_event(
                    "in_progress",
                    method=method,
                    items=((item_id, item_type),),
                )
                if isinstance(item, dict) and item.get("type") == "agentMessage":
                    if delta_item_ids and item_id not in delta_item_ids:
                        raise AppServerError(
                            f"agent completion does not match delta itemId: {item_id}"
                        )
                    value = item.get("text")
                    if isinstance(value, str):
                        if item.get("phase") == "final_answer":
                            final_messages.append(value)
                            final_agent_item_id = item_id
                            final_answer_latency = (
                                loop.time() - turn_started
                            )
                        else:
                            fallback_messages.append(value)
            elif method == "thread/tokenUsage/updated":
                usage = AppServerUsage.from_notification(payload)
                self._emit_turn_event(
                    "in_progress",
                    method=method,
                    usage=usage,
                )
            elif method == "error":
                error = dict(payload.get("error") or {})
                if payload.get("willRetry") is True:
                    if not self.config.allow_retrying_errors:
                        self._emit_turn_event(
                            "failed",
                            method=method,
                            terminal_reason=(
                                "server retry rejected by one-inference policy"
                            ),
                        )
                        raise AppServerError(
                            "server retry rejected by one-inference policy"
                        )
                    retrying_errors.append(error)
                    self._emit_turn_event(
                        "in_progress",
                        method=method,
                        terminal_reason=f"retrying error: {error}",
                    )
                else:
                    self._emit_turn_event(
                        "failed",
                        method=method,
                        terminal_reason=f"terminal error: {error}",
                    )
                    raise AppServerError(f"terminal app-server error: {error}")
            elif method == "thread/status/changed":
                if payload.get("status", {}).get("type") == "systemError":
                    self._emit_turn_event(
                        "failed",
                        method=method,
                        terminal_reason="app-server thread entered systemError",
                    )
                    raise AppServerError("app-server thread entered systemError")
            elif method == "turn/completed":
                completed_turn = dict(payload.get("turn") or {})
                completed_status = str(completed_turn.get("status") or "")
                self._emit_turn_event(
                    (
                        "completed"
                        if completed_status == "completed"
                        else "aborted"
                        if completed_status in {"interrupted", "aborted"}
                        else "failed"
                    ),
                    method=method,
                    items=tuple(
                        sorted(
                            (
                                str(item.get("id")),
                                str(item.get("type") or "unknown"),
                            )
                            for item in completed_turn.get("items", [])
                            if isinstance(item, dict)
                            and isinstance(item.get("id"), str)
                        )
                    ),
                    terminal_reason=(
                        None
                        if completed_status == "completed"
                        else f"turn completed with status {completed_status}"
                    ),
                )
        if completed_turn.get("status") != "completed":
            raise AppServerError(
                f"turn ended with status {completed_turn.get('status')}"
            )
        completed_items = completed_turn.get("items", [])
        if not isinstance(completed_items, list):
            raise AppServerError("turn/completed returned malformed items")
        completed_turn_item_ids: set[str] = set()
        for item in completed_items:
            item_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(item_id, str) or not item_id:
                raise AppServerError("turn/completed item omitted id")
            if item_id in completed_turn_item_ids:
                raise AppServerError(
                    f"duplicate turn/completed itemId: {item_id}"
                )
            completed_turn_item_ids.add(item_id)
        if final_agent_item_id is not None and completed_turn_item_ids:
            if final_agent_item_id not in completed_turn_item_ids:
                raise AppServerError(
                    "final agent itemId is absent from completed turn"
                )
        if self.config.usage_wait_seconds > 0:
            deadline = asyncio.get_running_loop().time() + self.config.usage_wait_seconds
            while asyncio.get_running_loop().time() < deadline:
                timeout = deadline - asyncio.get_running_loop().time()
                try:
                    message = await asyncio.wait_for(
                        self._next_notification(), timeout=timeout
                    )
                except TimeoutError:
                    break
                if (
                    message.get("method") == "thread/tokenUsage/updated"
                    and message.get("params", {}).get("threadId")
                    == session.thread_id
                    and message.get("params", {}).get("turnId") == turn_id
                ):
                    usage = AppServerUsage.from_notification(message["params"])
                    self._emit_turn_event(
                        "completed",
                        method="thread/tokenUsage/updated",
                        usage=usage,
                    )
                elif message.get("method") == "error":
                    payload = message.get("params")
                    if isinstance(payload, dict) and payload.get("willRetry") is not True:
                        raise AppServerError(
                            f"terminal app-server error after completion: {payload}"
                        )
        if final_messages:
            final_text = final_messages[-1]
        elif fallback_messages:
            final_text = fallback_messages[-1]
        else:
            raise AppServerError("completed turn has no agent final message")
        parsed: Any = None
        if output_schema is not None:
            try:
                parsed = json.loads(final_text)
            except json.JSONDecodeError as error:
                raise AppServerError("structured final answer is not JSON") from error
        return AppServerTurnResult(
            thread_id=session.thread_id,
            turn_id=turn_id,
            status="completed",
            text=final_text,
            parsed=parsed,
            usage=usage,
            deltas=tuple(deltas),
            retrying_errors=tuple(retrying_errors),
            raw_completed_turn=completed_turn,
            final_agent_item_id=final_agent_item_id,
            request_id=request_id,
            item_ids=tuple(sorted(item_types)),
            item_types=tuple(sorted(item_types.items())),
            reasoning_item_ids=tuple(
                sorted(
                    item_id
                    for item_id, item_type in item_types.items()
                    if item_type == "reasoning"
                )
            ),
            latest_event_sequence=self._active_event_sequence,
            first_item_latency_seconds=first_item_latency,
            final_answer_latency_seconds=final_answer_latency,
        )

    def _turn_request_sent(
        self, session: AppServerSession, request_id: str | int
    ) -> None:
        self._active_request_id = request_id
        self._active_thread_id = session.thread_id
        self._emit_turn_event("requested", method="turn/start")

    def _emit_turn_event(
        self,
        lifecycle_status: str,
        *,
        method: str,
        items: tuple[tuple[str, str], ...] = (),
        terminal_reason: str | None = None,
        usage: AppServerUsage | None = None,
    ) -> None:
        callback = self._active_event_callback
        if callback is None or self._active_thread_id is None:
            return
        self._active_event_sequence += 1
        callback(
            AppServerTurnEvent(
                sequence=self._active_event_sequence,
                lifecycle_status=lifecycle_status,
                request_id=self._active_request_id,
                thread_id=self._active_thread_id,
                turn_id=self._active_turn_id,
                method=method,
                items=items,
                terminal_reason=terminal_reason,
                usage=usage,
            )
        )

    async def _interrupt_and_drain_timeout(
        self, session: AppServerSession
    ) -> None:
        turn_id = self._active_turn_id
        if (
            turn_id is not None
            and self.process is not None
            and self.process.returncode is None
        ):
            try:
                await asyncio.wait_for(
                    self._rpc(
                        "turn/interrupt",
                        {
                            "threadId": session.thread_id,
                            "turnId": turn_id,
                        },
                    ),
                    timeout=self.config.timeout_drain_seconds,
                )
            except (AppServerError, TimeoutError):
                pass
        deadline = (
            asyncio.get_running_loop().time()
            + self.config.timeout_drain_seconds
        )
        while asyncio.get_running_loop().time() < deadline:
            timeout = deadline - asyncio.get_running_loop().time()
            try:
                message = await asyncio.wait_for(
                    self._next_notification(), timeout=timeout
                )
            except (AppServerError, TimeoutError):
                break
            self._process_timeout_notification(session, message)

    async def interrupt_active_turn(self) -> bool:
        """Request interruption for the authoritative active turn, if known."""

        thread_id = self._active_thread_id
        turn_id = self._active_turn_id
        if (
            thread_id is None
            or turn_id is None
            or self.process is None
            or self.process.returncode is not None
        ):
            return False
        await asyncio.wait_for(
            self._rpc(
                "turn/interrupt",
                {"threadId": thread_id, "turnId": turn_id},
            ),
            timeout=self.config.timeout_drain_seconds,
        )
        return True

    def _drain_queued_timeout_events(
        self, session: AppServerSession
    ) -> None:
        while True:
            try:
                message = self._notifications.get_nowait()
            except asyncio.QueueEmpty:
                return
            self._process_timeout_notification(session, message)

    def _process_timeout_notification(
        self,
        session: AppServerSession,
        message: dict[str, Any],
    ) -> None:
        method = str(message.get("method") or "")
        payload = message.get("params")
        if not isinstance(payload, dict):
            return
        if payload.get("threadId") not in (None, session.thread_id):
            return
        correlated_turn = payload.get("turnId")
        if method == "turn/completed":
            turn = payload.get("turn")
            if not isinstance(turn, dict):
                return
            correlated_turn = turn.get("id")
        if correlated_turn not in (None, self._active_turn_id):
            return
        if method in {"item/started", "item/completed"}:
            item = payload.get("item")
            if isinstance(item, dict) and isinstance(item.get("id"), str):
                self._emit_turn_event(
                    "timed_out",
                    method=method,
                    items=(
                        (
                            str(item["id"]),
                            str(item.get("type") or "unknown"),
                        ),
                    ),
                    terminal_reason="event observed during timeout drain",
                )
        elif method == "thread/tokenUsage/updated":
            self._emit_turn_event(
                "timed_out",
                method=method,
                usage=AppServerUsage.from_notification(payload),
                terminal_reason="usage observed during timeout drain",
            )
        elif method in {"turn/completed", "turn/aborted"}:
            turn = payload.get("turn")
            status = (
                str(turn.get("status") or "")
                if isinstance(turn, dict)
                else "aborted"
            )
            self._emit_turn_event(
                (
                    "aborted"
                    if status in {"interrupted", "aborted", ""}
                    else "timed_out"
                ),
                method=method,
                terminal_reason=(
                    f"timeout followed by terminal status "
                    f"{status or 'aborted'}"
                ),
            )

    async def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        _, result = await self._rpc_with_id(method, params)
        return result

    async def _rpc_with_id(
        self,
        method: str,
        params: dict[str, Any],
        *,
        on_sent: Callable[[str | int], None] | None = None,
    ) -> tuple[str | int, Any]:
        if self._fatal is not None:
            raise AppServerError(f"app-server protocol failed: {self._fatal}")
        loop = asyncio.get_running_loop()
        self._next_id += 1
        request_id = self._next_id
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[request_id] = future
        await self._send({"id": request_id, "method": method, "params": params})
        if on_sent is not None:
            on_sent(request_id)
        try:
            result = await asyncio.wait_for(
                future, timeout=self.config.request_timeout_seconds
            )
            return request_id, result
        except TimeoutError as error:
            self._pending.pop(request_id, None)
            raise AppServerError(f"RPC timed out: {method}") from error
        except asyncio.CancelledError:
            self._pending.pop(request_id, None)
            raise

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send({"method": method, "params": params})

    async def _send(self, payload: dict[str, Any]) -> None:
        process = self.process
        if process is None or process.stdin is None or process.returncode is not None:
            raise AppServerError("app-server is not running")
        line = json.dumps(payload, separators=(",", ":")).encode() + b"\n"
        self._wire.append(b"> " + line)
        async with self._write_lock:
            process.stdin.write(line)
            await process.stdin.drain()

    async def _read_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            while line := await self.process.stdout.readline():
                if len(line) > self.config.max_jsonl_bytes:
                    raise AppServerError("app-server JSONL line exceeded limit")
                self._wire.append(b"< " + line)
                try:
                    message = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    raise AppServerError("malformed app-server JSONL") from error
                if not isinstance(message, dict):
                    raise AppServerError("app-server JSONL message is not an object")
                if "id" in message and "method" not in message:
                    request_id = message["id"]
                    future = self._pending.pop(request_id, None)
                    if future is None or future.done():
                        continue
                    if "error" in message:
                        future.set_exception(
                            AppServerError(f"RPC error: {message['error']}")
                        )
                    else:
                        future.set_result(message.get("result"))
                elif "id" in message and "method" in message:
                    self.unsupported_server_requests += 1
                    await self._send(
                        {
                            "id": message["id"],
                            "error": {
                                "code": -32601,
                                "message": (
                                    f"unsupported server request: {message['method']}"
                                ),
                            },
                        }
                    )
                elif "method" in message:
                    try:
                        self._notifications.put_nowait(message)
                    except asyncio.QueueFull as error:
                        raise AppServerError(
                            "app-server notification queue overflow"
                        ) from error
            if not self._closing:
                raise AppServerError(
                    "app-server stdout closed before client shutdown"
                )
            if self.process.returncode not in (0, None):
                raise AppServerError(
                    f"app-server stdout closed with {self.process.returncode}"
                )
        except BaseException as error:
            self._fail(error)

    async def _read_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        while chunk := await self.process.stderr.read(8192):
            self._stderr.append(chunk)

    def _fail(self, error: BaseException) -> None:
        if isinstance(error, asyncio.CancelledError):
            return
        self._fatal = error
        for future in self._pending.values():
            if not future.done():
                future.set_exception(AppServerError(str(error)))
        self._pending.clear()
        try:
            self._notifications.put_nowait(
                {"method": "client/fatal", "params": {}}
            )
        except asyncio.QueueFull:
            pass

    async def _next_notification(self) -> dict[str, Any]:
        if self._fatal is not None:
            raise AppServerError(f"app-server protocol failed: {self._fatal}")
        message = await self._notifications.get()
        if self._fatal is not None:
            raise AppServerError(f"app-server protocol failed: {self._fatal}")
        return message

    @property
    def stderr_text(self) -> str:
        return self._stderr.value().decode("utf-8", errors="replace")

    @property
    def wire_bytes(self) -> bytes:
        return self._wire.value()

    def take_wire_bytes(self) -> bytes:
        return self._wire.take()

    async def close(self, *, force: bool = False) -> None:
        process = self.process
        if process is None:
            return
        self._closing = True
        if process.stdin is not None:
            process.stdin.close()
            try:
                await process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass
        if process.returncode is None:
            try:
                await asyncio.wait_for(
                    process.wait(), timeout=self.config.graceful_shutdown_seconds
                )
            except TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    await asyncio.wait_for(
                        process.wait(),
                        timeout=self.config.termination_timeout_seconds,
                    )
                    self.last_shutdown_mode = "sigterm"
                except TimeoutError:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await process.wait()
                    self.last_shutdown_mode = "sigkill"
            else:
                self.last_shutdown_mode = "graceful"
        else:
            self.last_shutdown_mode = "graceful"
        drain_tasks = [
            task
            for task in (self._reader_task, self._stderr_task)
            if task is not None
        ]
        if drain_tasks:
            _, pending = await asyncio.wait(
                drain_tasks,
                timeout=self.config.termination_timeout_seconds,
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*drain_tasks, return_exceptions=True)
        self.process = None

    async def __aenter__(self) -> AppServerClient:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> None:
        await self.close(force=exc is not None)
