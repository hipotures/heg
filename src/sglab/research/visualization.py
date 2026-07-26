from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
import hashlib
import json
import os
import stat
import sqlite3
from datetime import UTC, datetime

from ..model import BitGraph, find_cycles_of_length_bounded
from ..state import read_json
from ..targets import TARGETS
from .protocol import canonical_json


VISUALIZATION_CANDIDATE_LIMIT = 256
VISUALIZATION_LANE_WINDOW_LIMIT = 120
VISUALIZATION_TOTAL_WINDOW_LIMIT = 2048
VISUALIZATION_VERIFICATION_LIMIT = 64
VISUALIZATION_CYCLE_NODE_BUDGET = 20_000
VISUALIZATION_MANIFEST_LIMIT_BYTES = 1024 * 1024
VISUALIZATION_LIVE_CHECKPOINT_LIMIT_BYTES = 1024 * 1024
VISUALIZATION_LIVE_CHECKPOINT_SCAN_LIMIT = 256
VISUALIZATION_LIVE_DIRECTORY_ENTRY_LIMIT = 2048
DEFAULT_LIVE_FRONTIER_INTERVAL_SECONDS = 10
VISUALIZATION_SOURCES = {
    "global_best",
    "lane_best",
    "m4_active",
    "candidate",
    "live_frontier",
}


class VisualizationNotFoundError(KeyError):
    pass


class VisualizationUnavailableError(RuntimeError):
    pass


def campaign_graph_visualization(
    workspace: Path,
    *,
    source: str,
    lane_id: str | None = None,
    candidate_id: str | None = None,
    live_frontier_interval_seconds: int = (
        DEFAULT_LIVE_FRONTIER_INTERVAL_SECONDS
    ),
) -> dict[str, Any]:
    if source not in VISUALIZATION_SOURCES:
        raise ValueError("unsupported visualization source")
    if (
        isinstance(live_frontier_interval_seconds, bool)
        or not isinstance(live_frontier_interval_seconds, int)
        or not 1 <= live_frontier_interval_seconds <= 3600
    ):
        raise ValueError("live frontier interval must be 1 to 3600 seconds")
    if source == "lane_best" and not lane_id:
        raise ValueError("lane_best requires lane_id")
    if source == "candidate" and not candidate_id:
        raise ValueError("candidate source requires candidate_id")
    root, campaign_id, connection = _campaign_connection(workspace)
    try:
        campaign = connection.execute(
            "SELECT target FROM research_campaigns WHERE campaign_id=?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            raise VisualizationNotFoundError("campaign not found")
        target = str(campaign["target"])
        if source == "live_frontier":
            selected = _select_live_checkpoint(
                root / "research-campaigns" / campaign_id,
                connection=connection,
                campaign_id=campaign_id,
                lane_id=lane_id,
            )
        else:
            selected = _select_candidate(
                connection,
                campaign_id=campaign_id,
                source=source,
                lane_id=lane_id,
                candidate_id=candidate_id,
            )
        graph6 = str(selected["graph6"])
        try:
            graph = BitGraph.from_graph6(graph6)
        except (UnicodeError, ValueError) as error:
            raise VisualizationUnavailableError(
                "selected candidate graph is unavailable"
            ) from error
        graph_sha256 = hashlib.sha256(graph6.encode("ascii")).hexdigest()
        stored_graph_sha256 = selected.get("graph_sha256")
        if stored_graph_sha256 and stored_graph_sha256 != graph_sha256:
            raise VisualizationUnavailableError(
                "selected candidate graph hash mismatch"
            )
        score = _json_object(selected.get("score_json"))
        examples = [
            dict(item)
            for item in _bounded_cycle_examples(graph6, target)
        ]
        exact = _exact_verification(
            connection,
            campaign_root=root / "research-campaigns" / campaign_id,
            campaign_id=campaign_id,
            candidate_id=str(selected["candidate_id"]),
            graph=graph,
            graph6=graph6,
        )
        lanes = [
            {
                "lane_id": str(row["lane_id"]),
                "algorithm": str(row["algorithm"]),
                "state": str(row["state"]),
            }
            for row in connection.execute(
                """
                SELECT lane_id, algorithm, state FROM research_lanes
                WHERE campaign_id=? ORDER BY updated_at DESC, lane_id
                LIMIT 64
                """,
                (campaign_id,),
            )
        ]
        active_m4 = connection.execute(
            """
            SELECT verification_job_id, candidate_id
            FROM campaign_verification_jobs
            WHERE campaign_id=? AND state='running'
            ORDER BY started_at, created_at, verification_job_id LIMIT 1
            """,
            (campaign_id,),
        ).fetchone()
        return {
            "campaign_id": campaign_id,
            "source": source,
            "selection": {
                "candidate_id": str(selected["candidate_id"]),
                "candidate_snapshot_id": selected.get("candidate_snapshot_id"),
                "lane_id": str(selected["lane_id"]),
                "lane_version": int(selected["lane_version"]),
                "checkpoint_ref_present": bool(selected.get("checkpoint_ref")),
                "created_at": str(selected["created_at"]),
                "state": str(selected.get("state") or "retained"),
                "verification_status": selected.get("certification_status"),
                "graph_sha256": graph_sha256,
                "transient": bool(selected.get("transient")),
                "checkpoint_id": selected.get("checkpoint_id"),
                "high_water": selected.get("high_water"),
                "published_at": selected.get("published_at"),
            },
            "graph": {
                "order": graph.n,
                "size": graph.size(),
                "vertices": list(range(graph.n)),
                "edges": [list(edge) for edge in graph.edges()],
            },
            "score": score,
            "cycle_examples": examples,
            "exact_verification": exact,
            "availability": {
                "lanes": lanes,
                "m4_active": (
                    {
                        "verification_job_id": str(
                            active_m4["verification_job_id"]
                        ),
                        "candidate_id": str(active_m4["candidate_id"]),
                    }
                    if active_m4 is not None
                    else None
                ),
            },
            "display_contract": {
                "heuristic_examples_are_certification": False,
                "exact_authority": "persisted_M4_manifest",
                "cycle_node_budget_per_length": (
                    VISUALIZATION_CYCLE_NODE_BUDGET
                ),
                "symlink_targets_followed": False,
                "live_frontier_interval_seconds": (
                    live_frontier_interval_seconds
                ),
                "live_frontier_is_certification": False,
            },
        }
    finally:
        connection.close()


def campaign_visualization_series(workspace: Path) -> dict[str, Any]:
    _root, campaign_id, connection = _campaign_connection(workspace)
    try:
        candidates = []
        rows = connection.execute(
            """
            SELECT candidate_id, lane_id, created_at, state,
                   certification_status, score_json
            FROM campaign_candidates WHERE campaign_id=?
            ORDER BY created_at DESC, rowid DESC LIMIT ?
            """,
            (campaign_id, VISUALIZATION_CANDIDATE_LIMIT),
        ).fetchall()
        for row in reversed(rows):
            score = _json_object(row["score_json"])
            candidates.append(
                {
                    "candidate_id": str(row["candidate_id"]),
                    "lane_id": str(row["lane_id"]),
                    "created_at": str(row["created_at"]),
                    "state": str(row["state"]),
                    "certification_status": row["certification_status"],
                    "weighted_penalty": score.get("weighted_penalty"),
                    "witness_counts": score.get("witness_counts", {}),
                    "score_complete": score.get("complete"),
                    "ordering_key": score.get("ordering_key"),
                }
            )
        lane_rows = connection.execute(
            """
            SELECT lane_id, lane_version, end_high_water, end_at, metrics_json
            FROM lane_metric_windows WHERE campaign_id=?
            ORDER BY end_at DESC, rowid DESC LIMIT ?
            """,
            (campaign_id, VISUALIZATION_TOTAL_WINDOW_LIMIT),
        ).fetchall()
        per_lane: dict[str, int] = {}
        windows = []
        for row in lane_rows:
            lane = str(row["lane_id"])
            count = per_lane.get(lane, 0)
            if count >= VISUALIZATION_LANE_WINDOW_LIMIT:
                continue
            per_lane[lane] = count + 1
            metrics = _json_object(row["metrics_json"])
            windows.append(
                {
                    "lane_id": lane,
                    "lane_version": int(row["lane_version"]),
                    "end_high_water": int(row["end_high_water"]),
                    "end_at": str(row["end_at"]),
                    "candidates_per_second": metrics.get(
                        "candidates_per_second"
                    ),
                    "best_scalar": metrics.get("best_scalar"),
                    "best_score": metrics.get("best_score"),
                    "diversity": metrics.get("diversity"),
                    "operator_yield": metrics.get("operator_yield"),
                    "plateau_evaluations": metrics.get(
                        "plateau_evaluations"
                    ),
                }
            )
        windows.reverse()
        verifications = [
            {
                "verification_job_id": str(row["verification_job_id"]),
                "candidate_id": str(row["candidate_id"]),
                "state": str(row["state"]),
                "certification_status": row["certification_status"],
                "created_at": str(row["created_at"]),
                "started_at": row["started_at"],
                "completed_at": row["completed_at"],
                "immutable_snapshot": bool(row["candidate_snapshot_id"]),
            }
            for row in connection.execute(
                """
                SELECT verification_job_id, candidate_id, state,
                       certification_status, created_at, started_at,
                       completed_at, candidate_snapshot_id
                FROM campaign_verification_jobs WHERE campaign_id=?
                ORDER BY created_at DESC, rowid DESC LIMIT ?
                """,
                (campaign_id, VISUALIZATION_VERIFICATION_LIMIT),
            )
        ]
        lanes = [
            {
                "lane_id": str(row["lane_id"]),
                "algorithm": str(row["algorithm"]),
                "graph_family": str(row["graph_family"]),
                "state": str(row["state"]),
                "telemetry_high_water": int(row["telemetry_high_water"]),
            }
            for row in connection.execute(
                """
                SELECT lane_id, algorithm, graph_family, state,
                       telemetry_high_water
                FROM research_lanes WHERE campaign_id=?
                ORDER BY updated_at DESC, lane_id LIMIT 64
                """,
                (campaign_id,),
            )
        ]
        return {
            "campaign_id": campaign_id,
            "candidate_history": candidates,
            "lane_windows": windows,
            "verifications": verifications,
            "lanes": lanes,
            "limits": {
                "candidate_history": VISUALIZATION_CANDIDATE_LIMIT,
                "lane_windows_per_lane": VISUALIZATION_LANE_WINDOW_LIMIT,
                "verifications": VISUALIZATION_VERIFICATION_LIMIT,
            },
        }
    finally:
        connection.close()


def _campaign_connection(
    workspace: Path,
) -> tuple[Path, str, sqlite3.Connection]:
    root = workspace.resolve()
    pointer = read_json(root / "active-research-campaign.json", default={})
    if not pointer:
        pointer = read_json(
            root / "prepared-research-campaign.json", default={}
        )
    campaign_id = pointer.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id:
        raise VisualizationNotFoundError("no research campaign is selected")
    database = root / "results.sqlite3"
    if not database.is_file():
        raise VisualizationNotFoundError("campaign database is unavailable")
    connection = sqlite3.connect(
        f"{database.as_uri()}?mode=ro", uri=True, timeout=2
    )
    connection.row_factory = sqlite3.Row
    return root, campaign_id, connection


def _select_candidate(
    connection: sqlite3.Connection,
    *,
    campaign_id: str,
    source: str,
    lane_id: str | None,
    candidate_id: str | None,
) -> dict[str, Any]:
    if source == "m4_active":
        row = connection.execute(
            """
            SELECT j.verification_job_id, j.state AS job_state,
                   j.certification_status,
                   s.candidate_snapshot_id, s.candidate_id, s.graph6,
                   s.graph_sha256, s.score_json, s.lane_id, s.lane_version,
                   s.checkpoint_ref, s.source_created_at AS created_at,
                   'immutable_snapshot' AS state
            FROM campaign_verification_jobs j
            JOIN campaign_candidate_snapshots s
              ON s.candidate_snapshot_id=j.candidate_snapshot_id
            WHERE j.campaign_id=? AND j.state='running'
            ORDER BY j.started_at, j.created_at, j.verification_job_id
            LIMIT 1
            """,
            (campaign_id,),
        ).fetchone()
        if row is None:
            raise VisualizationUnavailableError(
                "no candidate is currently being verified by M4"
            )
        return dict(row)
    query = """
        SELECT candidate_id, graph6, graph_sha256, score_json, lane_id,
               lane_version, checkpoint_ref, created_at, state,
               certification_status, NULL AS candidate_snapshot_id
        FROM campaign_candidates WHERE campaign_id=?
    """
    parameters: list[Any] = [campaign_id]
    if source == "lane_best":
        exists = connection.execute(
            """
            SELECT 1 FROM research_lanes
            WHERE campaign_id=? AND lane_id=?
            """,
            (campaign_id, lane_id),
        ).fetchone()
        if exists is None:
            raise VisualizationNotFoundError("lane not found")
        query += " AND lane_id=?"
        parameters.append(lane_id)
    elif source == "candidate":
        query += " AND candidate_id=?"
        parameters.append(candidate_id)
    query += " ORDER BY created_at DESC, rowid DESC LIMIT ?"
    parameters.append(VISUALIZATION_CANDIDATE_LIMIT)
    rows = [dict(row) for row in connection.execute(query, parameters)]
    if not rows:
        raise VisualizationNotFoundError("candidate not found")
    if source == "candidate":
        return rows[0]
    return min(
        rows,
        key=lambda row: (
            _score_ordering_key(_json_object(row["score_json"])),
            -_timestamp_key(str(row["created_at"])),
            str(row["candidate_id"]),
        ),
    )


def _select_live_checkpoint(
    campaign_root: Path,
    *,
    connection: sqlite3.Connection,
    campaign_id: str,
    lane_id: str | None,
) -> dict[str, Any]:
    lane_rows = connection.execute(
        """
        SELECT lane_id, state FROM research_lanes
        WHERE campaign_id=? ORDER BY updated_at DESC, lane_id
        """,
        (campaign_id,),
    ).fetchall()
    known_lanes = {str(row["lane_id"]) for row in lane_rows}
    if lane_id is not None and lane_id not in known_lanes:
        raise VisualizationNotFoundError("lane not found")
    active_lanes = {
        str(row["lane_id"])
        for row in lane_rows
        if str(row["state"]) in {"starting", "running", "paused", "stopping"}
    }
    checkpoint_dir = campaign_root / "lane-checkpoints"
    try:
        directory_stat = checkpoint_dir.lstat()
    except FileNotFoundError as error:
        raise VisualizationUnavailableError(
            "no live search frontier is available"
        ) from error
    if (
        stat.S_ISLNK(directory_stat.st_mode)
        or not stat.S_ISDIR(directory_stat.st_mode)
    ):
        raise VisualizationUnavailableError(
            "live checkpoint directory is unavailable"
        )
    candidates: list[tuple[int, Path]] = []
    for inspected, path in enumerate(checkpoint_dir.iterdir(), start=1):
        if inspected > VISUALIZATION_LIVE_DIRECTORY_ENTRY_LIMIT:
            break
        if (
            path.name.startswith("checkpoint-")
            and path.name.endswith(".json")
        ):
            try:
                file_stat = path.lstat()
            except FileNotFoundError:
                continue
            if (
                stat.S_ISREG(file_stat.st_mode)
                and 0 < file_stat.st_size
                <= VISUALIZATION_LIVE_CHECKPOINT_LIMIT_BYTES
            ):
                candidates.append((file_stat.st_mtime_ns, path))
    candidates.sort(key=lambda item: (item[0], item[1].name), reverse=True)
    candidates = candidates[:VISUALIZATION_LIVE_CHECKPOINT_SCAN_LIMIT]
    fallback: dict[str, Any] | None = None
    for modified_ns, path in candidates:
        try:
            checkpoint = _read_live_checkpoint(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        checkpoint_lane = str(checkpoint.get("lane_id") or "")
        if checkpoint_lane not in known_lanes:
            continue
        if lane_id is not None and checkpoint_lane != lane_id:
            continue
        selected = _live_checkpoint_selection(
            checkpoint, modified_ns=modified_ns
        )
        if lane_id is not None or checkpoint_lane in active_lanes:
            return selected
        if fallback is None:
            fallback = selected
    if fallback is not None:
        return fallback
    raise VisualizationUnavailableError(
        "no live search frontier is available"
    )


def _read_live_checkpoint(path: Path) -> dict[str, Any]:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or not 0 < before.st_size
            <= VISUALIZATION_LIVE_CHECKPOINT_LIMIT_BYTES
        ):
            raise ValueError("live checkpoint is unavailable")
        chunks = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        before.st_dev != after.st_dev
        or before.st_ino != after.st_ino
        or before.st_size != after.st_size
        or len(payload) != before.st_size
    ):
        raise ValueError("live checkpoint changed while being read")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("live checkpoint must be an object")
    checkpoint_id = value.get("checkpoint_id")
    digest = value.get("sha256")
    unsigned = {
        key: item
        for key, item in value.items()
        if key not in {"checkpoint_id", "sha256"}
    }
    calculated = hashlib.sha256(
        canonical_json(
            unsigned,
            max_bytes=VISUALIZATION_LIVE_CHECKPOINT_LIMIT_BYTES,
        )
    ).hexdigest()
    if (
        not isinstance(checkpoint_id, str)
        or checkpoint_id != f"checkpoint-{calculated[:24]}"
        or digest != calculated
    ):
        raise ValueError("live checkpoint integrity mismatch")
    return value


def _live_checkpoint_selection(
    checkpoint: dict[str, Any], *, modified_ns: int
) -> dict[str, Any]:
    graph6 = checkpoint.get("graph6")
    score = checkpoint.get("score")
    candidate_id = checkpoint.get("current_candidate_id")
    lane_id = checkpoint.get("lane_id")
    if (
        not isinstance(graph6, str)
        or not isinstance(score, dict)
        or not isinstance(candidate_id, str)
        or not candidate_id
        or not isinstance(lane_id, str)
        or not lane_id
    ):
        raise ValueError("live checkpoint is incomplete")
    return {
        "candidate_id": candidate_id,
        "graph6": graph6,
        "graph_sha256": hashlib.sha256(
            graph6.encode("ascii")
        ).hexdigest(),
        "score_json": json.dumps(score, sort_keys=True),
        "lane_id": lane_id,
        "lane_version": int(checkpoint.get("lane_version", 0)),
        "checkpoint_ref": str(checkpoint["checkpoint_id"]),
        "checkpoint_id": str(checkpoint["checkpoint_id"]),
        "created_at": datetime.fromtimestamp(
            modified_ns / 1_000_000_000, tz=UTC
        ).isoformat().replace("+00:00", "Z"),
        "published_at": datetime.fromtimestamp(
            modified_ns / 1_000_000_000, tz=UTC
        ).isoformat().replace("+00:00", "Z"),
        "state": "live_frontier",
        "certification_status": None,
        "candidate_snapshot_id": None,
        "high_water": int(checkpoint.get("high_water", 0)),
        "transient": True,
    }


def _score_ordering_key(score: dict[str, Any]) -> tuple[Any, ...]:
    ordering = score.get("ordering_key")
    if isinstance(ordering, list) and ordering:
        return tuple(
            value if isinstance(value, (int, float)) else float("inf")
            for value in ordering
        )
    penalty = score.get("weighted_penalty")
    return (
        float(penalty)
        if isinstance(penalty, (int, float)) and not isinstance(penalty, bool)
        else float("inf"),
    )


def _timestamp_key(value: str) -> int:
    return int.from_bytes(value.encode("utf-8"), "big")


@lru_cache(maxsize=64)
def _bounded_cycle_examples(
    graph6: str, target: str
) -> tuple[tuple[tuple[str, Any], ...], ...]:
    graph = BitGraph.from_graph6(graph6)
    plugin = TARGETS[target]
    results = []
    for length in plugin.forbidden_lengths(graph.n):
        found, complete = find_cycles_of_length_bounded(
            graph,
            length,
            1,
            VISUALIZATION_CYCLE_NODE_BUDGET,
        )
        if found:
            status = "bounded_example"
            vertices: list[int] | None = list(found[0])
        elif complete:
            status = "no_example_in_complete_display_scan"
            vertices = None
        else:
            status = "not_found_within_visualization_budget"
            vertices = None
        results.append(
            tuple(
                {
                    "length": length,
                    "vertices": vertices,
                    "status": status,
                    "search_complete": complete,
                    "authority": "heuristic_display_scan",
                }.items()
            )
        )
    return tuple(results)


def _exact_verification(
    connection: sqlite3.Connection,
    *,
    campaign_root: Path,
    campaign_id: str,
    candidate_id: str,
    graph: BitGraph,
    graph6: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT verification_job_id, state, certification_status,
               certification_artifact_ref
        FROM campaign_verification_jobs
        WHERE campaign_id=? AND candidate_id=?
          AND certification_artifact_ref IS NOT NULL
        ORDER BY completed_at DESC, created_at DESC, rowid DESC LIMIT 1
        """,
        (campaign_id, candidate_id),
    ).fetchone()
    if row is None:
        return None
    result: dict[str, Any] = {
        "verification_job_id": str(row["verification_job_id"]),
        "state": str(row["state"]),
        "status": row["certification_status"],
        "integrity_status": "unavailable",
        "witnesses": [],
    }
    try:
        manifest = _read_manifest(
            campaign_root, str(row["certification_artifact_ref"])
        )
    except (OSError, ValueError, json.JSONDecodeError):
        return result
    expected_hash = hashlib.sha256(
        (graph6 + "\n").encode("ascii")
    ).hexdigest()
    if manifest.get("graph6_sha256") != expected_hash:
        result["integrity_status"] = "graph_hash_mismatch"
        return result
    witnesses = []
    for verifier in manifest.get("verifiers", []):
        if not isinstance(verifier, dict):
            continue
        implementation = str(
            verifier.get("implementation") or "unidentified_verifier"
        )
        payloads: list[tuple[int | None, Any]] = []
        if isinstance(verifier.get("witnesses"), list):
            for witness in verifier["witnesses"]:
                if isinstance(witness, dict):
                    kind = str(witness.get("kind") or "")
                    length = (
                        int(kind.removeprefix("cycle_"))
                        if kind.removeprefix("cycle_").isdigit()
                        else None
                    )
                    payloads.append((length, witness.get("vertices")))
        if "witness" in verifier:
            payloads.append((verifier.get("length"), verifier.get("witness")))
        for length, vertices in payloads:
            normalized = _valid_cycle(graph, length, vertices)
            if normalized is not None:
                witnesses.append(
                    {
                        "implementation": implementation,
                        "length": len(normalized),
                        "vertices": normalized,
                        "authority": "persisted_M4_manifest",
                    }
                )
    result["integrity_status"] = "verified"
    result["witnesses"] = witnesses
    result["manifest_status"] = manifest.get("status")
    return result


def _read_manifest(root: Path, reference: str) -> dict[str, Any]:
    relative = Path(reference)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("invalid verification artifact reference")
    resolved_root = root.resolve()
    candidate = resolved_root / relative
    if candidate.is_symlink():
        raise ValueError("verification artifact is unavailable")
    path = candidate.resolve()
    if resolved_root not in path.parents or not path.is_file():
        raise ValueError("verification artifact is unavailable")
    if path.stat().st_size > VISUALIZATION_MANIFEST_LIMIT_BYTES:
        raise ValueError("verification artifact exceeds display limit")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("verification manifest must be an object")
    return value


def _valid_cycle(
    graph: BitGraph, length: Any, vertices: Any
) -> list[int] | None:
    if (
        isinstance(length, bool)
        or not isinstance(length, int)
        or not isinstance(vertices, list)
        or len(vertices) != length
        or len(set(vertices)) != length
        or any(
            isinstance(vertex, bool)
            or not isinstance(vertex, int)
            or not 0 <= vertex < graph.n
            for vertex in vertices
        )
    ):
        return None
    if any(
        not graph.has_edge(
            vertices[index], vertices[(index + 1) % len(vertices)]
        )
        for index in range(len(vertices))
    ):
        return None
    return list(vertices)


def _json_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
