from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
from shutil import which
from threading import Thread
from urllib.request import urlopen
import json
import platform
import sys
import tempfile

from .benchmark import calibrate, hardware_metadata, microbenchmark, soak, write_report
from .model import BitGraph
from .certification import certify, verify_cpp
from .config import load_config
from .db import connect
from .external import TOOLS
from .locations import asset_path, cyclecheck_path
from .resources import run_bounded
from .search import ALGORITHMS, MODES, SearchConfig, config_from_run, run_search
from .sat import run_pysat_cegar
from .state import (
    append_event,
    atomic_write_json,
    next_control,
    utc_now,
)
from .targets.erdos_gyarfas import verify_reference
from .web import create_server, serve


def _workspace(path: str) -> Path:
    return Path(path).expanduser().resolve()


def _read_text_limited(
    path: str,
    *,
    encoding: str,
    max_bytes: int = 4 * 1024 * 1024,
) -> str:
    source = Path(path)
    with source.open("rb") as handle:
        payload = handle.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError(f"input exceeds {max_bytes} bytes")
    return payload.decode(encoding)


def cmd_doctor(_: Namespace) -> int:
    external = {tool.name: tool.version() for tool in TOOLS}
    external["cadical"] = {"path": which("cadical"), "version": None}
    cyclecheck = cyclecheck_path()
    cycle_version = (
        run_bounded(
            [str(cyclecheck), "--version"],
            timeout_seconds=5,
            output_limit_bytes=4096,
        )
        if cyclecheck.is_file()
        else None
    )
    report = {
        "python": platform.python_version(),
        "python_supported": tuple(map(int, platform.python_version_tuple()[:2]))
        >= (3, 12),
        "platform": platform.platform(),
        "cgroup_v2": Path("/sys/fs/cgroup/cgroup.controllers").exists(),
        "tools": external,
        "cyclecheck": {
            "path": str(cyclecheck),
            "available": cyclecheck.is_file(),
            "version": (
                cycle_version.stdout.decode("utf-8", errors="replace").strip()
                if cycle_version is not None and cycle_version.status == "OK"
                else None
            ),
        },
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
    if args.graph_json:
        payload = json.loads(_read_text_limited(args.graph_json, encoding="utf-8"))
        graph = BitGraph.from_edges(
            int(payload["n"]), [tuple(edge) for edge in payload["edges"]]
        )
    else:
        graph = BitGraph.from_graph6(_read_text_limited(args.graph6, encoding="ascii"))
    if args.artifact_dir:
        report = certify(
            graph,
            Path(args.artifact_dir).resolve(),
            binary=Path(args.cpp_binary) if args.cpp_binary else None,
            timeout_seconds=args.timeout,
            memory_limit_bytes=args.memory_limit,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return (
            0
            if report["status"] in {"COUNTEREXAMPLE_VERIFIED", "INVALID_CANDIDATE"}
            else 2
        )
    result = verify_reference(graph)
    reference_payload = {
        "status": result.status,
        "complete": result.complete,
        "message": result.message,
        "witnesses": [
            {"kind": witness.kind, "vertices": witness.vertices}
            for witness in result.witnesses
        ],
        "implementation": result.implementation,
        "elapsed_seconds": result.elapsed_seconds,
    }
    if args.reference_only:
        report: dict[str, object] = reference_payload
    else:
        independent = verify_cpp(
            graph,
            Path(args.cpp_binary) if args.cpp_binary else None,
            args.timeout,
            args.memory_limit,
        )
        agrees = (
            (result.status == "VERIFIED" and independent["status"] == "ABSENT")
            or (result.status == "REJECTED" and independent["status"] == "FOUND")
            or result.status == independent["status"] == "INVALID"
        )
        report = {
            "agreement": agrees,
            "reference": reference_payload,
            "independent": independent,
        }
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.reference_only:
        return 0 if result.status == "VERIFIED" else 1
    return 0 if bool(report.get("agreement")) else 2


def cmd_dashboard_smoke(_: Namespace) -> int:
    with tempfile.TemporaryDirectory() as temp_dir:
        workspace = Path(temp_dir)
        atomic_write_json(workspace / "state.json", {"status": "SMOKE"})
        server = create_server(workspace, "127.0.0.1", 0)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address
        try:
            with urlopen(f"http://{host}:{port}/api/status", timeout=2) as response:
                payload = json.load(response)
                status = response.status
            if status != 200 or payload.get("status") != "SMOKE":
                raise RuntimeError("dashboard status endpoint failed its smoke check")
            with urlopen(f"http://{host}:{port}/", timeout=2) as response:
                page = response.read()
                status = response.status
            if status != 200 or b"STRUCTURAL GRAPH LAB" not in page:
                raise RuntimeError("dashboard static page failed its smoke check")
            print("dashboard smoke: ok")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
    return 0


def cmd_benchmark_smoke(_: Namespace) -> int:
    report = microbenchmark(iterations=2, orders=(20, 24, 28, 32))
    report["hardware"] = hardware_metadata(Path.cwd())
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _duration(value: str) -> float:
    units = {"s": 1, "m": 60, "h": 3600}
    try:
        if value[-1].lower() in units:
            return float(value[:-1]) * units[value[-1].lower()]
        return float(value)
    except (ValueError, IndexError) as error:
        raise ValueError(f"invalid duration: {value}") from error


def cmd_run(args: Namespace) -> int:
    loaded = load_config(
        asset_path("configs", "default.toml"),
        asset_path("configs", "targets", "erdos_gyarfas.toml"),
        args.config,
    )
    runtime = loaded["runtime"]
    limits = loaded["limits"]
    storage = loaded["storage"]
    graph = loaded["graph"]
    search = loaded["search"]
    memory_limit_bytes = (
        args.memory_limit
        if args.memory_limit is not None
        else int(limits["memory_max_bytes"])
    )
    configured_memory_high = int(limits["memory_high_bytes"])
    memory_high_bytes = (
        args.memory_high
        if args.memory_high is not None
        else (
            0
            if args.memory_limit is not None
            and memory_limit_bytes > 0
            and configured_memory_high > memory_limit_bytes
            else configured_memory_high
        )
    )
    config = SearchConfig(
        workspace=_workspace(args.workspace),
        target=args.target,
        order=args.order if args.order is not None else int(graph["order"]),
        mode=args.mode or str(search["mode"]),
        algorithm=args.algorithm or str(search["algorithm"]),
        workers=args.workers if args.workers is not None else int(runtime["workers"]),
        seed=args.seed if args.seed is not None else int(search["seeds"][0]),
        wall_seconds=(
            _duration(args.time_limit)
            if args.time_limit is not None
            else float(limits["wall_seconds"])
        ),
        max_candidates=args.max_candidates,
        witness_cap=(
            args.witness_cap
            if args.witness_cap is not None
            else int(search["forbidden_cycle_witness_cap"])
        ),
        queue_capacity=int(runtime["queue_capacity"]),
        archive_top_k=int(storage["archive_top_k"]),
        state_seconds=float(runtime["state_update_seconds"]),
        checkpoint_seconds=float(runtime["checkpoint_seconds"]),
        worker_recycle_candidates=int(runtime["worker_recycle_candidates"]),
        memory_high_bytes=memory_high_bytes,
        memory_limit_bytes=memory_limit_bytes,
        min_free_disk_bytes=int(limits["min_free_disk_bytes"]),
        max_log_bytes=int(limits["max_log_bytes"]),
        notes=args.notes or str(loaded.get("notes", {}).get("text", "")),
        exact_timeout_seconds=args.exact_timeout,
    )
    run_dir = run_search(config)
    print(run_dir)
    return 0


def cmd_resume(args: Namespace) -> int:
    run_dir = _workspace(args.run)
    config = config_from_run(
        run_dir, _duration(args.time_limit) if args.time_limit else None
    )
    print(run_search(config, resume_run=run_dir))
    return 0


def cmd_control(args: Namespace) -> int:
    workspace = _workspace(args.workspace)
    request = next_control(workspace, args.action)
    print(json.dumps(request, sort_keys=True))
    return 0


def cmd_sat(args: Namespace) -> int:
    report = run_pysat_cegar(
        args.order,
        _workspace(args.output),
        timeout_seconds=_duration(args.time_limit),
        seed=args.seed,
        solver_name=args.solver,
        memory_limit_bytes=args.memory_limit,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] != "TOOL_FAILURE" else 2


def cmd_benchmark(args: Namespace) -> int:
    if args.benchmark_command == "calibrate":
        report = calibrate(args.minutes, seeds=args.seeds, jobs=args.jobs)
    elif args.benchmark_command == "soak":
        report = soak(
            _workspace(args.workspace),
            hours=args.hours,
            order=args.order,
            workers=args.workers,
        )
    else:
        report = microbenchmark(iterations=args.iterations)
    output = _workspace(args.output)
    output.mkdir(parents=True, exist_ok=True)
    report["target"] = "erdos_gyarfas"
    report["reproduce_argv"] = ["sglab", *sys.argv[1:]]
    report["hardware"] = hardware_metadata(output)
    paths = write_report(report, output)
    print(json.dumps({"json": str(paths[0]), "markdown": str(paths[1])}, indent=2))
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
    graph_input = verify.add_mutually_exclusive_group(required=True)
    graph_input.add_argument("--graph-json")
    graph_input.add_argument("--graph6")
    verify.add_argument("--artifact-dir")
    verify.add_argument("--cpp-binary")
    verify.add_argument("--timeout", type=float, default=0)
    verify.add_argument("--memory-limit", type=int, default=0)
    verify.add_argument("--reference-only", action="store_true")
    verify.set_defaults(func=cmd_verify)

    dashboard_smoke = subparsers.add_parser("dashboard-smoke")
    dashboard_smoke.set_defaults(func=cmd_dashboard_smoke)

    benchmark_smoke = subparsers.add_parser("benchmark-smoke")
    benchmark_smoke.set_defaults(func=cmd_benchmark_smoke)

    run = subparsers.add_parser("run")
    run.add_argument("--target", choices=["erdos_gyarfas"], default="erdos_gyarfas")
    run.add_argument("--config")
    run.add_argument("--order", type=int)
    run.add_argument("--mode", choices=sorted(MODES))
    run.add_argument("--algorithm", choices=sorted(ALGORITHMS))
    run.add_argument("--workers", type=int)
    run.add_argument("--seed", type=int)
    run.add_argument("--time-limit")
    run.add_argument("--max-candidates", type=int, default=0)
    run.add_argument("--witness-cap", type=int)
    run.add_argument("--memory-high", type=int)
    run.add_argument("--memory-limit", type=int)
    run.add_argument("--notes")
    run.add_argument("--exact-timeout", type=float, default=30)
    run.add_argument("--workspace", required=True)
    run.set_defaults(func=cmd_run)

    resume = subparsers.add_parser("resume")
    resume.add_argument("--run", required=True)
    resume.add_argument("--time-limit")
    resume.set_defaults(func=cmd_resume)

    control = subparsers.add_parser("control")
    control.add_argument("--workspace", required=True)
    control.add_argument("--action", choices=["PAUSE", "RESUME", "STOP"], required=True)
    control.set_defaults(func=cmd_control)

    sat = subparsers.add_parser("sat")
    sat.add_argument("--order", type=int, required=True)
    sat.add_argument("--output", required=True)
    sat.add_argument("--time-limit", default="60s")
    sat.add_argument("--seed", type=int, default=1)
    sat.add_argument("--solver", default="cadical195")
    sat.add_argument("--memory-limit", type=int, default=0)
    sat.set_defaults(func=cmd_sat)

    benchmark = subparsers.add_parser("benchmark")
    benchmark_commands = benchmark.add_subparsers(
        dest="benchmark_command", required=True
    )
    calibration = benchmark_commands.add_parser("calibrate")
    calibration.add_argument("--minutes", type=float, default=15)
    calibration.add_argument("--seeds", type=int, default=2)
    calibration.add_argument("--jobs", type=int)
    calibration.add_argument(
        "--target", choices=["erdos_gyarfas"], default="erdos_gyarfas"
    )
    calibration.add_argument("--output", required=True)
    calibration.set_defaults(func=cmd_benchmark)
    micro = benchmark_commands.add_parser("micro")
    micro.add_argument("--iterations", type=int, default=10)
    micro.add_argument("--output", required=True)
    micro.set_defaults(func=cmd_benchmark)
    soak_parser = benchmark_commands.add_parser("soak")
    soak_parser.add_argument("--hours", type=float, default=2)
    soak_parser.add_argument("--order", type=int, default=32)
    soak_parser.add_argument("--workers", type=int, default=1)
    soak_parser.add_argument("--workspace", required=True)
    soak_parser.add_argument("--output", required=True)
    soak_parser.set_defaults(func=cmd_benchmark)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
