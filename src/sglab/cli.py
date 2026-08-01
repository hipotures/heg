from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
from shutil import which
from subprocess import DEVNULL, Popen
from threading import Thread
from urllib.request import urlopen
import asyncio
import fcntl
import hashlib
import json
import os
import platform
import sqlite3
import sys
import tempfile

from .benchmark import (
    calibrate,
    hardware_metadata,
    microbenchmark,
    mutation_cache_benchmark,
    score_kernel_benchmark,
    soak,
    write_report,
)
from .model import BitGraph
from .certification import certify, verify_cpp
from .config import load_config
from .comparisons import (
    import_campaign_snapshot_fixture,
    import_comparison_fixture_bundle,
    import_m6_context_report,
    run_replay_dry_run,
)
from .comparison_worker import ComparisonWorker
from .db import connect
from .external import TOOLS
from .locations import asset_path, cyclecheck_path, score_worker_path
from .resources import run_bounded
from .research.app_server_protocol import generate_protocol_preflight
from .research.auth import (
    director_home,
    import_authorized_auth,
)
from .research.campaign import (
    CampaignPlanError,
    PREPARED_CAMPAIGN_POINTER,
    ResearchCampaignRunner,
    campaign_application_data,
    campaign_status,
    load_prepared_campaign_plan,
    parse_duration,
    prepare_campaign_plan,
    request_campaign_control,
    validate_campaign_plan_fingerprint,
)
from .research.compliance import run_no_model_compliance_audit
from .research.control_study import ControlStudyBudget, ControlStudyRunner
from .research.context_screen import (
    prepare_context_screen_phase_a,
    run_authenticated_context_screen,
)
from .research.export import export_campaign
from .research.continuity import repository_commit
from .research.resume import build_resume_preview, campaign_plan
from .research.experiment import (
    run_authenticated_experiment,
    run_phase_a_audit,
)
from .research.inspection import inspect_persisted_sessions
from .research.operator import (
    ExperimentConfig,
    ExperimentConfigError,
    load_experiment_config,
)
from .research.store import ResearchStore
from .research.proposal_ranking_replay import (
    build_replay_records,
    run_faithful_heg_benchmark,
    run_red_team,
    run_replay,
)
from .research.proposal_ranking import (
    CATALOG_ID as PROPOSAL_RANKING_CATALOG_ID,
    PolicyWorker,
    build_context as build_proposal_ranking_context,
    verify_frozen_policy,
)
from .search import ALGORITHMS, MODES, SearchConfig, config_from_run, run_search
from .sat import run_pysat_cegar
from .state import (
    append_event,
    atomic_write_json,
    read_json,
    next_control,
    utc_now,
)
from .targets import TARGETS
from .ui_fixture import create_ui_fixture
from .web import create_server, serve


def _workspace(path: str) -> Path:
    return Path(path).expanduser().resolve()


FIRST_REAL_GRAPH_WORKSPACE_MARKER = {
    "workspace_kind": "first_real_graph_campaign",
    "synthetic_data": False,
    "marker_schema_version": 1,
}


def _workspace_has_campaign_data(workspace: Path) -> bool:
    """Return whether a marker-less workspace contains scientific data.

    A normal ``sglab init`` workspace has an empty SQLite schema and the
    standard directories, so it is safe for the operator-facing campaign
    commands to upgrade it with the explicit first-real-graph marker. Any
    existing campaign, legacy run, prepared pointer, or active pointer makes
    that upgrade unsafe and is rejected instead of being overwritten.
    """

    allowed_entries = {
        "runs",
        "best",
        "logs",
        "checkpoints",
        "certificates",
        "benchmarks",
        "results.sqlite3",
        "results.sqlite3-wal",
        "results.sqlite3-shm",
        "state.json",
        "events.jsonl",
        ".workspace-init.lock",
    }
    if any(child.name not in allowed_entries for child in workspace.iterdir()):
        return True
    database = workspace / "results.sqlite3"
    if database.is_file():
        with connect(database) as connection:
            for table in (
                "research_campaigns",
                "runs",
                "candidates",
            ):
                try:
                    count = connection.execute(
                        f"SELECT count(*) FROM {table}"
                    ).fetchone()[0]
                except sqlite3.OperationalError:
                    count = 0
                if int(count or 0) > 0:
                    return True
    return any(
        (workspace / name).exists()
        for name in (
            PREPARED_CAMPAIGN_POINTER,
            "active-research-campaign.json",
        )
    )


def _ensure_first_real_graph_workspace(
    workspace: Path,
    *,
    allow_upgrade: bool = True,
) -> Path:
    """Create or validate the non-synthetic campaign workspace marker.

    The marker is written atomically while holding a workspace-local lock.
    Existing explicit markers are never changed. A marker-less workspace is
    upgraded only when it is demonstrably empty (including a fresh generic
    ``sglab init`` workspace); populated or incompatible workspaces fail
    closed.
    """

    root = workspace.expanduser().resolve()
    if root in {Path("/"), Path.home().resolve()}:
        raise ValueError("refusing a broad campaign workspace")
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".workspace-init.lock"
    with lock_path.open("a", encoding="ascii") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        marker_path = root / "workspace.json"
        marker = read_json(marker_path, default={})
        if marker:
            if (
                marker.get("workspace_kind")
                != FIRST_REAL_GRAPH_WORKSPACE_MARKER["workspace_kind"]
                or marker.get("synthetic_data")
                is not FIRST_REAL_GRAPH_WORKSPACE_MARKER["synthetic_data"]
            ):
                raise ValueError(
                    "workspace marker is incompatible with a first-real-graph campaign"
                )
        elif not allow_upgrade:
            raise ValueError(
                "workspace requires an explicit first-real-graph campaign marker"
            )
        elif _workspace_has_campaign_data(root):
            raise ValueError(
                "refusing to upgrade a non-empty marker-less workspace"
            )
        else:
            atomic_write_json(
                marker_path,
                {
                    **FIRST_REAL_GRAPH_WORKSPACE_MARKER,
                    "initialized_at": utc_now(),
                    "initialized_by": "sglab",
                },
            )
        for directory in (
            "runs",
            "best",
            "logs",
            "checkpoints",
            "certificates",
            "benchmarks",
        ):
            (root / directory).mkdir(exist_ok=True)
        database = connect(root / "results.sqlite3")
        database.close()
        if not (root / "state.json").exists():
            atomic_write_json(
                root / "state.json",
                {
                    "status": "IDLE",
                    "workspace": str(root),
                    "updated_at": utc_now(),
                    "status_checked_at": "2026-07-23",
                },
            )
        if not (root / "events.jsonl").exists():
            (root / "events.jsonl").write_text("", encoding="utf-8")
        append_event(root / "events.jsonl", "workspace_initialized")
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return root


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
    score_worker = score_worker_path()
    score_worker_version = (
        run_bounded(
            [str(score_worker), "--version"],
            timeout_seconds=5,
            output_limit_bytes=4096,
        )
        if score_worker.is_file()
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
        "score_worker": {
            "path": str(score_worker),
            "available": score_worker.is_file(),
            "version": (
                score_worker_version.stdout.decode(
                    "utf-8", errors="replace"
                ).strip()
                if score_worker_version is not None
                and score_worker_version.status == "OK"
                else None
            ),
        },
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["python_supported"] else 1


def cmd_proposal_ranking(args: Namespace) -> int:
    """Run a bounded identity, worker-call, and shutdown health check."""

    del args
    report: dict[str, object] = {
        "catalog_id": PROPOSAL_RANKING_CATALOG_ID,
        "identity": None,
        "worker_before": None,
        "worker_after_call": None,
        "worker_after_close": None,
        "priority": None,
        "clean_shutdown": False,
        "no_orphan": False,
        "ok": False,
    }
    worker: PolicyWorker | None = None
    try:
        identity = verify_frozen_policy()
        if identity.get("catalog_id") != PROPOSAL_RANKING_CATALOG_ID:
            raise RuntimeError("frozen policy catalog identity mismatch")
        report["identity"] = identity
        context = build_proposal_ranking_context(
            BitGraph.empty(4), capped_cycle_counts=(0,) * 6
        ).as_dict()
        proposal_id = hashlib.sha256(
            b"sglab-proposal-ranking-doctor"
        ).hexdigest()
        proposal = {
            "schema_version": "stage2b.proposal.v1",
            "proposal_id": proposal_id,
            "k": 2,
            "operator_family": "legal_2_switch",
            "selector_tags": ["uniform_random"],
            "anchor_forbidden_length": None,
            "broken_sampled_witnesses_by_length": [0] * 6,
            "removed_edge_load_sum_by_length": [0] * 6,
            "removed_edge_load_max_by_length": [0] * 6,
            "minimum_distance_between_removed_edges": 0,
            "mean_distance_between_removed_edges": 0.0,
            "minimum_preexisting_distance_for_new_edges": 0,
            "mean_preexisting_distance_for_new_edges": 0.0,
            "local_triangle_risk": 0,
            "local_c4_risk": 0,
            "reconnection_span": 0.0,
        }
        worker = PolicyWorker()
        report["worker_before"] = worker.telemetry()
        report["priority"] = worker.call(context, proposal)
        report["worker_after_call"] = worker.telemetry()
        worker.close()
        report["worker_after_close"] = worker.telemetry()
        after_close = report["worker_after_close"]
        if isinstance(after_close, dict):
            report["clean_shutdown"] = not bool(after_close.get("usable"))
            report["no_orphan"] = int(after_close.get("orphan_count", 0)) == 0
        after_call = report["worker_after_call"]
        report["ok"] = bool(
            isinstance(after_call, dict)
            and int(after_call.get("calls", 0)) == 1
            and int(after_call.get("failures", 0)) == 0
            and bool(report["clean_shutdown"])
            and bool(report["no_orphan"])
        )
    except BaseException as error:
        report["error"] = f"{type(error).__name__}: {error}"
        if worker is not None:
            try:
                worker.close()
                report["worker_after_close"] = worker.telemetry()
            except BaseException:
                pass
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if bool(report["ok"]) else 1


def cmd_init(args: Namespace) -> int:
    workspace = _workspace(args.workspace)
    if args.kind == "first-real-graph-campaign":
        print(_ensure_first_real_graph_workspace(workspace))
        return 0
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
            target=args.target,
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
    plugin = TARGETS[args.target]
    result = plugin.exact_verify(graph)
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
            lengths=plugin.forbidden_lengths(graph.n),
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
            if status != 200 or b"Structural Graph Lab" not in page:
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
    if args.benchmark_command == "proposal-ranking":
        output = _workspace(args.output)
        output.mkdir(parents=True, exist_ok=True)
        if args.corpus:
            from .research.proposal_ranking_replay import load_replay

            records = load_replay(args.corpus)["records"]
        else:
            records = build_replay_records()
        replay = run_replay(records)
        red_team = run_red_team()
        benchmark = run_faithful_heg_benchmark(
            records,
            calls=100_000,
            e2e_evaluations=args.e2e_evaluations,
        )
        report = {
            "schema_version": "stage7.heg.acceptance.v1",
            "kind": "proposal_ranking",
            "replay": replay.as_dict(),
            "red_team": red_team,
            "benchmark": benchmark,
            "status": (
                "passed"
                if replay.passed
                and red_team["status"] == "passed"
                and benchmark["status"] == "passed"
                else "no_go"
            ),
        }
        path = output / "stage7-heg-acceptance.json"
        atomic_write_json(path, report)
        print(json.dumps({"json": str(path), "status": report["status"]}, indent=2))
        return 0 if report["status"] == "passed" else 2
    if args.benchmark_command == "active-director-controls":
        budget = (
            ControlStudyBudget(wall_seconds=10, seeds=(1701, 2903))
            if args.smoke
            else ControlStudyBudget()
        )
        report = ControlStudyRunner(
            workspace=_workspace(args.workspace),
            output=_workspace(args.output),
            budget=budget,
        ).run()
        print(
            json.dumps(
                {
                    "json": report["json_report"],
                    "markdown": report["markdown_report"],
                },
                indent=2,
            )
        )
        return 0
    if args.benchmark_command == "calibrate":
        report = calibrate(args.minutes, seeds=args.seeds, jobs=args.jobs)
    elif args.benchmark_command == "score-kernel":
        report = score_kernel_benchmark(
            iterations=args.iterations,
            backend_evaluations=args.backend_evaluations,
            search_evaluations=args.search_evaluations,
        )
    elif args.benchmark_command == "mutation-cache":
        report = mutation_cache_benchmark(
            episodes=args.episodes,
            evaluations=args.evaluations,
            order=args.order,
        )
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
    hardware = hardware_metadata(output)
    report["hardware"] = hardware
    cgroup_peak = hardware.get("cgroup_usage", {}).get("memory_peak")
    if report["kind"] != "soak" and str(cgroup_peak).isdigit():
        report["ru_maxrss_bytes"] = report["peak_rss_bytes"]
        report["peak_rss_bytes"] = int(cgroup_peak)
        report["peak_rss_source"] = "cgroup_v2 memory.peak"
    else:
        report["peak_rss_source"] = (
            "sampled master-plus-worker RSS"
            if report["kind"] == "soak"
            else "resource.getrusage"
        )
    paths = write_report(report, output)
    print(json.dumps({"json": str(paths[0]), "markdown": str(paths[1])}, indent=2))
    return 0


def cmd_ai_director(args: Namespace) -> int:
    workspace = _workspace(args.workspace)
    application_data = workspace / ".sglab"
    if args.ai_director_command == "preflight":
        report = generate_protocol_preflight(args.codex)
        output = (
            Path(args.output).expanduser().resolve()
            if args.output
            else application_data / "director" / "preflight.json"
        )
        atomic_write_json(output, report)
        print(json.dumps({**report, "report_path": str(output)}, indent=2, sort_keys=True))
        return 0
    if args.ai_director_command == "compliance-audit":
        report = asyncio.run(
            run_no_model_compliance_audit(
                codex=args.codex,
                application_data=application_data / "no-model-compliance",
            )
        )
        output = (
            Path(args.output).expanduser().resolve()
            if args.output
            else application_data / "director" / "no-model-compliance.json"
        )
        atomic_write_json(output, report)
        print(
            json.dumps(
                {**report, "report_path": str(output)},
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if report["ok"] else 1
    if args.ai_director_command == "auth-import":
        destination = import_authorized_auth(
            Path(args.from_codex_home),
            application_data,
        )
        print(
            json.dumps(
                {
                    "imported": True,
                    "destination": str(destination),
                    "copied": ["auth.json"],
                },
                sort_keys=True,
            )
        )
        return 0
    home = director_home(application_data)
    sessions = inspect_persisted_sessions(
        workspace / "results.sqlite3",
        home,
    )
    print(
        json.dumps(
            {
                "codex_home": str(home),
                "auth_imported": (home / "auth.json").is_file(),
                "sessions": sessions,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_ai_experiment(args: Namespace) -> int:
    workspace = _workspace(args.workspace)
    if args.ai_experiment_command == "phase-a":
        report = run_phase_a_audit(workspace)
    elif args.ai_experiment_command == "context-screen-phase-a":
        report = prepare_context_screen_phase_a(
            workspace,
            source_workspace=Path(args.source_workspace),
        )
    elif args.ai_experiment_command == "context-screen-run":
        report = run_authenticated_context_screen(
            workspace,
            source_workspace=Path(args.source_workspace),
            codex=args.codex,
            turn_timeout_seconds=args.turn_timeout_seconds,
        )
    else:
        report = run_authenticated_experiment(
            workspace,
            codex=args.codex,
            evaluation_cap=args.evaluation_cap,
            resume=args.resume,
            context_mode=args.context_mode,
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


EXPERIMENT_STATE_FILE = Path(".sglab") / "experiment-state.json"


def _experiment_state_path(workspace: Path) -> Path:
    return workspace.resolve() / EXPERIMENT_STATE_FILE


def _write_experiment_state(
    workspace: Path,
    *,
    config: ExperimentConfig,
    campaign_id: str,
    plan_fingerprint: str,
    proposal_ranking: str | None,
    state: str,
    director_mode: str,
    pid: int | None = None,
) -> None:
    payload: dict[str, object] = {
        "schema_version": 1,
        "experiment_id": config.experiment_id,
        "campaign_id": campaign_id,
        "plan_fingerprint": plan_fingerprint,
        "proposal_ranking": proposal_ranking,
        "director_mode": director_mode,
        "workspace": str(workspace.resolve()),
        "state": state,
        "updated_at": utc_now(),
    }
    if pid is not None:
        payload["pid"] = pid
    atomic_write_json(_experiment_state_path(workspace), payload)


def _read_experiment_state(workspace: Path) -> dict[str, object]:
    state = read_json(_experiment_state_path(workspace), default={})
    if not state:
        return {}
    if state.get("schema_version") != 1:
        raise ValueError("experiment state schema is unsupported")
    if not isinstance(state.get("experiment_id"), str):
        raise ValueError("experiment state has no experiment ID")
    if not isinstance(state.get("campaign_id"), str):
        raise ValueError("experiment state has no campaign ID")
    return state


def _process_is_live(pid_value: object) -> bool:
    try:
        pid = int(pid_value)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _launch_experiment_campaign(
    workspace: Path,
    *,
    campaign_id: str,
    plan_fingerprint: str | None,
    time_limit: str,
    resume: bool,
) -> int:
    if resume:
        command = [
            sys.executable,
            "-m",
            "sglab",
            "research-campaign",
            "resume",
            "--workspace",
            str(workspace),
            "--campaign-id",
            campaign_id,
            "--additional-time",
            time_limit,
        ]
    else:
        if not plan_fingerprint:
            raise ValueError("prepared experiment is missing its fingerprint")
        command = [
            sys.executable,
            "-m",
            "sglab",
            "research-campaign",
            "start",
            "--workspace",
            str(workspace),
            "--time-limit",
            time_limit,
            "--plan-fingerprint",
            plan_fingerprint,
        ]
    logs = workspace / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    log_path = logs / "experiment-runner.log"
    if log_path.is_file() and log_path.stat().st_size >= 16 * 1024 * 1024:
        os.replace(log_path, log_path.with_suffix(".log.1"))
    with log_path.open("ab") as log:
        process = Popen(
            command,
            stdin=DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
            env=os.environ.copy(),
        )
    return int(process.pid)


def _experiment_summary(
    config: ExperimentConfig,
    *,
    state: str,
    proposal_ranking: str | None,
    resumed: bool,
) -> dict[str, object]:
    return {
        "ok": True,
        "experiment_id": config.experiment_id,
        "workspace": str(config.workspace),
        "state": state,
        "resumed": resumed,
        "director_mode": config.director_mode,
        "proposal_ranking": proposal_ranking,
        "proposal_ranking_enabled": proposal_ranking is not None,
        "dashboard": "serve this workspace with sglab serve",
    }


def cmd_experiment(args: Namespace) -> int:
    if args.experiment_command != "run":
        raise SystemExit("unsupported experiment command")
    try:
        config = load_experiment_config(args.config)
        duration = parse_duration(config.time_limit)
        if duration != 3600:
            raise ExperimentConfigError(
                "the first real graph experiment contract is fixed at one hour"
            )
        workspace = _ensure_first_real_graph_workspace(config.workspace)
        state = _read_experiment_state(workspace)
        if state and state.get("experiment_id") != config.experiment_id:
            raise ExperimentConfigError(
                "workspace is already bound to a different experiment ID"
            )
        campaign_id = str(state.get("campaign_id")) if state else None
        if campaign_id is None:
            pointer = read_json(
                workspace / PREPARED_CAMPAIGN_POINTER,
                default={},
            )
            if pointer.get("campaign_id"):
                campaign_id = str(pointer["campaign_id"])

        if campaign_id is None:
            plan = prepare_campaign_plan(
                workspace,
                duration_seconds=duration,
                director_mode=config.director_mode,
                proposal_ranking=config.proposal_ranking,
            )
            if config.director_mode == "llm":
                import_authorized_auth(
                    config.codex_home,
                    campaign_application_data(
                        workspace,
                        str(plan["campaign_id"]),
                    ),
                )
            # Re-read the immutable artifact after credential import so the
            # process boundary receives the exact bytes that were prepared.
            plan = load_prepared_campaign_plan(
                workspace,
                campaign_id=str(plan["campaign_id"]),
                expected_fingerprint=str(plan["plan_fingerprint"]),
            )
            pid = _launch_experiment_campaign(
                workspace,
                campaign_id=str(plan["campaign_id"]),
                plan_fingerprint=str(plan["plan_fingerprint"]),
                time_limit=config.time_limit,
                resume=False,
            )
            _write_experiment_state(
                workspace,
                config=config,
                campaign_id=str(plan["campaign_id"]),
                plan_fingerprint=str(plan["plan_fingerprint"]),
                proposal_ranking=plan.get("proposal_ranking"),
                state="starting",
                director_mode=str(plan["director_mode"]),
                pid=pid,
            )
            print(
                json.dumps(
                    _experiment_summary(
                        config,
                        state="starting",
                        proposal_ranking=plan.get("proposal_ranking"),
                        resumed=False,
                    ),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        status = campaign_status(workspace, campaign_id)
        if status.get("state") in {"IDLE", "NOT_FOUND", "SCHEMA_UNAVAILABLE"}:
            raise ExperimentConfigError(
                "experiment state references an unavailable campaign"
            )
        plan = None
        stored_ranking = state.get("proposal_ranking")
        projected_ranking = status.get("proposal_ranking")
        if status.get("state") == "prepared":
            plan = load_prepared_campaign_plan(
                workspace,
                campaign_id=campaign_id,
                expected_fingerprint=(
                    str(state["plan_fingerprint"])
                    if state.get("plan_fingerprint")
                    else None
                ),
            )
            projected_ranking = plan.get("proposal_ranking")
        elif status.get("resume_supported"):
            # Resume must validate the durable plan before launching a new
            # execution attempt; the runner repeats this check at the child
            # process boundary.
            plan = campaign_plan(workspace, campaign_id)
            projected_ranking = plan.get("proposal_ranking")
        if config.proposal_ranking_explicit and config.proposal_ranking != projected_ranking:
            raise ExperimentConfigError(
                "experiment ID is already bound to a different proposal-ranking contract"
            )
        effective_ranking = projected_ranking or stored_ranking
        if effective_ranking is not None and config.director_mode == "passive":
            raise ExperimentConfigError(
                "proposal-ranking activation requires LLM Director mode"
            )
        effective_mode = str(
            (plan or {}).get("director_mode")
            or state.get("director_mode")
            or status.get("director_mode")
            or config.director_mode
        )
        if config.director_mode_explicit and effective_mode != config.director_mode:
            raise ExperimentConfigError(
                "experiment ID is already bound to a different Director mode"
            )
        config_for_summary = ExperimentConfig(
            config_path=config.config_path,
            experiment_id=config.experiment_id,
            workspace=config.workspace,
            time_limit=config.time_limit,
            director_mode=effective_mode,
            director_mode_explicit=config.director_mode_explicit,
            proposal_ranking=effective_ranking,
            proposal_ranking_explicit=config.proposal_ranking_explicit,
            codex_home=config.codex_home,
        )
        if status.get("state") == "running":
            process = status.get("process") or {}
            if _process_is_live(process.get("pid")):
                print(
                    json.dumps(
                        _experiment_summary(
                            config_for_summary,
                            state="running",
                            proposal_ranking=effective_ranking,
                            resumed=True,
                        ),
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0
        resumable = bool(status.get("resume_supported"))
        if status.get("state") == "prepared":
            assert plan is not None
            pid = _launch_experiment_campaign(
                workspace,
                campaign_id=campaign_id,
                plan_fingerprint=str(plan["plan_fingerprint"]),
                time_limit=config.time_limit,
                resume=False,
            )
            _write_experiment_state(
                workspace,
                config=config_for_summary,
                campaign_id=campaign_id,
                plan_fingerprint=str(plan["plan_fingerprint"]),
                proposal_ranking=effective_ranking,
                state="starting",
                director_mode=effective_mode,
                pid=pid,
            )
            next_state = "starting"
        elif resumable:
            pid = _launch_experiment_campaign(
                workspace,
                campaign_id=campaign_id,
                plan_fingerprint=None,
                time_limit=config.time_limit,
                resume=True,
            )
            _write_experiment_state(
                workspace,
                config=config_for_summary,
                campaign_id=campaign_id,
                plan_fingerprint=str(state.get("plan_fingerprint") or ""),
                proposal_ranking=effective_ranking,
                state="resuming",
                director_mode=effective_mode,
                pid=pid,
            )
            next_state = "resuming"
        else:
            raise ExperimentConfigError(
                "the latest attempt is not resumable; choose a new experiment.id"
            )
        print(
            json.dumps(
                _experiment_summary(
                    config_for_summary,
                    state=next_state,
                    proposal_ranking=effective_ranking,
                    resumed=True,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    except (ExperimentConfigError, CampaignPlanError, ValueError) as error:
        raise SystemExit(str(error)) from error


def cmd_research_campaign(args: Namespace) -> int:
    workspace = _workspace(args.workspace)
    command = args.research_campaign_command
    if command == "prepare":
        # ``prepare`` is the supported operator entry point. Upgrade only a
        # fresh generic ``sglab init`` workspace (or a new directory); the
        # campaign planner itself still enforces the marker for library and
        # recovery callers.
        _ensure_first_real_graph_workspace(workspace)
        duration = parse_duration(args.time_limit)
        report = prepare_campaign_plan(
            workspace,
            duration_seconds=duration,
            director_mode=args.director_mode,
            passive_seed=args.passive_seed,
            proposal_ranking=args.proposal_ranking,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if command == "auth-import":
        current = campaign_status(workspace, args.campaign_id)
        if current.get("state") == "prepared":
            plan = load_prepared_campaign_plan(
                workspace,
                campaign_id=args.campaign_id,
                expected_fingerprint=args.plan_fingerprint,
            )
        else:
            plan = campaign_plan(workspace, args.campaign_id)
            validate_campaign_plan_fingerprint(
                plan, expected=args.plan_fingerprint
            )
        import_authorized_auth(
            Path(args.from_codex_home),
            campaign_application_data(
                workspace,
                str(plan["campaign_id"]),
            ),
        )
        print(
            json.dumps(
                {
                    "campaign_id": plan["campaign_id"],
                    "plan_fingerprint": plan["plan_fingerprint"],
                    "imported": True,
                    "copied": ["auth.json"],
                },
                sort_keys=True,
            )
        )
        return 0
    if command == "start":
        duration = parse_duration(args.time_limit) if args.time_limit else None
        stop_mode = "until_success" if args.until_success else "time_limit"
        prepared = None
        campaign_id = None
        maximum_cycles = None
        context_mode = "stateless_turns"
        if args.plan_fingerprint:
            prepared = load_prepared_campaign_plan(
                workspace,
                expected_fingerprint=args.plan_fingerprint,
            )
            if duration != float(
                prepared["stop_contract"]["campaign_wall_seconds"]
            ):
                raise SystemExit(
                    "start duration does not match the prepared campaign"
                )
            campaign_id = str(prepared["campaign_id"])
            maximum_cycles = int(
                prepared["director"]["maximum_cycles"]
            )
            context_mode = str(
                prepared["director"]["context_mode"]
            )
        elif (workspace / PREPARED_CAMPAIGN_POINTER).exists():
            raise SystemExit(
                "prepared campaign requires its exact plan fingerprint"
            )
        report = ResearchCampaignRunner(
            workspace=workspace,
            stop_mode=stop_mode,
            duration_seconds=duration,
            campaign_id=campaign_id,
            maximum_director_turns=maximum_cycles,
            context_mode=context_mode,
            prepared_plan=prepared,
            director_mode=args.director_mode,
            passive_seed=args.passive_seed,
            proposal_ranking=args.proposal_ranking,
        ).run()
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if command == "resume":
        current = campaign_status(workspace, args.campaign_id)
        if current.get("state") in {"IDLE", "NOT_FOUND", "SCHEMA_UNAVAILABLE"}:
            raise SystemExit("research campaign not found")
        additional = parse_duration(args.additional_time)
        overrides = {
            key: value
            for key, value in {
                "cpu_workers": args.cpu_workers,
                "maximum_active_lanes": args.max_active_lanes,
                "maximum_aggregate_resource_share": (
                    args.aggregate_lane_resource_share
                ),
                "lane_memory_bytes": args.lane_memory_bytes,
                "verifier_concurrency": args.verifier_concurrency,
                "verifier_memory_bytes": args.verifier_memory_bytes,
                "verification_queue_depth": args.verification_queue_depth,
            }.items()
            if value is not None
        }
        commit = repository_commit(Path(__file__).resolve().parents[2])
        if args.preview:
            report = build_resume_preview(
                workspace,
                str(current["campaign_id"]),
                additional_wall_seconds=additional,
                resource_overrides=overrides,
                repair_acknowledgement=args.repair_acknowledgement,
                code_commit=commit,
                director_mode=args.director_mode,
            )
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0
        report = ResearchCampaignRunner(
            workspace=workspace,
            stop_mode=str(current["stop_mode"]),
            duration_seconds=additional,
            campaign_id=str(current["campaign_id"]),
            maximum_director_turns=current.get("maximum_director_turns"),
            context_mode=str(
                current.get("effective_context_mode") or "stateless_turns"
            ),
            resume_resource_overrides=overrides,
            repair_acknowledgement=args.repair_acknowledgement,
            code_commit=commit,
            director_mode=args.director_mode,
        ).run()
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    if command == "status":
        print(
            json.dumps(
                campaign_status(workspace, args.campaign_id),
                indent=2,
                sort_keys=True,
            )
        )
        return 0
    if command == "continue":
        raise SystemExit(
            "continue is replaced by research-campaign resume "
            "--additional-time <duration>"
        )
    if command in {"pause", "stop"}:
        current = campaign_status(workspace)
        if not current.get("campaign_id") or current.get("state") in {
            "succeeded_certified_counterexample",
            "completed_deadline_reached",
            "stopped_by_operator",
        }:
            raise SystemExit("no active research campaign")
        action = {"pause": "PAUSE", "stop": "STOP"}[command]
        report = request_campaign_control(workspace, action)
        print(json.dumps(report, sort_keys=True))
        return 0
    current = campaign_status(workspace, args.campaign_id)
    campaign_id = current.get("campaign_id")
    if not campaign_id:
        raise SystemExit("research campaign not found")
    campaign_dir_value = (
        current.get("process", {}).get("campaign_dir")
        or str(workspace / "research-campaigns" / str(campaign_id))
    )
    with ResearchStore(workspace / "results.sqlite3") as store:
        report = export_campaign(
            store=store,
            campaign_id=str(campaign_id),
            campaign_dir=Path(str(campaign_dir_value)),
            output=_workspace(args.output),
        )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def cmd_comparisons(args: Namespace) -> int:
    workspace = _workspace(args.workspace)
    if args.comparisons_command == "import-campaign-snapshot":
        report = import_campaign_snapshot_fixture(
            source_workspace=_workspace(args.source_workspace),
            destination_workspace=workspace,
            snapshot_reference=args.snapshot,
            display_name=args.display_name,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    workspace.mkdir(parents=True, exist_ok=True)
    database = workspace / "results.sqlite3"
    if args.comparisons_command == "worker":
        launcher_value = os.environ.get("SGLAB_COMPARISON_CODEX_LAUNCHER_JSON")
        if launcher_value:
            launcher_payload = json.loads(launcher_value)
            if (
                not isinstance(launcher_payload, list)
                or not launcher_payload
                or not all(
                    isinstance(value, str) and value
                    for value in launcher_payload
                )
            ):
                raise ValueError(
                    "SGLAB_COMPARISON_CODEX_LAUNCHER_JSON must be a string array"
                )
            launcher = tuple(launcher_payload)
        else:
            launcher = ("codex",)
        auth_value = os.environ.get("SGLAB_CODEX_AUTH_SOURCE")
        result = ComparisonWorker(
            workspace=workspace,
            suite_id=args.suite_id,
            auth_source=Path(auth_value) if auth_value else None,
            launcher=launcher,
            maximum_concurrent_suites=int(
                os.environ.get("SGLAB_COMPARISON_MAX_CONCURRENT", "1")
            ),
        ).run()
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "suite_id": result.suite_id,
                    "attempt_id": result.attempt_id,
                    "terminal_status": result.terminal_status,
                    "terminal_reason": result.terminal_reason,
                    "inference_starts": result.inference_starts,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0 if result.ok else 1
    if args.comparisons_command == "install-fixture":
        fixture_id = import_comparison_fixture_bundle(
            database, Path(args.fixture).resolve()
        )
        report = {
            "ok": True,
            "fixture_id": fixture_id,
            "auth_access": False,
            "model_inferences": 0,
        }
    elif args.comparisons_command == "import-m6-context-report":
        suite_id = import_m6_context_report(database, Path(args.report).resolve())
        report: dict[str, object] = {
            "ok": True,
            "suite_id": suite_id,
            "read_only": True,
            "runtime_executed_elsewhere": True,
        }
    else:
        report = run_replay_dry_run(database)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


def cmd_ui_fixture(args: Namespace) -> int:
    result = create_ui_fixture(
        _workspace(args.workspace),
        profile=args.profile,
        replace=bool(args.replace),
        seed=args.seed,
    )
    print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
    return 0


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(prog="sglab")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor")
    doctor.set_defaults(func=cmd_doctor)

    proposal_ranking = subparsers.add_parser("proposal-ranking")
    proposal_ranking_commands = proposal_ranking.add_subparsers(
        dest="proposal_ranking_command", required=True
    )
    proposal_ranking_doctor = proposal_ranking_commands.add_parser("doctor")
    proposal_ranking_doctor.set_defaults(func=cmd_proposal_ranking)

    init = subparsers.add_parser("init")
    init.add_argument("--workspace", required=True)
    init.add_argument(
        "--kind",
        choices=["first-real-graph-campaign"],
        help="create the explicit non-synthetic campaign workspace marker",
    )
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
    verify.add_argument("--target", choices=sorted(TARGETS), default="erdos_gyarfas")
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
    score_kernel = benchmark_commands.add_parser("score-kernel")
    score_kernel.add_argument("--iterations", type=int, default=7)
    score_kernel.add_argument("--backend-evaluations", type=int, default=100)
    score_kernel.add_argument("--search-evaluations", type=int, default=1000)
    score_kernel.add_argument("--output", required=True)
    score_kernel.set_defaults(func=cmd_benchmark)
    mutation_cache = benchmark_commands.add_parser("mutation-cache")
    mutation_cache.add_argument("--episodes", type=int, default=16)
    mutation_cache.add_argument("--evaluations", type=int, default=80_000)
    mutation_cache.add_argument("--order", type=int, default=30)
    mutation_cache.add_argument("--output", required=True)
    mutation_cache.set_defaults(func=cmd_benchmark)
    soak_parser = benchmark_commands.add_parser("soak")
    soak_parser.add_argument("--hours", type=float, default=2)
    soak_parser.add_argument("--order", type=int, default=32)
    soak_parser.add_argument("--workers", type=int, default=1)
    soak_parser.add_argument("--workspace", required=True)
    soak_parser.add_argument("--output", required=True)
    soak_parser.set_defaults(func=cmd_benchmark)
    director_controls = benchmark_commands.add_parser(
        "active-director-controls"
    )
    director_controls.add_argument("--workspace", required=True)
    director_controls.add_argument("--output", required=True)
    director_controls.add_argument("--smoke", action="store_true")
    director_controls.set_defaults(func=cmd_benchmark)
    proposal_ranking = benchmark_commands.add_parser("proposal-ranking")
    proposal_ranking.add_argument("--output", required=True)
    proposal_ranking.add_argument("--corpus")
    proposal_ranking.add_argument("--e2e-evaluations", type=int, default=100)
    proposal_ranking.set_defaults(func=cmd_benchmark)

    ai_director = subparsers.add_parser("ai-director")
    ai_director_commands = ai_director.add_subparsers(
        dest="ai_director_command", required=True
    )
    director_preflight = ai_director_commands.add_parser("preflight")
    director_preflight.add_argument("--workspace", required=True)
    director_preflight.add_argument("--codex", default="codex")
    director_preflight.add_argument("--output")
    director_preflight.set_defaults(func=cmd_ai_director)
    director_compliance = ai_director_commands.add_parser("compliance-audit")
    director_compliance.add_argument("--workspace", required=True)
    director_compliance.add_argument("--codex", default="codex")
    director_compliance.add_argument("--output")
    director_compliance.set_defaults(func=cmd_ai_director)
    director_auth = ai_director_commands.add_parser("auth-import")
    director_auth.add_argument("--workspace", required=True)
    director_auth.add_argument("--from-codex-home", required=True)
    director_auth.set_defaults(func=cmd_ai_director)
    director_inspect = ai_director_commands.add_parser("inspect-session")
    director_inspect.add_argument("--workspace", required=True)
    director_inspect.set_defaults(func=cmd_ai_director)

    ai_experiment = subparsers.add_parser("ai-experiment")
    ai_experiment_commands = ai_experiment.add_subparsers(
        dest="ai_experiment_command", required=True
    )
    experiment_phase_a = ai_experiment_commands.add_parser("phase-a")
    experiment_phase_a.add_argument("--workspace", required=True)
    experiment_phase_a.set_defaults(func=cmd_ai_experiment)
    context_screen_phase_a = ai_experiment_commands.add_parser(
        "context-screen-phase-a"
    )
    context_screen_phase_a.add_argument("--workspace", required=True)
    context_screen_phase_a.add_argument(
        "--source-workspace", required=True
    )
    context_screen_phase_a.set_defaults(func=cmd_ai_experiment)
    context_screen_run = ai_experiment_commands.add_parser(
        "context-screen-run"
    )
    context_screen_run.add_argument("--workspace", required=True)
    context_screen_run.add_argument("--source-workspace", required=True)
    context_screen_run.add_argument("--codex", default="codex")
    context_screen_run.add_argument(
        "--turn-timeout-seconds", type=float, default=300.0
    )
    context_screen_run.set_defaults(func=cmd_ai_experiment)
    experiment_run = ai_experiment_commands.add_parser("run")
    experiment_run.add_argument("--workspace", required=True)
    experiment_run.add_argument("--codex", default="codex")
    experiment_run.add_argument(
        "--evaluation-cap", type=int, required=True
    )
    experiment_run.add_argument("--resume", action="store_true")
    experiment_run.add_argument(
        "--context-mode",
        choices=[
            "persistent_thread",
            "compacted_thread",
            "stateless_turns",
        ],
        default="stateless_turns",
    )
    experiment_run.set_defaults(func=cmd_ai_experiment)

    experiment = subparsers.add_parser(
        "experiment",
        help="run a durable operator-configured research experiment",
    )
    experiment_commands = experiment.add_subparsers(
        dest="experiment_command", required=True
    )
    experiment_run = experiment_commands.add_parser("run")
    experiment_run.add_argument("--config", required=True)
    experiment_run.set_defaults(func=cmd_experiment)

    research_campaign = subparsers.add_parser("research-campaign")
    campaign_commands = research_campaign.add_subparsers(
        dest="research_campaign_command", required=True
    )
    campaign_start = campaign_commands.add_parser("start")
    campaign_stop_mode = campaign_start.add_mutually_exclusive_group(required=True)
    campaign_stop_mode.add_argument("--time-limit")
    campaign_stop_mode.add_argument("--until-success", action="store_true")
    campaign_start.add_argument("--workspace", required=True)
    campaign_start.add_argument("--plan-fingerprint")
    campaign_start.add_argument(
        "--director-mode", choices=["llm", "passive"]
    )
    campaign_start.add_argument("--passive-seed", type=int, default=0)
    campaign_start.add_argument(
        "--proposal-ranking",
        choices=["mutation_forge_stage4r_v1"],
    )
    campaign_start.set_defaults(func=cmd_research_campaign)
    campaign_prepare = campaign_commands.add_parser("prepare")
    campaign_prepare.add_argument("--workspace", required=True)
    campaign_prepare.add_argument("--time-limit", required=True)
    campaign_prepare.add_argument(
        "--director-mode",
        choices=["llm", "passive"],
        default="llm",
    )
    campaign_prepare.add_argument("--passive-seed", type=int, default=0)
    campaign_prepare.add_argument(
        "--proposal-ranking",
        choices=["mutation_forge_stage4r_v1"],
    )
    campaign_prepare.set_defaults(func=cmd_research_campaign)
    campaign_auth = campaign_commands.add_parser("auth-import")
    campaign_auth.add_argument("--workspace", required=True)
    campaign_auth.add_argument("--campaign-id", required=True)
    campaign_auth.add_argument("--plan-fingerprint", required=True)
    campaign_auth.add_argument("--from-codex-home", required=True)
    campaign_auth.set_defaults(func=cmd_research_campaign)
    campaign_status_parser = campaign_commands.add_parser("status")
    campaign_status_parser.add_argument("--workspace", required=True)
    campaign_status_parser.add_argument("--campaign-id")
    campaign_status_parser.set_defaults(func=cmd_research_campaign)
    campaign_resume = campaign_commands.add_parser("resume")
    campaign_resume.add_argument("--workspace", required=True)
    campaign_resume.add_argument("--campaign-id", required=True)
    campaign_resume.add_argument("--additional-time", required=True)
    campaign_resume.add_argument("--cpu-workers", type=int)
    campaign_resume.add_argument("--max-active-lanes", type=int)
    campaign_resume.add_argument(
        "--aggregate-lane-resource-share", type=float
    )
    campaign_resume.add_argument("--lane-memory-bytes", type=int)
    campaign_resume.add_argument("--verifier-concurrency", type=int)
    campaign_resume.add_argument("--verifier-memory-bytes", type=int)
    campaign_resume.add_argument("--verification-queue-depth", type=int)
    campaign_resume.add_argument("--repair-acknowledgement")
    campaign_resume.add_argument(
        "--director-mode", choices=["llm", "passive"]
    )
    campaign_resume.add_argument("--preview", action="store_true")
    campaign_resume.set_defaults(func=cmd_research_campaign)
    for name in ("pause", "continue", "stop"):
        campaign_control = campaign_commands.add_parser(name)
        campaign_control.add_argument("--workspace", required=True)
        campaign_control.set_defaults(func=cmd_research_campaign)
    campaign_export = campaign_commands.add_parser("export")
    campaign_export.add_argument("--workspace", required=True)
    campaign_export.add_argument("--campaign-id")
    campaign_export.add_argument("--output", required=True)
    campaign_export.set_defaults(func=cmd_research_campaign)

    comparisons = subparsers.add_parser("comparisons")
    comparison_commands = comparisons.add_subparsers(
        dest="comparisons_command", required=True
    )
    comparison_import = comparison_commands.add_parser(
        "import-m6-context-report"
    )
    comparison_import.add_argument("--workspace", default="workspace")
    comparison_import.add_argument("--report", required=True)
    comparison_import.set_defaults(func=cmd_comparisons)
    comparison_replay = comparison_commands.add_parser("replay-dry-run")
    comparison_replay.add_argument("--workspace", required=True)
    comparison_replay.set_defaults(func=cmd_comparisons)
    comparison_fixture = comparison_commands.add_parser("install-fixture")
    comparison_fixture.add_argument("--workspace", required=True)
    comparison_fixture.add_argument("--fixture", required=True)
    comparison_fixture.set_defaults(func=cmd_comparisons)
    comparison_snapshot = comparison_commands.add_parser(
        "import-campaign-snapshot"
    )
    comparison_snapshot.add_argument(
        "--source-workspace",
        required=True,
    )
    comparison_snapshot.add_argument(
        "--workspace",
        dest="workspace",
        required=True,
        help="dedicated destination comparison workspace",
    )
    comparison_snapshot.add_argument("--snapshot", required=True)
    comparison_snapshot.add_argument("--display-name", required=True)
    comparison_snapshot.set_defaults(func=cmd_comparisons)
    comparison_worker = comparison_commands.add_parser("worker")
    comparison_worker.add_argument("--workspace", required=True)
    comparison_worker.add_argument("--suite-id", required=True)
    comparison_worker.set_defaults(func=cmd_comparisons)

    ui_fixture = subparsers.add_parser("ui-fixture")
    ui_fixture_commands = ui_fixture.add_subparsers(
        dest="ui_fixture_command", required=True
    )
    ui_fixture_create = ui_fixture_commands.add_parser("create")
    ui_fixture_create.add_argument("--workspace", required=True)
    ui_fixture_create.add_argument("--profile", choices=("full",), default="full")
    ui_fixture_create.add_argument("--seed", type=int, default=20260725)
    ui_fixture_create.add_argument("--replace", action="store_true")
    ui_fixture_create.set_defaults(func=cmd_ui_fixture)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))
