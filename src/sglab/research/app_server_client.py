from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
import asyncio
import json
import os
import signal

from .auth import prepare_private_directories


DISABLED_FEATURES = (
    "apps",
    "auth_elicitation",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "in_app_browser",
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
    "code_mode",
    "code_mode_host",
    "goals",
    "guardian_approval",
    "hooks",
    "workspace_dependencies",
    "image_generation",
    "tool_call_mcp_elicitation",
    "tool_suggest",
)


class AppServerError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AppServerConfig:
    application_data: Path
    launcher: tuple[str, ...] = ("codex",)
    model: str | None = None
    effort: str = "high"
    request_timeout_seconds: float = 30.0
    turn_timeout_seconds: float = 900.0
    usage_wait_seconds: float = 3.0
    stderr_limit_bytes: int = 256 * 1024
    wire_limit_bytes: int = 8 * 1024 * 1024
    max_jsonl_bytes: int = 2 * 1024 * 1024
    disabled_features: tuple[str, ...] = DISABLED_FEATURES
    environment: dict[str, str] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.launcher:
            raise ValueError("launcher cannot be empty")
        for value in (
            self.request_timeout_seconds,
            self.turn_timeout_seconds,
            self.usage_wait_seconds,
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

    @classmethod
    def from_notification(cls, payload: dict[str, Any]) -> AppServerUsage:
        raw = dict(payload.get("tokenUsage", {}).get("last", {}))
        return cls(
            input_tokens=int(raw.get("inputTokens", 0)),
            cached_input_tokens=int(raw.get("cachedInputTokens", 0)),
            output_tokens=int(raw.get("outputTokens", 0)),
            reasoning_output_tokens=int(raw.get("reasoningOutputTokens", 0)),
            total_tokens=int(raw.get("totalTokens", 0)),
            raw=raw,
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


class AppServerClient:
    """One persistent, isolated JSON-RPC connection over app-server stdio."""

    def __init__(self, config: AppServerConfig):
        config.validate()
        self.config = config
        self.home, self.work = prepare_private_directories(config.application_data)
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
        self.unsupported_server_requests = 0

    def _command(self) -> list[str]:
        command = [*self.config.launcher, "app-server", "--stdio"]
        for feature in self.config.disabled_features:
            command.extend(("--disable", feature))
        for override in (
            "project_doc_max_bytes=0",
            "project_doc_fallback_filenames=[]",
            'web_search="disabled"',
            "mcp_servers={}",
            "tools.view_image=false",
            "analytics.enabled=false",
        ):
            command.extend(("-c", override))
        return command

    async def start(self) -> None:
        if self.process is not None:
            raise AppServerError("app-server is already started")
        environment = os.environ.copy()
        environment.update(self.config.environment)
        environment["CODEX_HOME"] = str(self.home)
        environment["CODEX_SQLITE_HOME"] = str(self.home)
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
        result = await self._rpc(
            "skills/list",
            {"cwds": [str(self.work)], "forceReload": True},
        )
        paths: set[str] = set()
        for entry in result.get("data", []):
            for skill in entry.get("skills", []):
                if skill.get("enabled") is True and isinstance(skill.get("path"), str):
                    paths.add(skill["path"])
        for path in sorted(paths):
            response = await self._rpc(
                "skills/config/write",
                {"path": path, "enabled": False},
            )
            if response.get("effectiveEnabled") is not False:
                raise AppServerError(f"skill remained enabled: {path}")
        self.disabled_skill_paths = tuple(sorted(paths))

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
        params = self._thread_params(base_instructions)
        params["ephemeral"] = False
        result = await self._rpc("thread/start", params)
        return self._session(result, resumed=False)

    async def resume_thread(
        self, thread_id: str, base_instructions: str
    ) -> AppServerSession:
        params = self._thread_params(base_instructions)
        params["threadId"] = thread_id
        result = await self._rpc("thread/resume", params)
        return self._session(result, resumed=True)

    def _session(self, result: dict[str, Any], *, resumed: bool) -> AppServerSession:
        thread = result.get("thread")
        if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
            raise AppServerError("thread response omitted thread.id")
        return AppServerSession(
            thread_id=thread["id"],
            session_id=thread.get("sessionId"),
            thread_path=thread.get("path"),
            model=result.get("model"),
            effort=str(result.get("reasoningEffort") or self.config.effort),
            resumed=resumed,
            raw_thread=thread,
        )

    async def turn(
        self,
        session: AppServerSession,
        text: str,
        *,
        output_schema: dict[str, Any] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> AppServerTurnResult:
        async with self._turn_lock:
            try:
                return await asyncio.wait_for(
                    self._turn(session, text, output_schema, on_delta),
                    timeout=self.config.turn_timeout_seconds,
                )
            except TimeoutError as error:
                await self.close(force=True)
                raise AppServerError("app-server turn timed out") from error

    async def _turn(
        self,
        session: AppServerSession,
        text: str,
        output_schema: dict[str, Any] | None,
        on_delta: Callable[[str], None] | None,
    ) -> AppServerTurnResult:
        params: dict[str, Any] = {
            "threadId": session.thread_id,
            "input": [{"type": "text", "text": text}],
            "cwd": str(self.work),
            "effort": self.config.effort,
        }
        if self.config.model:
            params["model"] = self.config.model
        if output_schema is not None:
            params["outputSchema"] = output_schema
        response = await self._rpc("turn/start", params)
        turn = response.get("turn")
        if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
            raise AppServerError("turn/start omitted turn.id")
        turn_id = turn["id"]
        final_messages: list[str] = []
        fallback_messages: list[str] = []
        deltas: list[str] = []
        retrying_errors: list[dict[str, Any]] = []
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
                delta = payload.get("delta")
                if isinstance(delta, str):
                    deltas.append(delta)
                    if on_delta is not None:
                        on_delta(delta)
            elif method == "item/completed":
                item = payload.get("item")
                if isinstance(item, dict) and item.get("type") == "agentMessage":
                    value = item.get("text")
                    if isinstance(value, str):
                        if item.get("phase") == "final_answer":
                            final_messages.append(value)
                        else:
                            fallback_messages.append(value)
            elif method == "thread/tokenUsage/updated":
                usage = AppServerUsage.from_notification(payload)
            elif method == "error":
                error = dict(payload.get("error") or {})
                if payload.get("willRetry") is True:
                    retrying_errors.append(error)
                else:
                    raise AppServerError(f"terminal app-server error: {error}")
            elif method == "thread/status/changed":
                if payload.get("status", {}).get("type") == "systemError":
                    raise AppServerError("app-server thread entered systemError")
            elif method == "turn/completed":
                completed_turn = dict(payload.get("turn") or {})
        if completed_turn.get("status") != "completed":
            raise AppServerError(
                f"turn ended with status {completed_turn.get('status')}"
            )
        if usage is None and self.config.usage_wait_seconds > 0:
            deadline = asyncio.get_running_loop().time() + self.config.usage_wait_seconds
            while usage is None and asyncio.get_running_loop().time() < deadline:
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
        )

    async def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        if self._fatal is not None:
            raise AppServerError(f"app-server protocol failed: {self._fatal}")
        loop = asyncio.get_running_loop()
        self._next_id += 1
        request_id = self._next_id
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[request_id] = future
        await self._send({"id": request_id, "method": method, "params": params})
        try:
            return await asyncio.wait_for(
                future, timeout=self.config.request_timeout_seconds
            )
        except TimeoutError as error:
            self._pending.pop(request_id, None)
            raise AppServerError(f"RPC timed out: {method}") from error

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

    async def _next_notification(self) -> dict[str, Any]:
        if self._fatal is not None:
            raise AppServerError(f"app-server protocol failed: {self._fatal}")
        return await self._notifications.get()

    @property
    def stderr_text(self) -> str:
        return self._stderr.value().decode("utf-8", errors="replace")

    @property
    def wire_bytes(self) -> bytes:
        return self._wire.value()

    async def close(self, *, force: bool = False) -> None:
        process = self.process
        if process is None:
            return
        if process.stdin is not None:
            process.stdin.close()
        if process.returncode is None:
            try:
                os.killpg(
                    process.pid,
                    signal.SIGKILL if force else signal.SIGTERM,
                )
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except TimeoutError:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
        for task in (self._reader_task, self._stderr_task):
            if task is not None and not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (self._reader_task, self._stderr_task) if task),
            return_exceptions=True,
        )
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
