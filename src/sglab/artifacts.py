from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import math

from .model import BitGraph
from .state import atomic_write_json


def graph_svg(graph: BitGraph, size: int = 480) -> str:
    radius = size * 0.39
    center = size / 2
    points = [
        (
            center + radius * math.cos(2 * math.pi * vertex / max(1, graph.n)),
            center + radius * math.sin(2 * math.pi * vertex / max(1, graph.n)),
        )
        for vertex in range(graph.n)
    ]
    edges = "\n".join(
        f'<line x1="{points[u][0]:.2f}" y1="{points[u][1]:.2f}" '
        f'x2="{points[v][0]:.2f}" y2="{points[v][1]:.2f}"/>'
        for u, v in graph.edges()
    )
    vertices = "\n".join(
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="5"/>' for x, y in points
    )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}"><g stroke="#64748b" stroke-width="1">'
        f'{edges}</g><g fill="#38bdf8">{vertices}</g></svg>\n'
    )


def write_candidate(
    run_dir: Path,
    graph: BitGraph,
    score: dict[str, Any],
    run_id: str,
) -> tuple[str, dict[str, Any]]:
    candidate_id = graph.stable_hash()[:20]
    graph6 = graph.to_graph6()
    graph6_bytes = (graph6 + "\n").encode("ascii")
    best = run_dir / "best"
    best.mkdir(parents=True, exist_ok=True)
    graph_path = best / f"{candidate_id}.graph6"
    json_path = best / f"{candidate_id}.json"
    svg_path = best / f"{candidate_id}.svg"
    graph_path.write_bytes(graph6_bytes)
    svg_path.write_text(graph_svg(graph), encoding="utf-8")
    histogram: dict[str, int] = {}
    for degree in graph.degree_sequence():
        histogram[str(degree)] = histogram.get(str(degree), 0) + 1
    record = {
        "candidate_id": candidate_id,
        "run_id": run_id,
        "graph6": graph6,
        "graph6_sha256": hashlib.sha256(graph6_bytes).hexdigest(),
        "order": graph.n,
        "size": graph.size(),
        "degree_histogram": histogram,
        "score": score,
        "verification_status": "PENDING",
        "artifacts": {
            "graph6": graph_path.name,
            "json": json_path.name,
            "svg": svg_path.name,
        },
    }
    atomic_write_json(json_path, record)
    return candidate_id, record


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
