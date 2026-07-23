from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from subprocess import DEVNULL, Popen
from urllib.parse import parse_qs, urlparse
from typing import Any
import hmac
import json
import mimetypes
import os
import re
import sys

from .resources import recommended_workers
from .search import ALGORITHMS, MODES
from .state import atomic_write_json, read_json, utc_now

ARTIFACT_PATTERN = re.compile(r"^[0-9a-f]{20}\.(?:graph6|json|svg)$")
MAX_JSON_RESPONSE = 2 * 1024 * 1024


class DashboardServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        workspace: Path,
        static_dir: Path,
        token: str | None = None,
    ):
        self.workspace = workspace.resolve()
        self.static_dir = static_dir.resolve()
        self.token = token
        self.runner: Popen[bytes] | None = None
        super().__init__(address, DashboardHandler)

    def current_run_dir(self) -> Path | None:
        state = read_json(self.workspace / "state.json", default={})
        raw = state.get("run_dir")
        if raw:
            candidate = Path(str(raw)).resolve()
            if self.workspace in candidate.parents and candidate.is_dir():
                return candidate
        if (self.workspace / "run.json").is_file():
            return self.workspace
        return None

    def start_run(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if self.runner is not None and self.runner.poll() is None:
            return 409, {"error": "a dashboard-started run is already active"}
        try:
            order = _integer(payload, "order", 4, 128)
            workers = _integer(payload, "workers", 1, max(1, recommended_workers(256)))
            seed = _integer(payload, "seed", 0, 2**31 - 1)
            wall_seconds = _integer(payload, "wall_seconds", 1, 7 * 86400)
            memory_limit = _integer(payload, "memory_limit_bytes", 0, 2**63 - 1)
            mode = str(payload.get("mode", "cubic_first"))
            algorithm = str(payload.get("algorithm", "simulated_annealing"))
            target = str(payload.get("target", "erdos_gyarfas"))
            notes = str(payload.get("notes", ""))
        except (TypeError, ValueError) as error:
            return 400, {"error": str(error)}
        if target != "erdos_gyarfas":
            return 400, {"error": "unsupported target"}
        if mode not in MODES or algorithm not in ALGORITHMS:
            return 400, {"error": "unsupported mode or algorithm"}
        if mode == "cubic_first" and order % 2:
            return 400, {"error": "cubic_first requires an even order"}
        if len(notes) > 500:
            return 400, {"error": "notes exceed 500 characters"}
        command = [
            sys.executable,
            "-m",
            "sglab",
            "run",
            "--target",
            target,
            "--order",
            str(order),
            "--mode",
            mode,
            "--algorithm",
            algorithm,
            "--workers",
            str(workers),
            "--seed",
            str(seed),
            "--time-limit",
            str(wall_seconds),
            "--memory-limit",
            str(memory_limit),
            "--notes",
            notes,
            "--workspace",
            str(self.workspace),
        ]
        logs = self.workspace / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / "dashboard-runner.log").open("ab") as log:
            self.runner = Popen(
                command,
                stdin=DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
                env=os.environ.copy(),
            )
        request = _next_control(self.workspace, "START")
        atomic_write_json(self.workspace / "launch.json", {**payload, **request})
        return 202, {"accepted": True, "pid": self.runner.pid, **request}


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        if len(body) > MAX_JSON_RESPONSE:
            status, body = 507, b'{"error":"response exceeds configured limit"}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if self.server.token is None:
            return True
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.token}"
        return hmac.compare_digest(supplied, expected)

    def _require_authorized(self) -> bool:
        if self._authorized():
            return True
        self._json(401, {"error": "bearer token required"})
        return False

    def _body(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "invalid Content-Length"})
            return None
        if length <= 0 or length > 8192:
            self._json(400, {"error": "invalid request size"})
            return None
        try:
            value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "invalid JSON"})
            return None
        if not isinstance(value, dict):
            self._json(400, {"error": "expected a JSON object"})
            return None
        return value

    def _serve_static(self, relative: str) -> None:
        if relative in {"", "/"}:
            relative = "index.html"
        candidate = (self.server.static_dir / relative.lstrip("/")).resolve()
        if self.server.static_dir not in candidate.parents:
            self.send_error(403)
            return
        if not candidate.is_file():
            self.send_error(404)
            return
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self._json(
                200,
                read_json(
                    self.server.workspace / "state.json",
                    default={"status": "IDLE", "updated_at": utc_now()},
                ),
            )
            return
        if parsed.path == "/api/logs":
            limit = _query_limit(parsed.query, default=50, maximum=500)
            if limit is None:
                self._json(400, {"error": "invalid limit"})
                return
            run_dir = self.server.current_run_dir()
            path = (run_dir or self.server.workspace) / "events.jsonl"
            self._json(200, {"lines": _bounded_tail(path, limit)})
            return
        if parsed.path == "/api/runs":
            runs = []
            root = self.server.workspace / "runs"
            for path in sorted(root.glob("*/run.json"), reverse=True)[:100]:
                try:
                    record = read_json(path)
                    state = read_json(path.parent / "state.json", default={})
                    runs.append({**record, "live_status": state.get("status", "UNKNOWN")})
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
            self._json(200, {"runs": runs})
            return
        if parsed.path == "/api/candidates":
            limit = _query_limit(parsed.query, default=50, maximum=200)
            if limit is None:
                self._json(400, {"error": "invalid limit"})
                return
            run_dir = self.server.current_run_dir()
            records = []
            if run_dir is not None:
                for path in sorted((run_dir / "best").glob("*.json"))[:limit]:
                    try:
                        records.append(read_json(path))
                    except (OSError, ValueError, json.JSONDecodeError):
                        continue
            self._json(200, {"candidates": records})
            return
        if parsed.path.startswith("/api/artifact/"):
            if not self._require_authorized():
                return
            filename = parsed.path.removeprefix("/api/artifact/")
            if not ARTIFACT_PATTERN.fullmatch(filename):
                self._json(400, {"error": "invalid artifact id"})
                return
            run_dir = self.server.current_run_dir()
            if run_dir is None:
                self._json(404, {"error": "no current run"})
                return
            path = (run_dir / "best" / filename).resolve()
            if path.parent != (run_dir / "best").resolve() or not path.is_file():
                self._json(404, {"error": "artifact not found"})
                return
            body = path.read_bytes()
            if len(body) > MAX_JSON_RESPONSE:
                self._json(507, {"error": "artifact exceeds configured limit"})
                return
            self.send_response(200)
            self.send_header(
                "Content-Type",
                mimetypes.guess_type(filename)[0] or "application/octet-stream",
            )
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        if not self._require_authorized():
            return
        parsed = urlparse(self.path)
        payload = self._body()
        if payload is None:
            return
        if parsed.path == "/api/runs":
            status, response = self.server.start_run(payload)
            self._json(status, response)
            return
        if parsed.path != "/api/control":
            self._json(404, {"error": "not found"})
            return
        action = payload.get("action")
        if action not in {"PAUSE", "RESUME", "STOP"}:
            self._json(400, {"error": "unsupported action"})
            return
        request = _next_control(self.server.workspace, str(action))
        self._json(202, {"accepted": True, **request})

    def log_message(self, format: str, *args: object) -> None:
        return


def _integer(payload: dict[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = payload.get(key)
    if isinstance(value, bool):
        raise TypeError(f"{key} must be an integer")
    parsed = int(value)
    if not minimum <= parsed <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return parsed


def _query_limit(query: str, *, default: int, maximum: int) -> int | None:
    raw = parse_qs(query).get("limit", [str(default)])[0]
    try:
        return max(1, min(maximum, int(raw)))
    except ValueError:
        return None


def _next_control(workspace: Path, action: str) -> dict[str, Any]:
    current = read_json(workspace / "control.json", default={"version": 0})
    request = {
        "version": int(current.get("version", 0)) + 1,
        "requested_at": utc_now(),
        "action": action,
    }
    atomic_write_json(workspace / "control.json", request)
    return request


def _bounded_tail(path: Path, limit: int) -> list[str]:
    if not path.exists():
        return []
    with path.open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        handle.seek(max(0, size - 256 * 1024))
        data = handle.read()
    return data.decode("utf-8", errors="replace").splitlines()[-limit:]


def create_server(
    workspace: Path,
    host: str,
    port: int,
    *,
    token: str | None = None,
) -> DashboardServer:
    static_dir = Path(__file__).resolve().parents[2] / "web"
    return DashboardServer(
        (host, port),
        workspace=workspace,
        static_dir=static_dir,
        token=token if token is not None else os.environ.get("SGLAB_WEB_TOKEN"),
    )


def serve(workspace: Path, host: str, port: int) -> None:
    server = create_server(workspace, host, port)
    bound_host, bound_port = server.server_address
    print(f"Dashboard: http://{bound_host}:{bound_port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
