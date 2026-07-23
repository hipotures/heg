from __future__ import annotations

from pathlib import Path
from typing import Any
from multiprocessing import get_context
from queue import Empty
import hashlib
import json
import os
import platform
import tempfile
import time

from .model import BitGraph
from .resources import run_bounded
from .state import atomic_write_json, utc_now
from .targets.erdos_gyarfas import forbidden_lengths, verify_reference


def default_cyclecheck() -> Path:
    return Path(__file__).resolve().parents[2] / "_build" / "sglab-cyclecheck"


def verify_cpp(
    graph: BitGraph,
    binary: Path | None = None,
    timeout_seconds: float = 0,
) -> dict[str, Any]:
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
            timeout_seconds=max(timeout_seconds + 2, 5) if timeout_seconds > 0 else 7 * 86400,
            output_limit_bytes=1024 * 1024,
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
        return {
            "status": "TOOL_FAILURE",
            "complete": False,
            "elapsed_seconds": elapsed,
            "message": "cycle checker returned invalid JSON",
            "stderr": result.stderr.decode("utf-8", errors="replace"),
        }
    payload["elapsed_seconds"] = elapsed
    payload["implementation"] = "cpp17-bitset-dfs"
    if result.status == "UNKNOWN_TIMEOUT" or payload.get("status") == "TIMEOUT":
        payload["status"] = "UNKNOWN_TIMEOUT"
        payload["complete"] = False
    elif result.status != "OK" and payload.get("status") != "ERROR":
        payload["status"] = "TOOL_FAILURE"
        payload["complete"] = False
    return payload


def _reference_worker(graph: BitGraph, queue: Any) -> None:
    result = verify_reference(graph)
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
    graph: BitGraph, timeout_seconds: float = 0
) -> dict[str, Any]:
    context = get_context("spawn")
    queue = context.Queue(maxsize=1)
    process = context.Process(target=_reference_worker, args=(graph, queue))
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
        report = {
            "status": "TOOL_FAILURE",
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
) -> dict[str, Any]:
    """Create a standalone two-verifier artifact from a graph only."""

    output_dir.mkdir(parents=True, exist_ok=True)
    graph6 = graph.to_graph6()
    graph6_bytes = (graph6 + "\n").encode("ascii")
    edge_payload = {
        "n": graph.n,
        "edges": [list(edge) for edge in graph.edges()],
    }
    edge_bytes = (json.dumps(edge_payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    (output_dir / "candidate.graph6").write_bytes(graph6_bytes)
    (output_dir / "candidate.json").write_bytes(edge_bytes)
    reference_payload = verify_reference_bounded(graph, timeout_seconds)
    independent = verify_cpp(graph, binary, timeout_seconds)
    if (
        independent["status"] == "UNKNOWN_TIMEOUT"
        or reference_payload["status"] == "UNKNOWN_TIMEOUT"
    ):
        status = "UNKNOWN_TIMEOUT"
    elif (
        independent["status"] in {"TOOL_FAILURE", "ERROR"}
        or reference_payload["status"] == "TOOL_FAILURE"
    ):
        status = "TOOL_FAILURE"
    elif reference_payload["status"] == "VERIFIED" and independent["status"] == "ABSENT":
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
    repository = Path(__file__).resolve().parents[2]
    git_result = run_bounded(
        ["git", "rev-parse", "HEAD"],
        timeout_seconds=5,
        output_limit_bytes=1024,
        cwd=repository,
    )
    environment = {
        "created_at": utc_now(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "cpu_count": os.cpu_count(),
        "git_commit": git_result.stdout.decode("ascii", errors="replace").strip() or None,
        "cyclecheck": str(executable),
        "cyclecheck_sha256": (
            hashlib.sha256(executable.read_bytes()).hexdigest()
            if executable.is_file()
            else None
        ),
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
