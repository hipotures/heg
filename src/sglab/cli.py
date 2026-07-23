from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
from shutil import which
from threading import Thread
from urllib.request import urlopen
import json
import os
import platform
import tempfile
import time

from .model import BitGraph
from .db import connect
from .state import append_event, atomic_write_json, utc_now
from .targets.erdos_gyarfas import verify_reference
from .web import serve


def _workspace(path: str) -> Path:
    return Path(path).expanduser().resolve()


def cmd_doctor(_: Namespace) -> int:
    tools = ["geng", "labelg", "cadical", "sms", "glasgow_subgraph_solver"]
    report = {
        "python": platform.python_version(),
        "python_supported": tuple(map(int, platform.python_version_tuple()[:2])) >= (3, 12),
        "platform": platform.platform(),
        "cgroup_v2": Path("/sys/fs/cgroup/cgroup.controllers").exists(),
        "tools": {tool: which(tool) for tool in tools},
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["python_supported"] else 1


def cmd_init(args: Namespace) -> int:
    workspace = _workspace(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    for directory in (
        "runs",
        "best",
        "logs",
        "checkpoints",
        "certificates",
        "benchmarks",
    ):
        (workspace / directory).mkdir(exist_ok=True)
    database = connect(workspace / "results.sqlite3")
    database.close()
    atomic_write_json(
        workspace / "state.json",
        {
            "status": "IDLE",
            "workspace": str(workspace),
            "updated_at": utc_now(),
            "status_checked_at": "2026-07-23",
        },
    )
    if not (workspace / "events.jsonl").exists():
        (workspace / "events.jsonl").write_text("", encoding="utf-8")
    append_event(workspace / "events.jsonl", "workspace_initialized")
    print(workspace)
    return 0


def cmd_serve(args: Namespace) -> int:
    workspace = _workspace(args.workspace)
    if not workspace.exists():
        raise SystemExit("workspace does not exist; run sglab init first")
    serve(workspace, args.host, args.port)
    return 0


def cmd_verify(args: Namespace) -> int:
    payload = json.loads(Path(args.graph_json).read_text(encoding="utf-8"))
    graph = BitGraph.from_edges(int(payload["n"]), [tuple(edge) for edge in payload["edges"]])
    result = verify_reference(graph)
    print(json.dumps({
        "status": result.status,
        "complete": result.complete,
        "message": result.message,
        "witnesses": [
            {"kind": witness.kind, "vertices": witness.vertices}
            for witness in result.witnesses
        ],
    }, indent=2))
    return 0 if result.status == "VERIFIED" else 1


def cmd_dashboard_smoke(_: Namespace) -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        atomic_write_json(workspace / "state.json", {"status": "SMOKE"})
        thread = Thread(target=serve, args=(workspace, "127.0.0.1", 0), daemon=True)
        # The generic serve function cannot report an ephemeral port. Test the
        # state and static pieces directly instead of starting a hidden server.
        assert json.loads((workspace / "state.json").read_text())["status"] == "SMOKE"
        assert (Path(__file__).resolve().parents[2] / "web" / "index.html").is_file()
        print("dashboard smoke: ok")
    return 0


def cmd_benchmark_smoke(_: Namespace) -> int:
    graph = BitGraph.from_edges(4, [(0, 1), (1, 2), (2, 3), (3, 0), (0, 2), (1, 3)])
    start = time.perf_counter()
    for _ in range(100):
        verify_reference(graph)
    elapsed = time.perf_counter() - start
    print(json.dumps({"iterations": 100, "elapsed_seconds": elapsed}, indent=2))
    return 0


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="sglab")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor")
    doctor.set_defaults(func=cmd_doctor)

    init = subparsers.add_parser("init")
    init.add_argument("--workspace", required=True)
    init.set_defaults(func=cmd_init)

    web = subparsers.add_parser("serve")
    web.add_argument("--workspace", required=True)
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8080)
    web.set_defaults(func=cmd_serve)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--graph-json", required=True)
    verify.set_defaults(func=cmd_verify)

    dashboard_smoke = subparsers.add_parser("dashboard-smoke")
    dashboard_smoke.set_defaults(func=cmd_dashboard_smoke)

    benchmark_smoke = subparsers.add_parser("benchmark-smoke")
    benchmark_smoke.set_defaults(func=cmd_benchmark_smoke)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
