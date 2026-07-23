from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from multiprocessing import Event, Queue, get_context
from pathlib import Path
from queue import Empty, Full
from random import Random
from typing import Any
import ast
import hashlib
import json
import math
import os
import platform
import time

from .artifacts import write_candidate
from .certification import certify
from .db import checkpoint as database_checkpoint
from .db import connect, insert_metrics, insert_run, set_run_status
from .model import BitGraph
from .resources import current_rss_bytes, disk_free_bytes, recommended_workers
from .resources import run_bounded, set_address_space_limit
from .state import append_event, atomic_write_json, read_json, utc_now
from .targets import TARGETS
from .targets.base import ScoreResult

ALGORITHMS = {"simulated_annealing", "iterated_local_search"}
MODES = {"cubic_first", "minimal_structure_mixed_degree", "unrestricted_min_degree_3"}
TERMINAL_STATUSES = {
    "NO_RESULT_WITHIN_BUDGET",
    "UNKNOWN_MEMORY_LIMIT",
    "TOOL_FAILURE",
    "COUNTEREXAMPLE_VERIFIED",
}


def _write_checkpoint(path: Path, data: dict[str, Any]) -> None:
    atomic_write_json(path, data)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    atomic_write_json(path.with_suffix(".sha256.json"), {"sha256": digest})


def _read_checkpoint(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    manifest = read_json(path.with_suffix(".sha256.json"), default={})
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if manifest.get("sha256") != actual:
        raise ValueError(f"checkpoint hash mismatch: {path}")
    return read_json(path)


@dataclass(frozen=True, slots=True)
class SearchConfig:
    workspace: Path
    order: int = 32
    mode: str = "cubic_first"
    algorithm: str = "simulated_annealing"
    workers: int = 1
    seed: int = 1
    wall_seconds: float = 60.0
    max_candidates: int = 0
    witness_cap: int = 64
    queue_capacity: int = 256
    archive_top_k: int = 50
    state_seconds: float = 1.0
    checkpoint_seconds: float = 5.0
    worker_recycle_candidates: int = 500_000
    memory_limit_bytes: int = 0
    min_free_disk_bytes: int = 64 * 1024 * 1024
    notes: str = ""
    exact_timeout_seconds: float = 30.0

    def validate(self) -> None:
        if self.order < 4 or self.order > 128:
            raise ValueError("order must be between 4 and 128")
        if self.mode not in MODES:
            raise ValueError(f"unsupported mode: {self.mode}")
        if self.algorithm not in ALGORITHMS:
            raise ValueError(f"unsupported algorithm: {self.algorithm}")
        if self.mode == "cubic_first" and self.order % 2:
            raise ValueError("cubic_first requires an even order")
        if not 1 <= self.workers <= 256:
            raise ValueError("workers must be between 1 and 256")
        if self.wall_seconds <= 0:
            raise ValueError("wall_seconds must be positive")
        if self.queue_capacity < 4 or self.archive_top_k < 1:
            raise ValueError("queue_capacity and archive_top_k are too small")
        if self.exact_timeout_seconds < 0:
            raise ValueError("exact_timeout_seconds cannot be negative")


def _score_payload(score: ScoreResult) -> dict[str, Any]:
    return {
        "valid": score.valid,
        "witness_counts": {str(length): count for length, count in score.witness_counts},
        "weighted_penalty": score.weighted_penalty,
        "complete": score.complete,
        "novelty": score.novelty,
        "simplicity": score.simplicity,
        "ordering_key": list(score.ordering_key),
    }


def _scalar(score: ScoreResult) -> float:
    invalid, total, weighted, novelty, simplicity = score.ordering_key
    return (
        invalid * 1_000_000_000
        + total * 1000
        + weighted
        + novelty / 10_000_000
        + simplicity / 1_000_000
    )


def _novelty(graph: BitGraph, elite: BitGraph) -> float:
    differing = sum(
        (left ^ right).bit_count() for left, right in zip(graph.rows, elite.rows)
    ) // 2
    possible = max(1, graph.n * (graph.n - 1) // 2)
    return differing / possible


def _put(queue: Queue, message: dict[str, Any], important: bool = False) -> None:
    try:
        queue.put(message, timeout=0.05 if important else 0)
    except Full:
        return


def _worker(
    worker_id: int,
    config: SearchConfig,
    queue: Queue,
    stop: Event,
    pause: Event,
    resume_checkpoint: dict[str, Any] | None = None,
) -> None:
    set_address_space_limit(config.memory_limit_bytes or None)
    plugin = TARGETS["erdos_gyarfas"]
    rng = Random(config.seed + worker_id * 1_000_003)
    if resume_checkpoint:
        graph = BitGraph.from_graph6(str(resume_checkpoint["graph6"]))
        rng.setstate(ast.literal_eval(str(resume_checkpoint["rng_state"])))
    else:
        graph = plugin.generate_seed(
            rng, {"order": config.order, "mode": config.mode}
        )
    score = replace(
        plugin.cheap_score(graph, config.witness_cap),
        novelty=1.0,
    )
    best_graph, best_score = graph, score
    evaluated = accepted = improvements = legal = 0
    stagnation = 0
    tabu: list[str] = [graph.stable_hash()]
    last_report = time.monotonic()
    _put(
        queue,
        {
            "kind": "checkpoint",
            "worker": worker_id,
            "graph6": graph.to_graph6(),
            "score": _score_payload(score),
            "rng_state": repr(rng.getstate()),
            "evaluated": evaluated,
        },
        important=True,
    )
    _put(
        queue,
        {
            "kind": "improvement",
            "worker": worker_id,
            "graph6": graph.to_graph6(),
            "score": _score_payload(score),
        },
        important=True,
    )

    while not stop.is_set() and evaluated < config.worker_recycle_candidates:
        if pause.is_set():
            time.sleep(0.05)
            continue
        candidate = plugin.mutate(graph, rng, {"mode": config.mode})
        evaluated += 1
        if candidate == graph:
            continue
        legal += 1
        candidate_score = replace(
            plugin.cheap_score(candidate, config.witness_cap),
            novelty=_novelty(candidate, best_graph),
        )
        accept = False
        if config.algorithm == "simulated_annealing":
            temperature = max(0.05, 8.0 * (0.9995 ** (evaluated % 20_000)))
            if stagnation > 2_000:
                temperature = 8.0
                stagnation = 0
            delta = _scalar(candidate_score) - _scalar(score)
            accept = delta <= 0 or rng.random() < math.exp(-min(delta, 700) / temperature)
        else:
            key = candidate.stable_hash()
            if key not in tabu and candidate_score.ordering_key <= score.ordering_key:
                accept = True
            elif evaluated % 64 == 0:
                accept = True
            if accept:
                tabu.append(key)
                if len(tabu) > 128:
                    del tabu[0]
        if accept:
            graph, score = candidate, candidate_score
            accepted += 1
        if candidate_score.ordering_key < best_score.ordering_key:
            best_graph, best_score = candidate, candidate_score
            improvements += 1
            stagnation = 0
            _put(
                queue,
                {
                    "kind": "improvement",
                    "worker": worker_id,
                    "graph6": candidate.to_graph6(),
                    "score": _score_payload(candidate_score),
                },
                important=True,
            )
        else:
            stagnation += 1
        now = time.monotonic()
        if now - last_report >= 0.5:
            _put(
                queue,
                {
                    "kind": "metrics",
                    "worker": worker_id,
                    "evaluated": evaluated,
                    "accepted": accepted,
                    "legal": legal,
                    "improvements": improvements,
                    "rss_bytes": current_rss_bytes(),
                },
            )
            _put(
                queue,
                {
                    "kind": "checkpoint",
                    "worker": worker_id,
                    "graph6": graph.to_graph6(),
                    "score": _score_payload(score),
                    "rng_state": repr(rng.getstate()),
                    "evaluated": evaluated,
                },
            )
            last_report = now
    _put(
        queue,
        {
            "kind": "checkpoint",
            "worker": worker_id,
            "graph6": graph.to_graph6(),
            "score": _score_payload(score),
            "rng_state": repr(rng.getstate()),
            "evaluated": evaluated,
        },
        important=True,
    )
    _put(
        queue,
        {
            "kind": "exit",
            "worker": worker_id,
            "reason": "stopped" if stop.is_set() else "recycle",
            "evaluated": evaluated,
            "accepted": accepted,
            "legal": legal,
            "improvements": improvements,
        },
        important=True,
    )


def _environment() -> dict[str, Any]:
    repository = Path(__file__).resolve().parents[2]
    git = run_bounded(
        ["git", "rev-parse", "HEAD"],
        timeout_seconds=5,
        output_limit_bytes=1024,
        cwd=repository,
    )
    cyclecheck = repository / "_build" / "sglab-cyclecheck"
    cycle_version = (
        run_bounded(
            [str(cyclecheck), "--version"],
            timeout_seconds=5,
            output_limit_bytes=4096,
        )
        if cyclecheck.is_file()
        else None
    )
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "pid": os.getpid(),
        "git_commit": git.stdout.decode("ascii", errors="replace").strip() or None,
        "cyclecheck_version": (
            cycle_version.stdout.decode("utf-8", errors="replace").strip()
            if cycle_version is not None
            else None
        ),
        "cgroup_v2": Path("/sys/fs/cgroup/cgroup.controllers").exists(),
    }


def _run_id(config: SearchConfig) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    algorithm = "sa" if config.algorithm == "simulated_annealing" else "ils"
    return f"{stamp}-eg-n{config.order}-{algorithm}-s{config.seed}"


def run_search(config: SearchConfig, resume_run: Path | None = None) -> Path:
    config.validate()
    workspace = config.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "runs").mkdir(exist_ok=True)
    if resume_run is None:
        run_id = _run_id(config)
        run_dir = workspace / "runs" / run_id
        suffix = 1
        while run_dir.exists():
            run_dir = workspace / "runs" / f"{run_id}-{suffix}"
            suffix += 1
        run_id = run_dir.name
        for name in ("best", "checkpoints", "certificates", "benchmarks", "logs"):
            (run_dir / name).mkdir(parents=True, exist_ok=True)
        parameters = {**asdict(config), "workspace": str(workspace)}
        environment = _environment()
        run_record = {
            "run_id": run_id,
            "created_at": utc_now(),
            "target": "erdos_gyarfas",
            "status_checked_at": "2026-07-23",
            "parameters": parameters,
            "environment": environment,
            "git_commit": environment["git_commit"],
            "tool_versions": {"cyclecheck": environment["cyclecheck_version"]},
            "status": "RUNNING",
        }
        atomic_write_json(run_dir / "run.json", run_record)
    else:
        run_dir = resume_run.resolve()
        if run_dir.parent.parent != workspace or not (run_dir / "run.json").is_file():
            raise ValueError("resume directory must be a run inside the configured workspace")
        run_record = read_json(run_dir / "run.json")
        run_id = str(run_record["run_id"])
        parameters = dict(run_record["parameters"])
    atomic_write_json(workspace / "current_run.json", {"run_id": run_id, "run_dir": str(run_dir)})
    database = connect(run_dir / "results.sqlite3")
    if resume_run is None:
        insert_run(
            database,
            run_id,
            run_record["created_at"],
            "erdos_gyarfas",
            parameters,
            run_record["environment"],
        )
        append_event(run_dir / "events.jsonl", "run_started", run_id=run_id)
    else:
        set_run_status(database, run_id, "RUNNING")
        append_event(run_dir / "events.jsonl", "run_resumed", run_id=run_id)

    context = get_context("spawn")
    queue = context.Queue(maxsize=config.queue_capacity)
    stop = context.Event()
    pause = context.Event()
    worker_count = recommended_workers(config.workers)
    resume_checkpoints = {
        worker_id: _read_checkpoint(
            run_dir / "checkpoints" / f"worker-{worker_id}.json"
        )
        for worker_id in range(worker_count)
    }
    processes = [
        context.Process(
            target=_worker,
            args=(
                worker_id,
                config,
                queue,
                stop,
                pause,
                resume_checkpoints[worker_id],
            ),
            name=f"sglab-search-{worker_id}",
        )
        for worker_id in range(worker_count)
    ]
    for process in processes:
        process.start()

    started = time.monotonic()
    last_state = last_checkpoint = started
    worker_metrics: dict[int, dict[str, Any]] = {}
    worker_cumulative = {
        worker_id: {
            "evaluated": 0,
            "accepted": 0,
            "legal": 0,
            "improvements": 0,
        }
        for worker_id in range(worker_count)
    }
    worker_checkpoints: dict[int, dict[str, Any]] = {}
    archive: dict[str, tuple[tuple[int, ...], dict[str, Any]]] = {}
    for candidate_path in (run_dir / "best").glob("*.json"):
        record = read_json(candidate_path, default={})
        if "graph6" not in record:
            continue
        graph = BitGraph.from_graph6(str(record["graph6"]))
        key = TARGETS["erdos_gyarfas"].canonical_key(graph).decode("ascii")
        ordering = tuple(int(value) for value in record["score"]["ordering_key"])
        archive[key] = (ordering, record)
    last_control_version = int(
        read_json(workspace / "control.json", default={"version": 0}).get("version", 0)
    )
    worker_restarts = [0] * worker_count
    worker_failure_restarts = [0] * worker_count
    exited_workers: set[int] = set()
    worker_exit_reasons: dict[int, str] = {}
    stopped_by_user = False
    disk_exhausted = False
    memory_exhausted = False

    try:
        while True:
            now = time.monotonic()
            elapsed = now - started
            try:
                message = queue.get(timeout=0.1)
            except Empty:
                message = None
            if message:
                worker_id = int(message["worker"])
                if message["kind"] == "metrics":
                    worker_metrics[worker_id] = message
                elif message["kind"] == "checkpoint":
                    worker_checkpoints[worker_id] = message
                elif message["kind"] == "improvement":
                    graph = BitGraph.from_graph6(message["graph6"])
                    key = TARGETS["erdos_gyarfas"].canonical_key(graph).decode("ascii")
                    order_key = tuple(int(value) for value in message["score"]["ordering_key"])
                    if key not in archive:
                        if len(archive) >= config.archive_top_k:
                            worst_key = max(archive, key=lambda item: archive[item][0])
                            if order_key >= archive[worst_key][0]:
                                continue
                            worst_record = archive.pop(worst_key)[1]
                            for filename in worst_record.get("artifacts", {}).values():
                                path = run_dir / "best" / str(filename)
                                if path.is_file():
                                    path.unlink()
                        candidate_id, record = write_candidate(
                            run_dir, graph, message["score"], run_id
                        )
                        archive[key] = (order_key, record)
                        database.execute(
                            "INSERT OR IGNORE INTO candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (
                                candidate_id,
                                run_id,
                                graph.to_graph6(),
                                graph.n,
                                graph.size(),
                                json.dumps(message["score"], sort_keys=True),
                                "PENDING",
                                utc_now(),
                            ),
                        )
                        database.commit()
                        append_event(
                            run_dir / "events.jsonl",
                            "improvement_archived",
                            worker=worker_id,
                            candidate_id=candidate_id,
                            score=order_key,
                        )
                elif message["kind"] == "exit":
                    for field in ("evaluated", "accepted", "legal", "improvements"):
                        worker_cumulative[worker_id][field] += int(message.get(field, 0))
                    worker_metrics.pop(worker_id, None)
                    exited_workers.add(worker_id)
                    worker_exit_reasons[worker_id] = str(message["reason"])

            control = read_json(workspace / "control.json", default={"version": 0})
            version = int(control.get("version", 0))
            if version > last_control_version:
                action = control.get("action")
                last_control_version = version
                if action == "PAUSE":
                    pause.set()
                elif action == "RESUME":
                    pause.clear()
                elif action == "STOP":
                    stopped_by_user = True
                    stop.set()
                append_event(run_dir / "events.jsonl", "control_processed", action=action)

            total = sum(
                values["evaluated"] for values in worker_cumulative.values()
            ) + sum(int(item.get("evaluated", 0)) for item in worker_metrics.values())
            worker_rss = sum(
                int(item.get("rss_bytes", 0)) for item in worker_metrics.values()
            )
            if config.max_candidates and total >= config.max_candidates:
                stop.set()
            if elapsed >= config.wall_seconds:
                stop.set()
            if disk_free_bytes(run_dir) < config.min_free_disk_bytes:
                disk_exhausted = True
                stop.set()
            if config.memory_limit_bytes and worker_rss >= config.memory_limit_bytes:
                memory_exhausted = True
                stop.set()
            for worker_id, process in enumerate(processes):
                if (
                    not stop.is_set()
                    and not process.is_alive()
                    and process.exitcode is not None
                ):
                    reason = worker_exit_reasons.get(worker_id)
                    if process.exitcode == 0 and reason is None:
                        # The process can exit just before its final queue message
                        # is drained. Do not misclassify normal recycling as a crash.
                        if message is not None:
                            continue
                        reason = "recycle"
                    if worker_id in worker_metrics:
                        last_metrics = worker_metrics.pop(worker_id)
                        for field in ("evaluated", "accepted", "legal", "improvements"):
                            worker_cumulative[worker_id][field] += int(
                                last_metrics.get(field, 0)
                            )
                    if reason != "recycle":
                        worker_failure_restarts[worker_id] += 1
                    if worker_failure_restarts[worker_id] > 3:
                        stop.set()
                        continue
                    replacement = context.Process(
                        target=_worker,
                        args=(
                            worker_id,
                            config,
                            queue,
                            stop,
                            pause,
                            worker_checkpoints.get(worker_id),
                        ),
                        name=f"sglab-search-{worker_id}-r{worker_restarts[worker_id] + 1}",
                    )
                    replacement.start()
                    processes[worker_id] = replacement
                    worker_restarts[worker_id] += 1
                    exited_workers.discard(worker_id)
                    worker_exit_reasons.pop(worker_id, None)
                    append_event(
                        run_dir / "events.jsonl",
                        "worker_restarted",
                        worker=worker_id,
                        prior_exitcode=process.exitcode,
                    )
            if all(not process.is_alive() for process in processes):
                if len(exited_workers) == worker_count or any(
                    process.exitcode not in (0, None) for process in processes
                ):
                    break

            if now - last_checkpoint >= config.checkpoint_seconds:
                for worker_id, checkpoint_data in worker_checkpoints.items():
                    _write_checkpoint(
                        run_dir / "checkpoints" / f"worker-{worker_id}.json",
                        checkpoint_data,
                    )
                database_checkpoint(database)
                last_checkpoint = now

            if now - last_state >= config.state_seconds:
                total_accepted = sum(
                    values["accepted"] for values in worker_cumulative.values()
                ) + sum(int(item.get("accepted", 0)) for item in worker_metrics.values())
                total_improvements = sum(
                    values["improvements"] for values in worker_cumulative.values()
                ) + sum(
                    int(item.get("improvements", 0)) for item in worker_metrics.values()
                )
                best_record = (
                    min(archive.values(), key=lambda item: item[0])[1] if archive else None
                )
                status = "PAUSED" if pause.is_set() else "STOPPING" if stop.is_set() else "RUNNING"
                state = {
                    "updated_at": utc_now(),
                    "run_id": run_id,
                    "run_dir": str(run_dir),
                    "target": "erdos_gyarfas",
                    "status": status,
                    "elapsed_seconds": elapsed,
                    "workers": {
                        "configured": worker_count,
                        "alive": sum(process.is_alive() for process in processes),
                        "restarts": sum(worker_restarts),
                        "failed": sum(worker_failure_restarts),
                    },
                    "throughput": {
                        "candidates": total,
                        "accepted": total_accepted,
                        "candidates_per_second": total / max(elapsed, 0.001),
                    },
                    "best": best_record,
                    "resources": {
                        "master_rss_bytes": current_rss_bytes(),
                        "worker_rss_bytes": sum(
                            int(item.get("rss_bytes", 0)) for item in worker_metrics.values()
                        ),
                        "load_average": list(os.getloadavg()),
                        "disk_free_bytes": disk_free_bytes(run_dir),
                        "database_bytes": (run_dir / "results.sqlite3").stat().st_size,
                    },
                    "queues": {"telemetry_max": config.queue_capacity},
                }
                atomic_write_json(run_dir / "state.json", state)
                atomic_write_json(workspace / "state.json", state)
                insert_metrics(
                    database,
                    [
                        (
                            run_id,
                            utc_now(),
                            total,
                            total_improvements,
                            total / max(elapsed, 0.001),
                            current_rss_bytes(),
                        )
                    ],
                )
                last_state = now
    finally:
        stop.set()
        pause.clear()
        for process in processes:
            process.join(timeout=2)
        for process in processes:
            if process.is_alive():
                process.kill()
                process.join(timeout=1)

    for worker_id, checkpoint_data in worker_checkpoints.items():
        _write_checkpoint(
            run_dir / "checkpoints" / f"worker-{worker_id}.json",
            checkpoint_data,
        )

    final_status = (
        "UNKNOWN_MEMORY_LIMIT"
        if memory_exhausted
        or any(process.exitcode not in (0, None, -15, -9) for process in processes)
        else "TOOL_FAILURE"
        if disk_exhausted
        else "NO_RESULT_WITHIN_BUDGET"
    )
    verified_best_record: dict[str, Any] | None = None
    if archive:
        best_record = min(archive.values(), key=lambda item: item[0])[1]
        best_graph = BitGraph.from_graph6(str(best_record["graph6"]))
        verification = certify(
            best_graph,
            run_dir / "certificates" / str(best_record["candidate_id"]),
            timeout_seconds=config.exact_timeout_seconds,
        )
        best_record["verification_status"] = verification["status"]
        atomic_write_json(
            run_dir / "best" / f"{best_record['candidate_id']}.json",
            best_record,
        )
        database.execute(
            "UPDATE candidates SET verification_status=? WHERE candidate_id=?",
            (verification["status"], best_record["candidate_id"]),
        )
        for verifier in verification["verifiers"]:
            database.execute(
                """
                INSERT INTO verifications
                (candidate_id, verifier, status, complete, elapsed_seconds, report_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    best_record["candidate_id"],
                    verifier.get("implementation", "unknown"),
                    verifier["status"],
                    int(bool(verifier.get("complete"))),
                    float(verifier.get("elapsed_seconds", 0)),
                    json.dumps(verifier, sort_keys=True),
                ),
            )
        database.commit()
        append_event(
            run_dir / "events.jsonl",
            "finalist_verified",
            candidate_id=best_record["candidate_id"],
            status=verification["status"],
        )
        if verification["status"] == "COUNTEREXAMPLE_VERIFIED":
            final_status = "COUNTEREXAMPLE_VERIFIED"
        verified_best_record = best_record
    total = sum(
        values["evaluated"] for values in worker_cumulative.values()
    ) + sum(int(item.get("evaluated", 0)) for item in worker_metrics.values())
    final_state = {
        **read_json(run_dir / "state.json", default={}),
        "updated_at": utc_now(),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "status": final_status,
        "stop_requested": stopped_by_user,
        "workers": {
            "configured": worker_count,
            "alive": 0,
            "restarts": sum(worker_restarts),
            "failed": sum(worker_failure_restarts),
        },
        "throughput": {
            "candidates": total,
            "candidates_per_second": total / max(time.monotonic() - started, 0.001),
        },
    }
    if verified_best_record is not None:
        final_state["best"] = verified_best_record
    atomic_write_json(run_dir / "state.json", final_state)
    atomic_write_json(workspace / "state.json", final_state)
    set_run_status(database, run_id, final_status)
    database_checkpoint(database)
    database.close()
    append_event(run_dir / "events.jsonl", "run_finished", status=final_status)
    return run_dir


def config_from_run(run_dir: Path, wall_seconds: float | None = None) -> SearchConfig:
    record = read_json(run_dir / "run.json")
    values = dict(record["parameters"])
    values["workspace"] = Path(values["workspace"])
    if wall_seconds is not None:
        values["wall_seconds"] = wall_seconds
    allowed = SearchConfig.__dataclass_fields__
    return SearchConfig(**{key: value for key, value in values.items() if key in allowed})
