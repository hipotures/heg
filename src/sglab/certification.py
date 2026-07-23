from __future__ import annotations

from pathlib import Path
from typing import Any
from multiprocessing import get_context
from queue import Empty
import hashlib
import json
import math
import os
import platform
import tempfile
import time

from . import __version__
from .artifacts import hash_file
from .model import BitGraph
from .locations import cyclecheck_path, source_root
from .resources import run_bounded, set_address_space_limit
from .state import atomic_write_json, utc_now
from .targets.erdos_gyarfas import forbidden_lengths, verify_reference


def default_cyclecheck() -> Path:
    return cyclecheck_path()


def verify_cpp(
    graph: BitGraph,
    binary: Path | None = None,
    timeout_seconds: float = 0,
    memory_limit_bytes: int = 0,
) -> dict[str, Any]:
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise ValueError("timeout_seconds must be finite and nonnegative")
    if memory_limit_bytes < 0:
        raise ValueError("memory_limit_bytes cannot be negative")
    executable = (binary or default_cyclecheck()).resolve()
    if not executable.is_file():
        return {
            "status": "TOOL_FAILURE",
            "complete": False,
            "message": f"missing cycle checker: {executable}",
        }
    with tempfile.TemporaryDirectory(prefix="sglab-cyclecheck-") as directory:
        graph_path = Path(directory) / "candidate.graph6"
        graph_path.write_text(graph.to_graph6() + "\n", encoding="ascii")
        command = [str(executable), "--graph6", str(graph_path)]
        for length in forbidden_lengths(graph.n):
            command.extend(("--length", str(length)))
        if timeout_seconds > 0:
            command.extend(("--timeout-seconds", str(timeout_seconds)))
        started = time.perf_counter()
        result = run_bounded(
            command,
            timeout_seconds=max(timeout_seconds + 2, 5)
            if timeout_seconds > 0
            else 7 * 86400,
            output_limit_bytes=1024 * 1024,
            memory_limit_bytes=memory_limit_bytes or None,
        )
        elapsed = time.perf_counter() - started
    if result.status == "UNKNOWN_TIMEOUT":
        return {
            "status": "UNKNOWN_TIMEOUT",
            "complete": False,
            "elapsed_seconds": elapsed,
            "implementation": "cpp17-bitset-dfs",
            "message": "cycle checker exceeded its wall-time budget",
        }
    try:
        payload = json.loads(result.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        if memory_limit_bytes and result.returncode not in (0, None):
            return {
                "status": "UNKNOWN_MEMORY_LIMIT",
                "complete": False,
                "elapsed_seconds": elapsed,
                "message": "cycle checker failed under its memory limit",
            }
        return {
            "status": "TOOL_FAILURE",
            "complete": False,
            "elapsed_seconds": elapsed,
            "message": "cycle checker returned invalid JSON",
            "stderr": result.stderr.decode("utf-8", errors="replace"),
        }
    validation_error = _cyclecheck_payload_error(payload, graph)
    if validation_error is not None:
        return {
            "status": "TOOL_FAILURE",
            "complete": False,
            "elapsed_seconds": elapsed,
            "message": validation_error,
            "stderr": result.stderr.decode("utf-8", errors="replace"),
        }
    payload["elapsed_seconds"] = elapsed
    payload["implementation"] = "cpp17-bitset-dfs"
    if (
        memory_limit_bytes
        and payload.get("status") == "ERROR"
        and "alloc" in str(payload.get("message", "")).lower()
    ):
        payload["status"] = "UNKNOWN_MEMORY_LIMIT"
        payload["complete"] = False
    if result.status == "UNKNOWN_TIMEOUT" or payload.get("status") == "TIMEOUT":
        payload["status"] = "UNKNOWN_TIMEOUT"
        payload["complete"] = False
    elif result.status != "OK" and payload.get("status") != "ERROR":
        payload["status"] = "TOOL_FAILURE"
        payload["complete"] = False
    return payload


def _cyclecheck_payload_error(payload: object, graph: BitGraph) -> str | None:
    if not isinstance(payload, dict):
        return "cycle checker JSON must be an object"
    status = payload.get("status")
    if status not in {"FOUND", "ABSENT", "TIMEOUT", "ERROR"}:
        return "cycle checker returned an unknown status"
    if not isinstance(payload.get("complete"), bool):
        return "cycle checker omitted its completeness flag"
    lengths = set(forbidden_lengths(graph.n))
    if status == "FOUND":
        length = payload.get("length")
        witness = payload.get("witness")
        if (
            isinstance(length, bool)
            or not isinstance(length, int)
            or length not in lengths
        ):
            return "cycle checker returned an invalid witness length"
        if (
            not isinstance(witness, list)
            or len(witness) != length
            or any(
                isinstance(vertex, bool)
                or not isinstance(vertex, int)
                or not 0 <= vertex < graph.n
                for vertex in witness
            )
            or len(set(witness)) != length
        ):
            return "cycle checker returned invalid witness vertices"
        if any(
            not graph.has_edge(witness[index], witness[(index + 1) % length])
            for index in range(length)
        ):
            return "cycle checker witness is not a cycle in the input graph"
        if not payload["complete"]:
            return "a found witness must be complete"
    elif status == "ABSENT":
        reported = payload.get("lengths")
        if (
            not payload["complete"]
            or not isinstance(reported, list)
            or any(
                isinstance(length, bool) or not isinstance(length, int)
                for length in reported
            )
            or set(reported) != lengths
        ):
            return "cycle checker absence result does not cover all requested lengths"
    elif payload["complete"]:
        return "timeout and error results cannot be complete"
    return None


def _reference_worker(graph: BitGraph, queue: Any, memory_limit_bytes: int) -> None:
    set_address_space_limit(memory_limit_bytes or None)
    try:
        result = verify_reference(graph)
    except MemoryError:
        queue.put(
            {
                "status": "UNKNOWN_MEMORY_LIMIT",
                "complete": False,
                "message": "Python verifier exceeded its memory limit",
                "implementation": "python-reference-dfs",
                "witnesses": [],
                "elapsed_seconds": 0,
            }
        )
        return
    queue.put(
        {
            "status": result.status,
            "complete": result.complete,
            "message": result.message,
            "elapsed_seconds": result.elapsed_seconds,
            "implementation": result.implementation,
            "witnesses": [
                {"kind": witness.kind, "vertices": list(witness.vertices)}
                for witness in result.witnesses
            ],
        }
    )


def verify_reference_bounded(
    graph: BitGraph,
    timeout_seconds: float = 0,
    memory_limit_bytes: int = 0,
) -> dict[str, Any]:
    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise ValueError("timeout_seconds must be finite and nonnegative")
    if memory_limit_bytes < 0:
        raise ValueError("memory_limit_bytes cannot be negative")
    context = get_context("spawn")
    queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_reference_worker,
        args=(graph, queue, memory_limit_bytes),
    )
    process.start()
    process.join(timeout_seconds if timeout_seconds > 0 else None)
    if process.is_alive():
        process.kill()
        process.join()
        queue.close()
        return {
            "status": "UNKNOWN_TIMEOUT",
            "complete": False,
            "message": "Python reference verifier exceeded its wall-time budget",
            "implementation": "python-reference-dfs",
            "witnesses": [],
            "elapsed_seconds": timeout_seconds,
        }
    try:
        report = queue.get(timeout=0.5)
    except Empty:
        status = (
            "UNKNOWN_MEMORY_LIMIT"
            if memory_limit_bytes and process.exitcode not in (0, None)
            else "TOOL_FAILURE"
        )
        report = {
            "status": status,
            "complete": False,
            "message": f"Python verifier worker exited with {process.exitcode}",
            "implementation": "python-reference-dfs",
            "witnesses": [],
            "elapsed_seconds": 0,
        }
    queue.close()
    return report


def certify(
    graph: BitGraph,
    output_dir: Path,
    *,
    binary: Path | None = None,
    timeout_seconds: float = 0,
    memory_limit_bytes: int = 0,
) -> dict[str, Any]:
    """Create a standalone two-verifier artifact from a graph only."""

    if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise ValueError("timeout_seconds must be finite and nonnegative")
    if memory_limit_bytes < 0:
        raise ValueError("memory_limit_bytes cannot be negative")
    output_dir.mkdir(parents=True, exist_ok=True)
    graph6 = graph.to_graph6()
    graph6_bytes = (graph6 + "\n").encode("ascii")
    edge_payload = {
        "n": graph.n,
        "edges": [list(edge) for edge in graph.edges()],
    }
    edge_bytes = (
        json.dumps(edge_payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    (output_dir / "candidate.graph6").write_bytes(graph6_bytes)
    (output_dir / "candidate.json").write_bytes(edge_bytes)
    reference_payload = verify_reference_bounded(
        graph,
        timeout_seconds,
        memory_limit_bytes,
    )
    independent = verify_cpp(
        graph,
        binary,
        timeout_seconds,
        memory_limit_bytes,
    )
    if reference_payload["status"] == "INVALID":
        status = "INVALID_CANDIDATE"
    elif (
        independent["status"] == "UNKNOWN_TIMEOUT"
        or reference_payload["status"] == "UNKNOWN_TIMEOUT"
    ):
        status = "UNKNOWN_TIMEOUT"
    elif (
        independent["status"] == "UNKNOWN_MEMORY_LIMIT"
        or reference_payload["status"] == "UNKNOWN_MEMORY_LIMIT"
    ):
        status = "UNKNOWN_MEMORY_LIMIT"
    elif (
        independent["status"] in {"TOOL_FAILURE", "ERROR"}
        or reference_payload["status"] == "TOOL_FAILURE"
    ):
        status = "TOOL_FAILURE"
    elif (
        reference_payload["status"] == "VERIFIED" and independent["status"] == "ABSENT"
    ):
        status = "COUNTEREXAMPLE_VERIFIED"
    elif reference_payload["status"] == "REJECTED" and independent["status"] == "FOUND":
        status = "INVALID_CANDIDATE"
    else:
        status = "VERIFIER_DISAGREEMENT"
    executable = (binary or default_cyclecheck()).resolve()
    cycle_version = (
        run_bounded(
            [str(executable), "--version"],
            timeout_seconds=5,
            output_limit_bytes=16 * 1024,
        )
        if executable.is_file()
        else None
    )
    repository = source_root()
    git_result = (
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
    environment = {
        "created_at": utc_now(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "sglab_version": __version__,
        "cpu_count": os.cpu_count(),
        "git_commit": (
            git_result.stdout.decode("ascii", errors="replace").strip()
            if git_result is not None
            else None
        )
        or None,
        "git_dirty": (
            bool(git_status.stdout.strip())
            if git_status is not None and git_status.status == "OK"
            else None
        ),
        "cyclecheck": str(executable),
        "cyclecheck_sha256": (hash_file(executable) if executable.is_file() else None),
        "cyclecheck_version": (
            cycle_version.stdout.decode("utf-8", errors="replace").strip()
            if cycle_version is not None
            else None
        ),
    }
    atomic_write_json(output_dir / "environment.json", environment)
    manifest = {
        "candidate_id": hashlib.sha256(graph6.encode("ascii")).hexdigest()[:20],
        "target": "erdos_gyarfas",
        "status": status,
        "status_checked_at": "2026-07-23",
        "order": graph.n,
        "size": graph.size(),
        "minimum_degree": graph.minimum_degree(),
        "forbidden_lengths": list(forbidden_lengths(graph.n)),
        "graph6_sha256": hashlib.sha256(graph6_bytes).hexdigest(),
        "edge_list_sha256": hashlib.sha256(edge_bytes).hexdigest(),
        "verifiers": [reference_payload, independent],
        "environment": "environment.json",
        "reproduce": "commands.txt",
    }
    atomic_write_json(output_dir / "manifest.json", manifest)
    (output_dir / "commands.txt").write_text(
        "sglab verify --graph6 candidate.graph6 --artifact-dir reproduced\n",
        encoding="utf-8",
    )
    return manifest
