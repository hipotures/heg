from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import json
import mimetypes

from .state import read_json, atomic_write_json


class DashboardServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], workspace: Path, static_dir: Path):
        self.workspace = workspace.resolve()
        self.static_dir = static_dir.resolve()
        super().__init__(address, DashboardHandler)


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, relative: str) -> None:
        if relative in {"", "/"}:
            relative = "index.html"
        candidate = (self.server.static_dir / relative.lstrip("/")).resolve()
        if self.server.static_dir not in candidate.parents and candidate != self.server.static_dir:
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
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self._json(200, read_json(self.server.workspace / "state.json", default={"status": "IDLE"}))
            return
        if parsed.path == "/api/logs":
            limit_raw = parse_qs(parsed.query).get("limit", ["50"])[0]
            try:
                limit = max(1, min(500, int(limit_raw)))
            except ValueError:
                self._json(400, {"error": "invalid limit"})
                return
            log_path = self.server.workspace / "events.jsonl"
            lines = []
            if log_path.exists():
                lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
            self._json(200, {"lines": lines})
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/control":
            self._json(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0 or length > 4096:
            self._json(400, {"error": "invalid request size"})
            return
        try:
            payload = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid JSON"})
            return
        action = payload.get("action") if isinstance(payload, dict) else None
        if action not in {"START", "PAUSE", "RESUME", "STOP"}:
            self._json(400, {"error": "unsupported action"})
            return
        current = read_json(self.server.workspace / "control.json", default={"version": 0})
        version = int(current.get("version", 0)) + 1
        atomic_write_json(
            self.server.workspace / "control.json",
            {"version": version, "action": action},
        )
        self._json(202, {"accepted": True, "version": version, "action": action})

    def log_message(self, format: str, *args: object) -> None:
        # Keep the starter dashboard quiet; production logging belongs in JSONL.
        return


def serve(workspace: Path, host: str, port: int) -> None:
    static_dir = Path(__file__).resolve().parents[2] / "web"
    server = DashboardServer((host, port), workspace=workspace, static_dir=static_dir)
    print(f"Dashboard: http://{host}:{port}")
    server.serve_forever()
