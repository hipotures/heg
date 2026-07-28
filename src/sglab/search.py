from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from multiprocessing import Event, Queue, get_context
from pathlib import Path
from queue import Empty, Full
from random import Random
from typing import Any
import ast
import fcntl
import hashlib
import json
import math
import os
import platform
import time

from . import __version__
from .artifacts import hash_file, write_candidate
from .certification import certify
from .db import checkpoint as database_checkpoint
from .db import connect, insert_metrics, insert_run, prune_metrics, set_run_status
from .external import TOOLS
from .locations import cyclecheck_path, source_root
from .model import BitGraph
from .resources import current_rss_bytes, disk_free_bytes, recommended_workers
from .resources import run_bounded, set_address_space_limit
from .resources import sqlite_size_bytes
from .score_worker import (
    DEFAULT_WORKER_MEMORY_BYTES,
    PersistentScoreWorker,
    ScoreWorkerError,
)
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
    target: str = "erdos_gyarfas"
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
    memory_high_bytes: int = 0
    memory_limit_bytes: int = 0
    min_free_disk_bytes: int = 64 * 1024 * 1024
    max_log_bytes: int = 16 * 1024 * 1024
    notes: str = ""
    exact_timeout_seconds: float = 30.0

    def validate(self) -> None:
        if self.target not in TARGETS:
            raise ValueError(f"unsupported target: {self.target}")
        if self.order < 4 or self.order > 128:
            raise ValueError("order must be between 4 and 128")
        if self.mode not in MODES:
            raise ValueError(f"unsupported mode: {self.mode}")
        if self.algorithm not in ALGORITHMS:
            raise ValueError(f"unsupported algorithm: {self.algorithm}")
        if self.mode == "cubic_first" and self.order % 2:
            raise ValueError("cubic_first requires an even order")
        if self.mode == "minimal_structure_mixed_degree" and self.order < 5:
            raise ValueError("minimal_structure_mixed_degree requires order at least 5")
        if not 1 <= self.workers <= 256:
            raise ValueError("workers must be between 1 and 256")
        if not math.isfinite(self.wall_seconds) or not (
            0 < self.wall_seconds <= 365 * 86400
        ):
            raise ValueError("wall_seconds must be between 0 and 31536000")
        if self.max_candidates < 0:
            raise ValueError("max_candidates cannot be negative")
        if not 1 <= self.witness_cap <= 10_000:
            raise ValueError("witness_cap must be between 1 and 10000")
        if not 4 <= self.queue_capacity <= 65_536:
            raise ValueError("queue_capacity must be between 4 and 65536")
        if not 1 <= self.archive_top_k <= 10_000:
            raise ValueError("archive_top_k must be between 1 and 10000")
        if (
            not math.isfinite(self.state_seconds)
            or not math.isfinite(self.checkpoint_seconds)
            or self.state_seconds <= 0
            or self.checkpoint_seconds <= 0
        ):
            raise ValueError(
                "state and checkpoint intervals must be finite and positive"
            )
        if not 1 <= self.worker_recycle_candidates <= 1_000_000_000:
            raise ValueError(
                "worker_recycle_candidates must be between 1 and 1000000000"
            )
        if not 0 <= self.memory_high_bytes <= 2**63 - 1 or not (
            0 <= self.memory_limit_bytes <= 2**63 - 1
        ):
            raise ValueError("memory limits must fit a nonnegative signed 64-bit value")
        if not 0 <= self.min_free_disk_bytes <= 2**63 - 1:
            raise ValueError(
                "min_free_disk_bytes must fit a nonnegative signed 64-bit value"
            )
        if not 1024 <= self.max_log_bytes <= 1024 * 1024 * 1024:
            raise ValueError("max_log_bytes must be between 1 KiB and 1 GiB")
        if len(self.notes) > 500:
            raise ValueError("notes exceed 500 characters")
        if not math.isfinite(self.exact_timeout_seconds) or not (
            0 <= self.exact_timeout_seconds <= 7 * 86400
        ):
            raise ValueError("exact_timeout_seconds must be between 0 and 604800")
        if (
            self.memory_high_bytes
            and self.memory_limit_bytes
            and self.memory_high_bytes > self.memory_limit_bytes
        ):
            raise ValueError("memory_high_bytes cannot exceed memory_limit_bytes")


def _score_payload(score: ScoreResult) -> dict[str, Any]:
    return {
        "valid": score.valid,
        "witness_counts": {
            str(length): count for length, count in score.witness_counts
        },
        "weighted_penalty": score.weighted_penalty,
        "complete": score.complete,
        "novelty": score.novelty,
        "simplicity": score.simplicity,
        "ordering_key": list(score.ordering_key),
    }


def _score_from_payload(payload: dict[str, Any]) -> ScoreResult:
    return ScoreResult(
        valid=bool(payload["valid"]),
        witness_counts=tuple(
            sorted(
                (
                    (int(length), int(count))
                    for length, count in payload["witness_counts"].items()
                ),
                key=lambda item: item[0],
            )
        ),
        weighted_penalty=int(payload["weighted_penalty"]),
        complete=bool(payload["complete"]),
        novelty=float(payload.get("novelty", 0)),
        simplicity=int(payload.get("simplicity", 0)),
    )


def _scalar(score: ScoreResult) -> float:
    invalid, total, weighted, novelty, simplicity = score.ordering_key
    return (
        invalid * 2_000_000
        + total
        + weighted / 2_000_000
        + novelty / 4_000_000_000_000
        + simplicity / 80_000_000_000_000_000
    )


def _novelty(graph: BitGraph, elite: BitGraph) -> float:
    differing = (
        sum((left ^ right).bit_count() for left, right in zip(graph.rows, elite.rows))
        // 2
    )
    possible = max(1, graph.n * (graph.n - 1) // 2)
    return differing / possible


def _put(queue: Queue, message: dict[str, Any], important: bool = False) -> None:
    try:
        queue.put(message, timeout=0.05 if important else 0)
    except Full:
        return


def _worker_candidate_budget(config: SearchConfig, worker_id: int) -> int | None:
    if config.max_candidates <= 0:
        return None
    worker_count = recommended_workers(config.workers)
    base, remainder = divmod(config.max_candidates, worker_count)
    return base + int(worker_id < remainder)


def _queue_size(queue: Queue) -> int | None:
    try:
        return queue.qsize()
    except (NotImplementedError, OSError):
        return None


def _checkpoint_candidate_id(checkpoint: dict[str, Any]) -> str | None:
    graph6 = checkpoint.get("graph6")
    if not isinstance(graph6, str):
        return None
    return hashlib.sha256(graph6.encode("ascii")).hexdigest()[:20]


def _verification_completed(record: dict[str, Any]) -> bool:
    return record.get("verification_status") in {
        "COUNTEREXAMPLE_VERIFIED",
        "INVALID_CANDIDATE",
    }


def _worker(
    worker_id: int,
    config: SearchConfig,
    queue: Queue,
    stop: Event,
    pause: Event,
    resume_checkpoint: dict[str, Any] | None = None,
    *,
    score_worker: PersistentScoreWorker,
) -> None:
    plugin = TARGETS[config.target]
    rng = Random(config.seed + worker_id * 1_000_003)

    def score_graph(candidate: BitGraph) -> ScoreResult:
        node_budget = max(
            4_096, min(50_000, config.witness_cap * 1_024)
        )
        last_error: BaseException | None = None
        for attempt in range(2):
            try:
                response = score_worker.score(
                    candidate,
                    lengths=plugin.forbidden_lengths(candidate.n),
                    limit=config.witness_cap + 1,
                    node_budget=node_budget,
                )
                return plugin.score_from_cycle_counts(
                    candidate,
                    config.witness_cap,
                    response.results,
                    None,
                )
            except (OSError, ScoreWorkerError, ValueError) as error:
                last_error = error
                if attempt == 0:
                    try:
                        score_worker.restart()
                    except ScoreWorkerError as restart_error:
                        last_error = restart_error
                        break
        raise ScoreWorkerError(
            "mandatory C++ score worker failed after one restart"
        ) from last_error

    if resume_checkpoint:
        graph = BitGraph.from_graph6(str(resume_checkpoint["graph6"]))
        rng.setstate(ast.literal_eval(str(resume_checkpoint["rng_state"])))
        score = _score_from_payload(resume_checkpoint["score"])
        best_graph = BitGraph.from_graph6(
            str(resume_checkpoint.get("best_graph6", graph.to_graph6()))
        )
        best_score = _score_from_payload(
            resume_checkpoint.get("best_score", resume_checkpoint["score"])
        )
        stagnation = int(resume_checkpoint.get("stagnation", 0))
        tabu = [
            str(value) for value in resume_checkpoint.get("tabu", [graph.stable_hash()])
        ][-128:]
        algorithm_evaluated = int(resume_checkpoint.get("algorithm_evaluated", 0))
        next_restart = int(resume_checkpoint.get("next_restart", 50_000))
    else:
        graph = plugin.generate_seed(rng, {"order": config.order, "mode": config.mode})
        score = replace(
            score_graph(graph),
            novelty=1.0,
        )
        best_graph, best_score = graph, score
        stagnation = 0
        tabu = [graph.stable_hash()]
        algorithm_evaluated = 0
        next_restart = 50_000
    evaluated = accepted = improvements = legal = 0
    lifetime_evaluated = (
        int(resume_checkpoint.get("lifetime_evaluated", 0)) if resume_checkpoint else 0
    )
    candidate_budget = _worker_candidate_budget(config, worker_id)
    last_report = time.monotonic()

    def checkpoint_payload() -> dict[str, Any]:
        return {
            "kind": "checkpoint",
            "worker": worker_id,
            "graph6": graph.to_graph6(),
            "score": _score_payload(score),
            "best_graph6": best_graph.to_graph6(),
            "best_score": _score_payload(best_score),
            "rng_state": repr(rng.getstate()),
            "evaluated": evaluated,
            "lifetime_evaluated": lifetime_evaluated + evaluated,
            "algorithm_evaluated": algorithm_evaluated,
            "stagnation": stagnation,
            "tabu": tabu,
            "next_restart": next_restart,
        }

    _put(
        queue,
        checkpoint_payload(),
        important=True,
    )
    _put(
        queue,
        {
            "kind": "improvement",
            "worker": worker_id,
            "graph6": best_graph.to_graph6(),
            "score": _score_payload(best_score),
        },
        important=True,
    )

    while (
        not stop.is_set()
        and evaluated < config.worker_recycle_candidates
        and (
            candidate_budget is None
            or lifetime_evaluated + evaluated < candidate_budget
        )
    ):
        if pause.is_set():
            time.sleep(0.05)
            continue
        if (
            config.algorithm == "simulated_annealing"
            and algorithm_evaluated >= next_restart
        ):
            graph = plugin.generate_seed(
                rng, {"order": config.order, "mode": config.mode}
            )
            score = replace(
                score_graph(graph),
                novelty=_novelty(graph, best_graph),
            )
            tabu = [graph.stable_hash()]
            stagnation = 0
            next_restart += 50_000
        candidate = plugin.mutate(graph, rng, {"mode": config.mode})
        evaluated += 1
        algorithm_evaluated += 1
        if candidate == graph:
            continue
        legal += 1
        candidate_score = replace(
            score_graph(candidate),
            novelty=_novelty(candidate, best_graph),
        )
        accept = False
        if config.algorithm == "simulated_annealing":
            temperature = max(
                0.05,
                8.0 * (0.9995 ** (algorithm_evaluated % 20_000)),
            )
            if stagnation > 2_000:
                temperature = 8.0
                stagnation = 0
            delta = _scalar(candidate_score) - _scalar(score)
            accept = delta <= 0 or rng.random() < math.exp(
                -min(delta, 700) / temperature
            )
        else:
            key = candidate.stable_hash()
            if key not in tabu and candidate_score.ordering_key <= score.ordering_key:
                accept = True
            elif algorithm_evaluated % 64 == 0:
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
                checkpoint_payload(),
            )
            last_report = now
    _put(
        queue,
        checkpoint_payload(),
        important=True,
    )
    _put(
        queue,
        {
            "kind": "exit",
            "worker": worker_id,
            "reason": (
                "stopped"
                if stop.is_set()
                else "budget"
                if candidate_budget is not None
                and lifetime_evaluated + evaluated >= candidate_budget
                else "recycle"
            ),
            "evaluated": evaluated,
            "accepted": accepted,
            "legal": legal,
            "improvements": improvements,
        },
        important=True,
    )


def _worker_entry(
    worker_id: int,
    config: SearchConfig,
    queue: Queue,
    stop: Event,
    pause: Event,
    resume_checkpoint: dict[str, Any] | None = None,
) -> None:
    score_worker: PersistentScoreWorker | None = None
    try:
        if (
            config.memory_limit_bytes
            and config.memory_limit_bytes < 128 * 1024 * 1024
        ):
            raise ScoreWorkerError(
                "worker memory limit must be at least 128 MiB for the "
                "mandatory C++ scorer"
            )
        parent_memory_limit = (
            config.memory_limit_bytes - DEFAULT_WORKER_MEMORY_BYTES
            if config.memory_limit_bytes
            else None
        )
        set_address_space_limit(parent_memory_limit)
        score_worker = PersistentScoreWorker(
            memory_limit_bytes=DEFAULT_WORKER_MEMORY_BYTES
        )
        score_worker.start()
        _worker(
            worker_id,
            config,
            queue,
            stop,
            pause,
            resume_checkpoint,
            score_worker=score_worker,
        )
    except ScoreWorkerError as error:
        _put(
            queue,
            {
                "kind": "exit",
                "worker": worker_id,
                "reason": "score_worker",
                "error": f"{type(error).__name__}: {error}",
            },
            important=True,
        )
        raise SystemExit(78) from error
    except MemoryError as error:
        _put(
            queue,
            {
                "kind": "exit",
                "worker": worker_id,
                "reason": "memory",
                "error": f"{type(error).__name__}: {error}",
            },
            important=True,
        )
    except BaseException as error:
        _put(
            queue,
            {
                "kind": "exit",
                "worker": worker_id,
                "reason": "failure",
                "error": f"{type(error).__name__}: {error}",
            },
            important=True,
        )
        raise
    finally:
        if score_worker is not None:
            score_worker.close()


def _environment() -> dict[str, Any]:
    repository = source_root()
    git = (
        run_bounded(
            ["git", "rev-parse", "HEAD"],
            timeout_seconds=5,
            output_limit_bytes=1024,
            cwd=repository,
        )
        if repository is not None
        else None
    )
    git_status = (
        run_bounded(
            ["git", "status", "--porcelain"],
            timeout_seconds=5,
            output_limit_bytes=1024 * 1024,
            cwd=repository,
        )
        if repository is not None
        else None
    )
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
    external_tools = {tool.name: tool.version() for tool in TOOLS}
    return {
        "python": platform.python_version(),
        "sglab_version": __version__,
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "pid": os.getpid(),
        "git_commit": (
            git.stdout.decode("ascii", errors="replace").strip()
            if git is not None
            else None
        )
        or None,
        "git_dirty": (
            bool(git_status.stdout.strip())
            if git_status is not None and git_status.status == "OK"
            else None
        ),
        "cyclecheck_version": (
            cycle_version.stdout.decode("utf-8", errors="replace").strip()
            if cycle_version is not None
            else None
        ),
        "external_tools": external_tools,
        "cgroup_v2": Path("/sys/fs/cgroup/cgroup.controllers").exists(),
    }


def _run_id(config: SearchConfig) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    algorithm = "sa" if config.algorithm == "simulated_annealing" else "ils"
    target = "".join(part[0] for part in config.target.split("_"))
    return f"{stamp}-{target}-n{config.order}-{algorithm}-s{config.seed}"


def run_search(config: SearchConfig, resume_run: Path | None = None) -> Path:
    config.validate()
    workspace = config.workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    with (workspace / ".run.lock").open("a", encoding="ascii") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("another run already owns this workspace") from error
        try:
            return _run_search_locked(config, resume_run)
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _run_search_locked(config: SearchConfig, resume_run: Path | None = None) -> Path:
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
            "target": config.target,
            "status_checked_at": "2026-07-23",
            "parameters": parameters,
            "environment": environment,
            "git_commit": environment["git_commit"],
            "tool_versions": {
                "cyclecheck": environment["cyclecheck_version"],
                **environment["external_tools"],
            },
            "status": "RUNNING",
        }
        atomic_write_json(run_dir / "run.json", run_record)
    else:
        run_dir = resume_run.resolve()
        if run_dir.parent.parent != workspace or not (run_dir / "run.json").is_file():
            raise ValueError(
                "resume directory must be a run inside the configured workspace"
            )
        run_record = read_json(run_dir / "run.json")
        run_id = str(run_record["run_id"])
        parameters = dict(run_record["parameters"])
    atomic_write_json(
        workspace / "current_run.json", {"run_id": run_id, "run_dir": str(run_dir)}
    )
    database = connect(run_dir / "results.sqlite3")

    def log_event(event: str, **fields: Any) -> None:
        append_event(
            run_dir / "events.jsonl",
            event,
            max_bytes=config.max_log_bytes,
            **fields,
        )

    if resume_run is None:
        insert_run(
            database,
            run_id,
            run_record["created_at"],
            config.target,
            parameters,
            run_record["environment"],
        )
        database.executemany(
            "INSERT OR REPLACE INTO tool_versions VALUES (?, ?, ?)",
            (
                (
                    "sglab-cyclecheck",
                    environment["cyclecheck_version"],
                    str(cyclecheck_path()),
                ),
                *(
                    (
                        name,
                        details.get("version"),
                        details.get("path"),
                    )
                    for name, details in environment["external_tools"].items()
                ),
            ),
        )
        database.commit()
        log_event("run_started", run_id=run_id)
    else:
        set_run_status(database, run_id, "RUNNING")
        log_event("run_resumed", run_id=run_id)

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
            target=_worker_entry,
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
    prior_state = (
        read_json(run_dir / "state.json", default={}) if resume_run is not None else {}
    )
    prior_throughput = prior_state.get("throughput", {})
    prior_elapsed = float(prior_state.get("elapsed_seconds", 0))
    prior_evaluated = int(prior_throughput.get("candidates", 0))
    prior_accepted = int(prior_throughput.get("accepted", 0))
    prior_improvements = int(prior_throughput.get("improvements", 0))
    archive: dict[str, tuple[tuple[int, ...], dict[str, Any]]] = {}
    plugin = TARGETS[config.target]
    for candidate_path in (run_dir / "best").glob("*.json"):
        record = read_json(candidate_path, default={})
        if "graph6" not in record:
            continue
        graph = BitGraph.from_graph6(str(record["graph6"]))
        key = plugin.canonical_key(graph).decode("ascii")
        ordering = tuple(int(value) for value in record["score"]["ordering_key"])
        archive[key] = (ordering, record)
    last_control_version = int(
        read_json(workspace / "control.json", default={"version": 0}).get("version", 0)
    )
    worker_restarts = [0] * worker_count
    worker_failure_restarts = [0] * worker_count
    worker_last_rss = [0] * worker_count
    exited_workers: set[int] = set()
    worker_exit_reasons: dict[int, str] = {}
    stopped_by_user = False
    disk_exhausted = False
    memory_exhausted = False
    memory_high_triggered = False
    worker_memory_failure = False
    unrecoverable_worker_failure = False

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
                    worker_last_rss[worker_id] = int(message.get("rss_bytes", 0))
                elif message["kind"] == "checkpoint":
                    worker_checkpoints[worker_id] = message
                elif message["kind"] == "improvement":
                    graph = BitGraph.from_graph6(message["graph6"])
                    key = plugin.canonical_key(graph).decode("ascii")
                    archive_novelty = min(
                        (
                            _novelty(
                                graph,
                                BitGraph.from_graph6(str(record["graph6"])),
                            )
                            for _, record in archive.values()
                        ),
                        default=1.0,
                    )
                    archive_score = replace(
                        _score_from_payload(message["score"]),
                        novelty=archive_novelty,
                    )
                    score_payload = _score_payload(archive_score)
                    order_key = archive_score.ordering_key
                    if key not in archive:
                        if len(archive) >= config.archive_top_k:
                            worst_key = max(archive, key=lambda item: archive[item][0])
                            if order_key >= archive[worst_key][0]:
                                continue
                            worst_record = archive.pop(worst_key)[1]
                            database.execute(
                                "DELETE FROM artifacts WHERE candidate_id=?",
                                (worst_record["candidate_id"],),
                            )
                            database.execute(
                                "DELETE FROM verifications WHERE candidate_id=?",
                                (worst_record["candidate_id"],),
                            )
                            database.execute(
                                "DELETE FROM candidate_scores WHERE candidate_id=?",
                                (worst_record["candidate_id"],),
                            )
                            database.execute(
                                "DELETE FROM candidates WHERE candidate_id=?",
                                (worst_record["candidate_id"],),
                            )
                            for filename in worst_record.get("artifacts", {}).values():
                                path = run_dir / "best" / str(filename)
                                if path.is_file():
                                    path.unlink()
                            certificate_dir = (
                                run_dir
                                / "certificates"
                                / str(worst_record["candidate_id"])
                            )
                            if certificate_dir.is_dir():
                                for path in certificate_dir.iterdir():
                                    if path.is_file() or path.is_symlink():
                                        path.unlink()
                                certificate_dir.rmdir()
                        candidate_id, record = write_candidate(
                            run_dir, graph, score_payload, run_id
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
                                json.dumps(score_payload, sort_keys=True),
                                "PENDING",
                                utc_now(),
                            ),
                        )
                        components = {
                            "valid": int(bool(score_payload["valid"])),
                            "witness_total": sum(
                                int(value)
                                for value in score_payload["witness_counts"].values()
                            ),
                            "weighted_penalty": int(score_payload["weighted_penalty"]),
                            "novelty": float(score_payload["novelty"]),
                            "simplicity": int(score_payload["simplicity"]),
                        }
                        database.executemany(
                            "INSERT OR REPLACE INTO candidate_scores VALUES (?, ?, ?)",
                            (
                                (candidate_id, component, value)
                                for component, value in components.items()
                            ),
                        )
                        database.executemany(
                            """
                            INSERT INTO artifacts
                            (run_id, candidate_id, kind, path, sha256)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                (
                                    run_id,
                                    candidate_id,
                                    kind,
                                    str(Path("best") / filename),
                                    hash_file(run_dir / "best" / filename),
                                )
                                for kind, filename in record["artifacts"].items()
                            ),
                        )
                        database.commit()
                        log_event(
                            "improvement_archived",
                            worker=worker_id,
                            candidate_id=candidate_id,
                            score=order_key,
                        )
                elif message["kind"] == "exit":
                    for field in ("evaluated", "accepted", "legal", "improvements"):
                        worker_cumulative[worker_id][field] += int(
                            message.get(field, 0)
                        )
                    last_metrics = worker_metrics.pop(worker_id, None)
                    if last_metrics is not None:
                        worker_last_rss[worker_id] = int(
                            last_metrics.get("rss_bytes", 0)
                        )
                    exited_workers.add(worker_id)
                    worker_exit_reasons[worker_id] = str(message["reason"])
                    if message["reason"] == "memory":
                        worker_memory_failure = True
                    if message.get("error"):
                        log_event(
                            "worker_exit_error",
                            worker=worker_id,
                            reason=message["reason"],
                            error=message["error"],
                        )

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
                log_event("control_processed", action=action)

            total = (
                sum(values["evaluated"] for values in worker_cumulative.values())
                + sum(int(item.get("evaluated", 0)) for item in worker_metrics.values())
                + prior_evaluated
            )
            worker_rss = sum(
                int(item.get("rss_bytes", 0)) for item in worker_metrics.values()
            )
            master_rss = current_rss_bytes()
            aggregate_rss = master_rss + worker_rss
            if config.max_candidates and total >= config.max_candidates:
                stop.set()
            if elapsed >= config.wall_seconds:
                stop.set()
            if disk_free_bytes(run_dir) < config.min_free_disk_bytes:
                disk_exhausted = True
                stop.set()
            if config.memory_limit_bytes and aggregate_rss >= config.memory_limit_bytes:
                memory_exhausted = True
                stop.set()
            elif (
                config.memory_high_bytes
                and aggregate_rss >= config.memory_high_bytes
                and not memory_high_triggered
            ):
                memory_high_triggered = True
                pause.set()
                log_event(
                    "memory_high_pause",
                    aggregate_rss_bytes=aggregate_rss,
                    master_rss_bytes=master_rss,
                    worker_rss_bytes=worker_rss,
                    memory_high_bytes=config.memory_high_bytes,
                )
                database_checkpoint(database)
            for worker_id, process in enumerate(processes):
                if (
                    not stop.is_set()
                    and not process.is_alive()
                    and process.exitcode is not None
                ):
                    reason = worker_exit_reasons.get(worker_id)
                    if process.exitcode == 78:
                        reason = "score_worker"
                    checkpoint_data = worker_checkpoints.get(worker_id, {})
                    last_rss_bytes = worker_last_rss[worker_id]
                    if process.exitcode == 0 and reason is None:
                        # The process can exit just before its final queue message
                        # is drained. Do not misclassify normal recycling as a crash.
                        if message is not None:
                            continue
                        candidate_budget = _worker_candidate_budget(config, worker_id)
                        reason = (
                            "budget"
                            if candidate_budget is not None
                            and int(checkpoint_data.get("lifetime_evaluated", 0))
                            >= candidate_budget
                            else "recycle"
                        )
                    if worker_id in worker_metrics:
                        last_metrics = worker_metrics.pop(worker_id)
                        for field in ("evaluated", "accepted", "legal", "improvements"):
                            worker_cumulative[worker_id][field] += int(
                                last_metrics.get(field, 0)
                            )
                    if reason == "budget":
                        continue
                    if reason != "recycle":
                        worker_failure_restarts[worker_id] += 1
                    if reason == "score_worker":
                        unrecoverable_worker_failure = True
                        log_event(
                            "worker_abandoned",
                            worker=worker_id,
                            reason=reason,
                            prior_exitcode=process.exitcode,
                            last_candidate_id=_checkpoint_candidate_id(
                                checkpoint_data
                            ),
                            last_rss_bytes=last_rss_bytes,
                            retry=False,
                        )
                        stop.set()
                        continue
                    if worker_failure_restarts[worker_id] > 3:
                        if reason == "memory":
                            worker_memory_failure = True
                        else:
                            unrecoverable_worker_failure = True
                        log_event(
                            "worker_abandoned",
                            worker=worker_id,
                            reason=reason,
                            prior_exitcode=process.exitcode,
                            last_candidate_id=_checkpoint_candidate_id(checkpoint_data),
                            last_rss_bytes=last_rss_bytes,
                            retry=False,
                        )
                        stop.set()
                        continue
                    replacement = context.Process(
                        target=_worker_entry,
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
                    log_event(
                        "worker_restarted",
                        worker=worker_id,
                        reason=reason,
                        prior_exitcode=process.exitcode,
                        last_candidate_id=_checkpoint_candidate_id(checkpoint_data),
                        last_rss_bytes=last_rss_bytes,
                        retry=True,
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
                prune_metrics(database)
                database_checkpoint(database)
                last_checkpoint = now

            if now - last_state >= config.state_seconds:
                total_accepted = (
                    sum(values["accepted"] for values in worker_cumulative.values())
                    + sum(
                        int(item.get("accepted", 0)) for item in worker_metrics.values()
                    )
                    + prior_accepted
                )
                total_improvements = (
                    sum(values["improvements"] for values in worker_cumulative.values())
                    + sum(
                        int(item.get("improvements", 0))
                        for item in worker_metrics.values()
                    )
                    + prior_improvements
                )
                best_record = (
                    min(archive.values(), key=lambda item: item[0])[1]
                    if archive
                    else None
                )
                status = (
                    "PAUSED_MEMORY_HIGH"
                    if memory_high_triggered and pause.is_set()
                    else "PAUSED"
                    if pause.is_set()
                    else "STOPPING"
                    if stop.is_set()
                    else "RUNNING"
                )
                state = {
                    "updated_at": utc_now(),
                    "run_id": run_id,
                    "run_dir": str(run_dir),
                    "target": config.target,
                    "status": status,
                    "elapsed_seconds": prior_elapsed + elapsed,
                    "remaining_seconds": max(0.0, config.wall_seconds - elapsed),
                    "configuration": {
                        "order": config.order,
                        "mode": config.mode,
                        "algorithm": config.algorithm,
                        "seed": config.seed,
                        "wall_seconds": config.wall_seconds,
                    },
                    "workers": {
                        "configured": worker_count,
                        "alive": sum(process.is_alive() for process in processes),
                        "restarts": sum(worker_restarts),
                        "failed": sum(worker_failure_restarts),
                        "items": [
                            {
                                "worker": worker_id,
                                "alive": processes[worker_id].is_alive(),
                                "restarts": worker_restarts[worker_id],
                                "failures": worker_failure_restarts[worker_id],
                                "session_evaluated": worker_cumulative[worker_id][
                                    "evaluated"
                                ]
                                + int(
                                    worker_metrics.get(worker_id, {}).get(
                                        "evaluated", 0
                                    )
                                ),
                                "session_accepted": worker_cumulative[worker_id][
                                    "accepted"
                                ]
                                + int(
                                    worker_metrics.get(worker_id, {}).get("accepted", 0)
                                ),
                                "rss_bytes": int(
                                    worker_metrics.get(worker_id, {}).get(
                                        "rss_bytes", 0
                                    )
                                ),
                            }
                            for worker_id in range(worker_count)
                        ],
                    },
                    "throughput": {
                        "candidates": total,
                        "accepted": total_accepted,
                        "improvements": total_improvements,
                        "candidates_per_second": total
                        / max(prior_elapsed + elapsed, 0.001),
                    },
                    "best": best_record,
                    "exact_verification": {
                        "queued": 0,
                        "verified_candidates": sum(
                            _verification_completed(record)
                            for _, record in archive.values()
                        ),
                    },
                    "resources": {
                        "master_rss_bytes": master_rss,
                        "worker_rss_bytes": sum(
                            int(item.get("rss_bytes", 0))
                            for item in worker_metrics.values()
                        ),
                        "aggregate_rss_bytes": aggregate_rss,
                        "load_average": list(os.getloadavg()),
                        "disk_free_bytes": disk_free_bytes(run_dir),
                        "database_bytes": sqlite_size_bytes(
                            run_dir / "results.sqlite3"
                        ),
                    },
                    "queues": {
                        "telemetry_current": _queue_size(queue),
                        "telemetry_max": config.queue_capacity,
                        "exact_current": 0,
                    },
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
                            total / max(prior_elapsed + elapsed, 0.001),
                            aggregate_rss,
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
        if memory_exhausted or worker_memory_failure
        else "TOOL_FAILURE"
        if disk_exhausted or unrecoverable_worker_failure
        else "NO_RESULT_WITHIN_BUDGET"
    )
    verified_best_record: dict[str, Any] | None = None
    if archive and not disk_exhausted:
        best_record = min(archive.values(), key=lambda item: item[0])[1]
        best_graph = BitGraph.from_graph6(str(best_record["graph6"]))
        verification_state = {
            **read_json(run_dir / "state.json", default={}),
            "updated_at": utc_now(),
            "status": "VERIFYING_FINALIST",
            "exact_verification": {
                "queued": 1,
                "verified_candidates": sum(
                    _verification_completed(record) for _, record in archive.values()
                ),
            },
        }
        atomic_write_json(run_dir / "state.json", verification_state)
        atomic_write_json(workspace / "state.json", verification_state)
        verification = certify(
            best_graph,
            run_dir / "certificates" / str(best_record["candidate_id"]),
            timeout_seconds=config.exact_timeout_seconds,
            memory_limit_bytes=config.memory_limit_bytes,
            target=config.target,
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
        database.execute(
            "DELETE FROM verifications WHERE candidate_id=?",
            (best_record["candidate_id"],),
        )
        best_json_relative = str(Path("best") / f"{best_record['candidate_id']}.json")
        database.execute(
            "UPDATE artifacts SET sha256=? WHERE candidate_id=? AND path=?",
            (
                hash_file(run_dir / best_json_relative),
                best_record["candidate_id"],
                best_json_relative,
            ),
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
        certificate_dir = run_dir / "certificates" / str(best_record["candidate_id"])
        database.execute(
            "DELETE FROM artifacts WHERE candidate_id=? AND kind LIKE 'certificate_%'",
            (best_record["candidate_id"],),
        )
        database.executemany(
            """
            INSERT INTO artifacts
            (run_id, candidate_id, kind, path, sha256)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                (
                    run_id,
                    best_record["candidate_id"],
                    f"certificate_{path.suffix.lstrip('.') or 'file'}",
                    str(path.relative_to(run_dir)),
                    hash_file(path),
                )
                for path in certificate_dir.iterdir()
                if path.is_file()
            ),
        )
        database.commit()
        log_event(
            "finalist_verified",
            candidate_id=best_record["candidate_id"],
            status=verification["status"],
        )
        if verification["status"] == "COUNTEREXAMPLE_VERIFIED":
            final_status = "COUNTEREXAMPLE_VERIFIED"
        verified_best_record = best_record
    elif archive:
        log_event(
            "finalist_verification_skipped",
            reason="disk_free_below_configured_minimum",
        )
    total = (
        sum(values["evaluated"] for values in worker_cumulative.values())
        + sum(int(item.get("evaluated", 0)) for item in worker_metrics.values())
        + prior_evaluated
    )
    total_accepted = (
        sum(values["accepted"] for values in worker_cumulative.values())
        + sum(int(item.get("accepted", 0)) for item in worker_metrics.values())
        + prior_accepted
    )
    total_improvements = (
        sum(values["improvements"] for values in worker_cumulative.values())
        + sum(int(item.get("improvements", 0)) for item in worker_metrics.values())
        + prior_improvements
    )
    total_elapsed = prior_elapsed + time.monotonic() - started
    final_master_rss = current_rss_bytes()
    final_state = {
        **read_json(run_dir / "state.json", default={}),
        "updated_at": utc_now(),
        "run_id": run_id,
        "run_dir": str(run_dir),
        "status": final_status,
        "elapsed_seconds": total_elapsed,
        "remaining_seconds": 0,
        "stop_requested": stopped_by_user,
        "configuration": {
            "order": config.order,
            "mode": config.mode,
            "algorithm": config.algorithm,
            "seed": config.seed,
            "wall_seconds": config.wall_seconds,
        },
        "workers": {
            "configured": worker_count,
            "alive": 0,
            "restarts": sum(worker_restarts),
            "failed": sum(worker_failure_restarts),
            "items": [
                {
                    "worker": worker_id,
                    "alive": False,
                    "restarts": worker_restarts[worker_id],
                    "failures": worker_failure_restarts[worker_id],
                    "session_evaluated": worker_cumulative[worker_id]["evaluated"],
                    "session_accepted": worker_cumulative[worker_id]["accepted"],
                    "rss_bytes": 0,
                }
                for worker_id in range(worker_count)
            ],
        },
        "throughput": {
            "candidates": total,
            "accepted": total_accepted,
            "improvements": total_improvements,
            "candidates_per_second": total / max(total_elapsed, 0.001),
        },
        "exact_verification": {
            "queued": 0,
            "verified_candidates": sum(
                _verification_completed(record) for _, record in archive.values()
            ),
        },
        "queues": {
            "telemetry_current": 0,
            "telemetry_max": config.queue_capacity,
            "exact_current": 0,
        },
        "resources": {
            **read_json(run_dir / "state.json", default={}).get("resources", {}),
            "master_rss_bytes": final_master_rss,
            "worker_rss_bytes": 0,
            "aggregate_rss_bytes": final_master_rss,
            "load_average": list(os.getloadavg()),
            "disk_free_bytes": disk_free_bytes(run_dir),
            "database_bytes": sqlite_size_bytes(run_dir / "results.sqlite3"),
        },
    }
    if verified_best_record is not None:
        final_state["best"] = verified_best_record
    atomic_write_json(run_dir / "state.json", final_state)
    atomic_write_json(workspace / "state.json", final_state)
    set_run_status(database, run_id, final_status)
    database_checkpoint(database)
    database.close()
    log_event("run_finished", status=final_status)
    return run_dir


def config_from_run(run_dir: Path, wall_seconds: float | None = None) -> SearchConfig:
    record = read_json(run_dir / "run.json")
    values = dict(record["parameters"])
    values["workspace"] = Path(values["workspace"])
    if wall_seconds is not None:
        values["wall_seconds"] = wall_seconds
    allowed = SearchConfig.__dataclass_fields__
    return SearchConfig(
        **{key: value for key, value in values.items() if key in allowed}
    )
