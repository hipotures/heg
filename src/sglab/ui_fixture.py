from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from shutil import rmtree
from time import monotonic
from typing import Any
import json
import sqlite3

from .comparisons import import_m6_context_report
from .db import SCHEMA_VERSION, connect
from .locations import source_root
from .state import atomic_write_json


FIXTURE_VERSION = 1
DEFAULT_UI_FIXTURE_SEED = 20260725
FIXED_TIME = "2026-07-25T12:00:00Z"
DEMO_MARKER = {
    "workspace_kind": "ui_demo",
    "synthetic_data": True,
    "fixture_version": FIXTURE_VERSION,
    "generated_by": "deterministic_fixture",
}
CAMPAIGN_ID = "campaign-demo-running"


@dataclass(frozen=True, slots=True)
class UIFixtureResult:
    workspace: Path
    fixture_sha256: str
    database_bytes: int
    generation_seconds: float
    counts: dict[str, int]
    schema_version: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "workspace": str(self.workspace),
            "workspace_kind": "ui_demo",
            "synthetic_data": True,
            "fixture_version": FIXTURE_VERSION,
            "fixture_sha256": self.fixture_sha256,
            "database_bytes": self.database_bytes,
            "generation_seconds": self.generation_seconds,
            "counts": self.counts,
            "sqlite_schema_version": self.schema_version,
            "model_inferences": 0,
            "auth_accesses": 0,
            "external_network_requests": 0,
            "production_search_batches": 0,
        }


def create_ui_fixture(
    workspace: Path,
    *,
    profile: str = "full",
    replace: bool = False,
    seed: int = DEFAULT_UI_FIXTURE_SEED,
) -> UIFixtureResult:
    if profile != "full":
        raise ValueError("only the full UI fixture profile is supported")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**63:
        raise ValueError("seed must be a bounded non-negative integer")
    target = workspace.expanduser().resolve()
    _prepare_target(target, replace=replace)
    started = monotonic()
    target.mkdir(parents=True)
    atomic_write_json(
        target / "workspace.json",
        {
            **DEMO_MARKER,
            "profile": profile,
            "seed": seed,
            "generated_at": FIXED_TIME,
        },
    )
    database = target / "results.sqlite3"
    connection = connect(database)
    try:
        _populate_legacy_dashboard(connection, target, seed)
        _populate_campaigns(connection, target, seed)
        connection.commit()
        _populate_comparisons(connection, seed)
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        counts = _required_counts(connection)
        schema_version = int(
            connection.execute("PRAGMA user_version").fetchone()[0]
        )
        integrity = str(
            connection.execute("PRAGMA integrity_check").fetchone()[0]
        )
        if schema_version != SCHEMA_VERSION or integrity != "ok":
            raise RuntimeError("generated UI fixture failed SQLite validation")
        fixture_sha256 = _logical_workspace_sha256(connection, target)
    finally:
        connection.close()
    marker = {
        **DEMO_MARKER,
        "profile": profile,
        "seed": seed,
        "generated_at": FIXED_TIME,
        "fixture_sha256": fixture_sha256,
        "counts": counts,
        "sqlite_schema_version": schema_version,
    }
    atomic_write_json(target / "workspace.json", marker)
    atomic_write_json(
        target / "fixture-summary.json",
        {
            **marker,
            "database_file": "results.sqlite3",
            "contains_real_credentials": False,
            "contains_private_runtime_paths": False,
            "model_inferences": 0,
            "auth_accesses": 0,
            "production_search_batches": 0,
        },
    )
    return UIFixtureResult(
        workspace=target,
        fixture_sha256=fixture_sha256,
        database_bytes=database.stat().st_size,
        generation_seconds=monotonic() - started,
        counts=counts,
        schema_version=schema_version,
    )


def inspect_ui_fixture(workspace: Path) -> dict[str, Any]:
    target = workspace.expanduser().resolve()
    marker = _read_json(target / "workspace.json")
    if not _is_demo_marker(marker):
        raise ValueError("workspace is not an explicit synthetic UI demo")
    connection = connect(target / "results.sqlite3")
    try:
        return {
            "marker": marker,
            "counts": _required_counts(connection),
            "fixture_sha256": _logical_workspace_sha256(connection, target),
            "integrity_check": connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0],
            "foreign_key_check": connection.execute(
                "PRAGMA foreign_key_check"
            ).fetchall(),
            "schema_version": connection.execute(
                "PRAGMA user_version"
            ).fetchone()[0],
        }
    finally:
        connection.close()


def _prepare_target(target: Path, *, replace: bool) -> None:
    if target in {Path("/"), Path.home().resolve()}:
        raise ValueError("refusing a broad UI fixture workspace")
    if not target.exists():
        return
    if not target.is_dir():
        raise ValueError("UI fixture workspace must be a directory")
    marker = _read_json(target / "workspace.json", default={})
    if not _is_demo_marker(marker):
        raise ValueError("refusing to replace a workspace without the UI demo marker")
    if not replace:
        raise ValueError("UI demo workspace already exists; pass --replace")
    rmtree(target)


def _is_demo_marker(value: Any) -> bool:
    return isinstance(value, dict) and all(
        value.get(key) == expected for key, expected in DEMO_MARKER.items()
    )


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(label: str, seed: int) -> str:
    return sha256(f"{seed}:{label}".encode("ascii")).hexdigest()


def _time(index: int) -> str:
    hour = 8 + (index // 60)
    minute = index % 60
    return f"2026-07-25T{hour:02d}:{minute:02d}:00Z"


def _populate_legacy_dashboard(
    connection: sqlite3.Connection,
    workspace: Path,
    seed: int,
) -> None:
    run_states = (
        ("run-demo-current", "RUNNING"),
        ("run-demo-completed", "COMPLETED"),
        ("run-demo-paused", "PAUSED"),
        ("run-demo-stopped", "STOPPED"),
        ("run-demo-failed", "FAILED"),
        ("run-demo-empty", "CREATED"),
        ("run-demo-timeout", "TIMED_OUT"),
        ("run-demo-verifier-disagreement", "FAILED"),
    )
    for index, (run_id, status) in enumerate(run_states):
        parameters = {
            "order": 20 + 2 * (index % 2),
            "algorithm": (
                "iterated_local_search_tabu"
                if index % 3 == 0
                else "simulated_annealing"
                if index % 3 == 1
                else "random_restart"
            ),
            "mode": "cubic_first",
            "seed": seed + index,
            "synthetic_data": True,
        }
        connection.execute(
            """
            INSERT INTO runs
            (run_id, created_at, target, status, parameters_json, environment_json)
            VALUES (?, ?, 'erdos_gyarfas', ?, ?, ?)
            """,
            (
                run_id,
                _time(index),
                status,
                _json(parameters),
                _json({"fixture": "ui_demo", "external_network": False}),
            ),
        )
        for window in range(12 if index == 0 else 4):
            connection.execute(
                "INSERT INTO run_metrics VALUES (?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    _time(20 + index * 12 + window),
                    window * 500,
                    max(0, 6 - window // 2),
                    float(250 + index * 77 + window * 31),
                    90_000_000 + index * 12_000_000 + window * 900_000,
                ),
            )

    best_dir = workspace / "best"
    best_dir.mkdir()
    artifact_id = 1
    for index in range(40):
        compact = index % 5 == 0
        candidate_id = (
            f"cand-{index:03d}"
            if compact
            else f"candidate-{_digest(f'candidate-{index}', seed)[:48]}"
        )
        artifact_stem = _digest(f"artifact-{index}", seed)[:20]
        witness = {
            "4": index % 4,
            "8": (index * 3) % 6,
            "16": (index * 5) % 5,
        }
        weighted = witness["4"] * 16 + witness["8"] * 8 + witness["16"] * 4
        verifier_statuses = (
            "pending",
            "rejected_cycle_4",
            "rejected_cycle_8",
            "rejected_cycle_16",
            "SYNTHETIC_DEMO_EXACT_PASS",
            "timeout_unknown",
            "verifier_disagreement",
        )
        verifier_status = verifier_statuses[index % len(verifier_statuses)]
        graph6 = f"DEMO_GRAPH6_{index:03d}"
        score = {
            "ordering_key": [weighted, sum(witness.values()), -index],
            "witness_counts": witness,
            "weighted_penalty": weighted,
            "novelty": round(0.2 + (index % 8) * 0.09, 3),
            "simplicity": 20 + index % 3,
        }
        connection.execute(
            """
            INSERT INTO candidates
            (candidate_id, run_id, graph6, order_n, size_m, score_json,
             verification_status, created_at)
            VALUES (?, 'run-demo-current', ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                graph6,
                20 + 2 * (index % 2),
                30 + 3 * (index % 2),
                _json(score),
                verifier_status,
                _time(160 + index),
            ),
        )
        for component, value in (
            ("weighted_penalty", weighted),
            ("novelty", score["novelty"]),
            ("cycle_4", witness["4"]),
            ("cycle_8", witness["8"]),
            ("cycle_16", witness["16"]),
        ):
            connection.execute(
                "INSERT INTO candidate_scores VALUES (?, ?, ?)",
                (candidate_id, component, float(value)),
            )
        downloadable = index % 4 != 3
        artifacts: dict[str, str] = {}
        record = {
            "candidate_id": candidate_id,
            "synthetic_data": True,
            "order": 20 + 2 * (index % 2),
            "size": 30 + 3 * (index % 2),
            "graph6": graph6,
            "degree_histogram": {"3": 20 + 2 * (index % 2)},
            "score": score,
            "verification_status": verifier_status,
            "ancestry_summary": [
                {
                    "parent_candidate_id": (
                        None
                        if step == 0
                        else f"candidate-parent-{index:02d}-{step:02d}"
                    ),
                    "mutation_operator": (
                        "uniform_two_edge_switch"
                        if step % 2 == 0
                        else "forbidden_cycle_break_switch"
                    ),
                    "score_before": weighted + step + 1,
                    "score_after": weighted + step,
                    "evaluation": 1000 + index * 100 + step,
                }
                for step in range(min(8, 2 + index % 7))
            ],
            "artifacts": artifacts,
        }
        json_name = f"{artifact_stem}.json"
        if downloadable:
            graph_name = f"{artifact_stem}.graph6"
            svg_name = f"{artifact_stem}.svg"
            artifacts.update({"json": json_name, "graph6": graph_name, "svg": svg_name})
            (best_dir / graph_name).write_text(graph6 + "\n", encoding="ascii")
            (best_dir / svg_name).write_text(
                (
                    '<svg xmlns="http://www.w3.org/2000/svg" width="240" '
                    'height="120"><rect width="240" height="120" fill="#10202e"/>'
                    f'<text x="12" y="64" fill="#dce8f3">Synthetic {index:02d}</text>'
                    "</svg>"
                ),
                encoding="utf-8",
            )
            for kind, relative in (
                ("candidate_json", f"best/{json_name}"),
                ("graph6", f"best/{graph_name}"),
                ("svg", f"best/{svg_name}"),
            ):
                connection.execute(
                    """
                    INSERT INTO artifacts
                    (artifact_id, run_id, candidate_id, kind, path, sha256)
                    VALUES (?, 'run-demo-current', ?, ?, ?, ?)
                    """,
                    (
                        artifact_id,
                        candidate_id,
                        kind,
                        relative,
                        _digest(f"{kind}-{index}", seed),
                    ),
                )
                artifact_id += 1
        (best_dir / json_name).write_text(_json(record) + "\n", encoding="ascii")
        connection.execute(
            """
            INSERT INTO verifications
            (candidate_id, verifier, status, complete, elapsed_seconds, report_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                "synthetic_reference_verifier",
                verifier_status,
                int(verifier_status not in {"pending", "timeout_unknown"}),
                round(0.05 + index * 0.013, 3),
                _json(
                    {
                        "synthetic_data": True,
                        "cycle_profile": witness,
                        "claim": "demo_only",
                    }
                ),
            ),
        )

    root_run = {
        "run_id": "run-demo-current",
        "created_at": FIXED_TIME,
        "target": "erdos_gyarfas",
        "parameters": {
            "order": 20,
            "algorithm": "iterated_local_search_tabu",
            "seed": seed,
        },
        "synthetic_data": True,
    }
    atomic_write_json(workspace / "run.json", root_run)
    atomic_write_json(
        workspace / "state.json",
        {
            "status": "RUNNING_DEMO",
            "run_id": "run-demo-current",
            "target": "erdos_gyarfas",
            "updated_at": FIXED_TIME,
            "synthetic_data": True,
            "configuration": root_run["parameters"],
            "elapsed_seconds": 87.5,
            "remaining_seconds": 32.5,
            "throughput": {"candidates": 10000, "candidates_per_second": 8117.4},
            "workers": {"configured": 4, "alive": 3, "failed": 1, "restarts": 2},
            "resources": {
                "aggregate_rss_bytes": 734_003_200,
                "master_rss_bytes": 125_829_120,
                "worker_rss_bytes": 608_174_080,
                "load_average": [3.2, 2.8, 2.4],
                "disk_free_bytes": 81_604_714_496,
                "database_bytes": 0,
            },
            "exact_verification": {"queued": 3, "verified_candidates": 7},
            "best": {"score": {"ordering_key": [3, 3, -39]}},
        },
    )
    runs_dir = workspace / "runs"
    runs_dir.mkdir()
    for index, (run_id, status) in enumerate(run_states):
        run_dir = runs_dir / run_id
        run_dir.mkdir()
        parameters = {
            "order": 20 + 2 * (index % 2),
            "algorithm": (
                "iterated_local_search_tabu"
                if index % 3 == 0
                else "simulated_annealing"
                if index % 3 == 1
                else "random_restart"
            ),
        }
        atomic_write_json(
            run_dir / "run.json",
            {
                "run_id": run_id,
                "created_at": _time(index),
                "target": "erdos_gyarfas",
                "parameters": parameters,
                "synthetic_data": True,
            },
        )
        atomic_write_json(
            run_dir / "state.json",
            {
                "status": status,
                "elapsed_seconds": index * 33.5,
                "throughput": {
                    "candidates": index * 1750,
                    "candidates_per_second": 0 if index == 5 else 350 + index * 110,
                },
                "best": {"score": {"ordering_key": [max(0, 12 - index), index]}},
            },
        )
    event_kinds = (
        ("info", "Campaign coordinator started synthetic review data."),
        ("decision", "Director decision committed before synthetic evaluation."),
        ("warning", "Witness counting reached 94% of measured stage time."),
        ("resource_pressure", "Synthetic RSS crossed the soft memory threshold."),
        ("timeout", "Exact verifier timed out; result remains UNKNOWN."),
        ("error", "Synthetic worker exited unexpectedly and was not retried."),
        ("lease", "Comparison worker lease heartbeat refreshed."),
        ("authorization", "Synthetic exact plan authorization recorded."),
        ("shutdown", "Synthetic App Server completed graceful shutdown."),
    )
    with (workspace / "events.jsonl").open("w", encoding="utf-8") as handle:
        for index in range(36):
            kind, message = event_kinds[index % len(event_kinds)]
            handle.write(
                _json(
                    {
                        "timestamp": _time(220 + index),
                        "level": (
                            "error"
                            if kind == "error"
                            else "warning"
                            if kind in {"warning", "timeout", "resource_pressure"}
                            else "info"
                        ),
                        "kind": kind,
                        "message": message,
                        "synthetic_data": True,
                    }
                )
                + "\n"
            )


def _populate_campaigns(
    connection: sqlite3.Connection,
    workspace: Path,
    seed: int,
) -> None:
    campaigns = (
        ("campaign-demo-completed", "completed_deadline_reached", None, None),
        (CAMPAIGN_ID, "running", None, None),
        ("campaign-demo-paused", "paused_by_operator", None, None),
        ("campaign-demo-stopped", "stopped_by_operator", None, None),
        ("campaign-demo-failed", "paused_fault", "worker_crash", "Synthetic worker crash."),
        ("campaign-demo-empty", "created", None, None),
        ("campaign-demo-timeout", "paused_fault", "turn_timeout", "No final answer."),
        (
            "campaign-demo-verifier-disagreement",
            "paused_fault",
            "verifier_disagreement",
            "Synthetic exact paths disagree; no claim is made.",
        ),
    )
    for index, (campaign_id, state, fault_kind, fault_detail) in enumerate(campaigns):
        connection.execute(
            """
            INSERT INTO research_campaigns
            (campaign_id, created_at, updated_at, target,
             target_definition_sha256, state, state_version, stop_mode,
             deadline_at, fault_kind, fault_detail, effective_context_mode,
             context_recommendation_basis)
            VALUES (?, ?, ?, 'erdos_gyarfas', ?, ?, ?, 'time_limit', ?, ?, ?,
                    ?, 'single controlled S2/P2 pair')
            """,
            (
                campaign_id,
                _time(index),
                _time(60 + index),
                _digest("target-definition", seed),
                state,
                index,
                "2026-07-25T18:00:00Z",
                fault_kind,
                fault_detail,
                "stateless_turns" if index % 2 else "persistent_thread",
            ),
        )

    lane_states = (
        "running",
        "completed",
        "paused",
        "stopped",
        "failed",
        "blocked",
        "starting",
        "stopping",
        "running",
        "running",
        "running",
        "completed",
    )
    algorithms = (
        "iterated_local_search_tabu",
        "simulated_annealing",
        "random_restart",
    )
    lane_ids: list[str] = []
    for index, lane_state in enumerate(lane_states):
        lane_id = (
            f"lane-{index:02d}"
            if index % 4 == 0
            else f"lane-{_digest(f'lane-{index}', seed)[:36]}"
        )
        lane_ids.append(lane_id)
        params = {
            "order": 20 + 2 * (index % 2),
            "batch_candidates": 300 + index * 50,
            "witness_cap": 64 if index % 2 else 10000,
            "mutation_weights": {
                "uniform_two_edge_switch": round(0.2 + (index % 5) * 0.15, 2),
                "forbidden_cycle_break_switch": round(
                    0.8 - (index % 5) * 0.15, 2
                ),
            },
        }
        if algorithms[index % 3] == "iterated_local_search_tabu":
            params.update({"tabu_tenure": 48 + index, "perturbation_interval": 200})
        elif algorithms[index % 3] == "simulated_annealing":
            params.update({"temperature": 3.0, "cooling": 0.995})
        connection.execute(
            """
            INSERT INTO research_lanes
            (lane_id, campaign_id, target, parent_lane_id, parent_checkpoint_ref,
             created_by_action_id, state, lane_version, algorithm, graph_family,
             current_parameters_json, seed_lineage_json, checkpoint_ref,
             checkpoint_sha256, telemetry_high_water, resource_share,
             lease_expires_at, process_generation, created_at, updated_at,
             stopped_at)
            VALUES (?, ?, 'erdos_gyarfas', NULL, NULL, NULL, ?, ?, ?,
                    'connected_cubic', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                lane_id,
                CAMPAIGN_ID,
                lane_state,
                index,
                algorithms[index % 3],
                _json(params),
                _json({"seed": seed + index, "synthetic_data": True}),
                f"checkpoints/lane-{index:02d}.json",
                _digest(f"checkpoint-{index}", seed),
                0 if index == 6 else (index + 1) * 1200,
                round(0.04 + index * 0.005, 3),
                "2026-07-25T14:00:00Z" if lane_state in {"running", "starting"} else None,
                index % 3,
                _time(70 + index),
                _time(100 + index),
                _time(150 + index) if lane_state in {"stopped", "completed"} else None,
            ),
        )
        if index != 6:
            for window in range(10):
                end_high = (window + 1) * (100 + index * 10)
                metrics = {
                    "end_high_water": end_high,
                    "candidates_per_second": (
                        75 + window * 3
                        if index == 9
                        else 9400 - index * 430 + window * 17
                    ),
                    "best_scalar": max(2, 18 - window - index // 3),
                    "best_score": {
                        "witness_counts": {
                            "4": max(0, 5 - window // 2),
                            "8": max(0, 7 - window // 3),
                            "16": max(0, 4 - window // 4),
                        }
                    },
                    "accepted_mutations": 20 + window * 3,
                    "duplicate_rate": min(0.95, 0.05 + index * 0.025 + window * 0.01),
                    "diversity": max(0.04, 0.9 - index * 0.045 - window * 0.012),
                    "rss_bytes": 80_000_000 + index * 28_000_000 + window * 1_000_000,
                    "operator_yield": max(0.01, 0.32 - index * 0.012),
                    "operator_uses": {
                        "uniform_two_edge_switch": 50 + window * 5,
                        "forbidden_cycle_break_switch": 40 + window * 4,
                    },
                    "token_usage": 900 + window * 50,
                    "model_latency_seconds": round(1.4 + index * 0.2, 2),
                    "synthetic_data": True,
                }
                connection.execute(
                    """
                    INSERT INTO lane_metric_windows
                    (metric_window_id, lane_id, campaign_id, lane_version,
                     start_high_water, end_high_water, start_at, end_at,
                     metrics_json, artifact_ref, artifact_sha256)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"metric-{index:02d}-{window:02d}",
                        lane_id,
                        CAMPAIGN_ID,
                        index,
                        window * (100 + index * 10),
                        end_high,
                        _time(260 + index * 10 + window),
                        _time(261 + index * 10 + window),
                        _json(metrics),
                        f"metrics/lane-{index:02d}-{window:02d}.json",
                        _digest(f"metric-{index}-{window}", seed),
                    ),
                )
        if index < 8:
            connection.execute(
                """
                INSERT INTO lane_revisions
                (lane_revision_id, lane_id, campaign_id, action_id,
                 old_lane_version, new_lane_version, old_parameters_json,
                 new_parameters_json, applied_checkpoint_ref,
                 applied_checkpoint_sha256, applied_at)
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"revision-{index:02d}",
                    lane_id,
                    CAMPAIGN_ID,
                    index,
                    index + 1,
                    _json({"witness_cap": 64, "temperature": None}),
                    _json({"witness_cap": 10000, "temperature": 3.0}),
                    f"checkpoints/revision-{index:02d}.json",
                    _digest(f"revision-{index}", seed),
                    _time(380 + index),
                ),
            )

    session_id = "session-demo-director"
    thread_id = "thread-demo-persistent-history-20260725"
    connection.execute(
        """
        INSERT INTO app_server_sessions
        (session_record_id, campaign_id, thread_id, app_server_session_id,
         thread_path, parent_thread_id, model_requested, effort_requested,
         codex_version, codex_executable_sha256, protocol_schema_sha256,
         state, started_at, last_resumed_at, closed_at, context_mode)
        VALUES (?, ?, ?, 'synthetic-session', NULL, NULL, 'gpt-5.6-luna',
                'xhigh', '0.145.0-demo', ?, ?, 'running', ?, ?, NULL,
                'stateless_turns')
        """,
        (
            session_id,
            CAMPAIGN_ID,
            thread_id,
            _digest("codex-executable", seed),
            _digest("protocol-schema", seed),
            _time(400),
            _time(410),
        ),
    )
    turn_shapes = (
        ("completed", "completed", True, True),
        ("completed_invalid", "completed", True, False),
        ("completed_invalid", "completed", False, None),
        ("failed", "timed_out", None, None),
        ("failed_interrupted", "aborted", None, None),
        ("completed", "completed", True, True),
        ("failed", "failed", None, None),
        ("completed", "completed", True, True),
        ("in_progress", "in_progress", None, None),
        ("completed", "completed", True, True),
        ("completed", "completed", True, True),
        ("failed", "failed", None, None),
    )
    turn_ids: list[str] = []
    for index, (status, lifecycle, _schema, _semantic) in enumerate(turn_shapes):
        snapshot_id = f"snapshot-demo-{index:02d}"
        trigger_id = f"trigger-demo-{index:02d}"
        turn_record_id = f"turn-record-demo-{index:02d}"
        turn_ids.append(turn_record_id)
        connection.execute(
            """
            INSERT INTO director_snapshots
            (snapshot_id, campaign_id, campaign_state_version, high_water_json,
             artifact_ref, artifact_sha256, payload_bytes, created_at)
            VALUES (?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                CAMPAIGN_ID,
                _json({"evaluations": index * 1000, "synthetic_data": True}),
                f"audit/snapshot-{index:02d}.json",
                _digest(f"snapshot-{index}", seed),
                2400 + index * 120,
                _time(420 + index),
            ),
        )
        connection.execute(
            """
            INSERT INTO director_triggers
            (trigger_id, campaign_id, campaign_state_version, reason_set_json,
             first_event_at, coalesced_at, snapshot_id, status)
            VALUES (?, ?, 1, ?, ?, ?, ?, 'completed')
            """,
            (
                trigger_id,
                CAMPAIGN_ID,
                _json(["periodic_review", "synthetic_fixture"]),
                _time(420 + index),
                _time(421 + index),
                snapshot_id,
            ),
        )
        has_usage = index not in {3, 4, 5, 8, 11}
        error_kind = (
            "synthetic_prohibited_tool_attempt"
            if index == 11
            else "schema_invalid"
            if index == 2
            else "semantic_invalid"
            if index == 1
            else "turn_timeout"
            if index == 3
            else "interrupted"
            if index == 4
            else None
        )
        connection.execute(
            """
            INSERT INTO app_server_turns
            (turn_record_id, session_record_id, campaign_id, thread_id, turn_id,
             snapshot_id, trigger_id, status, request_artifact_ref,
             request_sha256, response_artifact_ref, response_sha256,
             wire_log_artifact_ref, wire_log_sha256, input_tokens,
             cached_input_tokens, cache_write_input_tokens, output_tokens,
             reasoning_output_tokens, total_tokens, raw_usage_json,
             wall_seconds, error_kind, error_detail, started_at, completed_at,
             final_agent_item_id, lifecycle_status, request_id, item_ids_json,
             item_types_json, reasoning_item_ids_json, latest_event_sequence,
             latest_event_at, turn_started_at, terminal_reason,
             evidence_registry_artifact_ref, evidence_registry_sha256,
             thread_lifecycle)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                turn_record_id,
                session_id,
                CAMPAIGN_ID,
                thread_id,
                f"turn-demo-{index:02d}",
                snapshot_id,
                trigger_id,
                status,
                f"audit/request-{index:02d}.json",
                _digest(f"request-{index}", seed),
                None if lifecycle in {"timed_out", "aborted", "in_progress"} else f"audit/response-{index:02d}.json",
                None if lifecycle in {"timed_out", "aborted", "in_progress"} else _digest(f"response-{index}", seed),
                f"wire/turn-{index:02d}.jsonl",
                _digest(f"wire-{index}", seed),
                2000 + index * 120 if has_usage else None,
                600 + index * 30 if has_usage else None,
                100 + index * 5 if has_usage else None,
                500 + index * 50 if has_usage else None,
                300 + index * 25 if has_usage else None,
                2500 + index * 170 if has_usage else None,
                _json({"synthetic_data": True}) if has_usage else None,
                1.2 + index * 0.7,
                error_kind,
                (
                    "Synthetic record only; no tool was invoked."
                    if index == 11
                    else "Synthetic structured response did not match the schema."
                    if index == 2
                    else "Synthetic response failed the local semantic contract."
                    if index == 1
                    else "Synthetic timeout with reasoning items preserved."
                    if index == 3
                    else None
                ),
                _time(440 + index),
                None if lifecycle in {"timed_out", "aborted", "in_progress"} else _time(441 + index),
                None if lifecycle in {"timed_out", "aborted", "in_progress"} else f"item-final-{index:02d}",
                lifecycle,
                f"request-demo-{index:02d}",
                _json([f"reasoning-{index:02d}-a", f"reasoning-{index:02d}-b"]),
                _json(
                    {
                        f"reasoning-{index:02d}-a": "reasoning",
                        f"reasoning-{index:02d}-b": "reasoning",
                    }
                ),
                _json([f"reasoning-{index:02d}-a", f"reasoning-{index:02d}-b"]),
                8 + index,
                _time(441 + index),
                _time(440 + index),
                error_kind,
                f"audit/evidence-{index:02d}.json",
                _digest(f"evidence-{index}", seed),
                "fresh" if index % 2 == 0 else "resumed",
            ),
        )

    action_types = (
        "start_lane",
        "request_diagnostic",
        "set_review_trigger",
        "promote_candidate",
        "schedule_verification",
        "stop_lane",
        "patch_lane",
        "restart_lane",
        "fork_lane",
        "reallocate_resources",
    )
    outcome_statuses = (
        "applied",
        "applied",
        "rejected",
        "blocked",
        "measurement_only",
        "applied",
        "applied",
        "failed",
    )
    for batch_index in range(12):
        batch_id = f"decision-batch-demo-{batch_index:02d}"
        connection.execute(
            """
            INSERT INTO director_action_batches
            (decision_batch_id, campaign_id, snapshot_id, trigger_id,
             turn_record_id, campaign_assessment, next_review_json,
             validation_status, response_artifact_ref, response_sha256,
             created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                CAMPAIGN_ID,
                f"snapshot-demo-{batch_index:02d}",
                f"trigger-demo-{batch_index:02d}",
                turn_ids[batch_index],
                (
                    "The synthetic portfolio is improving slowly."
                    if batch_index % 3
                    else "The synthetic plateau warrants a measured strategy change."
                ),
                _json({"after_evaluations": 1000 + batch_index * 500}),
                "accepted" if batch_index not in {2, 7} else "rejected",
                f"audit/decision-{batch_index:02d}.json",
                _digest(f"decision-{batch_index}", seed),
                _time(470 + batch_index),
            ),
        )
        for offset in range(2):
            action_index = batch_index * 2 + offset
            action_type = action_types[action_index % len(action_types)]
            action_id = f"action-demo-{action_index:02d}"
            lane_id = lane_ids[action_index % len(lane_ids)]
            parameters = _action_parameters(
                action_type, action_index, lane_id, seed
            )
            rationale = (
                "Test whether targeted forbidden-cycle breaking improves the score "
                "without collapsing diversity."
                if action_index % 5
                else (
                    "This intentionally long synthetic rationale exercises wrapping, "
                    "line clamping, expansion controls, and semantic grouping. "
                    * 8
                ).strip()
            )
            validation_status = (
                "accepted"
                if action_index % 7 not in {2, 5}
                else "rejected"
                if action_index % 7 == 2
                else "blocked"
            )
            connection.execute(
                """
                INSERT INTO director_actions
                (action_id, decision_batch_id, campaign_id, action_type,
                 priority, target_lane_id, expected_lane_version,
                 hypothesis_ids_json, evidence_ids_json, parameters_json,
                 rationale, expected_effect, evaluation_window_json,
                 fallback_json, idempotency_key, lease_expires_at,
                 validation_status, validation_detail, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action_id,
                    batch_id,
                    CAMPAIGN_ID,
                    action_type,
                    50 + action_index % 50,
                    lane_id if action_type in {"stop_lane", "patch_lane", "restart_lane", "fork_lane"} else None,
                    action_index % 12 if action_type in {"stop_lane", "patch_lane", "restart_lane", "fork_lane"} else None,
                    _json([f"hypothesis-demo-{action_index % 10:02d}"]),
                    _json([f"snapshot-demo-{batch_index:02d}", lane_id]),
                    _json(parameters),
                    rationale,
                    (
                        "Improve weighted score while retaining at least 0.25 diversity."
                    ),
                    _json({"evaluations": 1000, "seconds": 20}),
                    _json({"type": "request_diagnostic"}),
                    f"demo-idempotency-{action_index:02d}",
                    "2026-07-25T18:00:00Z",
                    validation_status,
                    None if validation_status == "accepted" else "Synthetic review state.",
                    _time(500 + action_index),
                ),
            )
            if action_index % 6 != 5:
                effect_kind = action_index % 8
                observed = _observed_effect(effect_kind, action_index)
                connection.execute(
                    """
                    INSERT INTO director_action_outcomes
                    (action_outcome_id, action_id, campaign_id,
                     application_status, resulting_lane_id,
                     resulting_lane_version, pre_window_id, post_window_id,
                     observed_effect_json, expectation_met, failure_kind,
                     failure_detail, applied_at, evaluated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"outcome-demo-{action_index:02d}",
                        action_id,
                        CAMPAIGN_ID,
                        outcome_statuses[effect_kind],
                        lane_id if validation_status == "accepted" else None,
                        action_index % 12 + 1 if validation_status == "accepted" else None,
                        f"metric-{action_index % 12:02d}-00"
                        if action_index % 12 != 6
                        else None,
                        f"metric-{action_index % 12:02d}-01"
                        if action_index % 12 != 6
                        else None,
                        _json(observed),
                        None if effect_kind in {3, 6} else int(effect_kind in {0, 5}),
                        "synthetic_timeout" if effect_kind == 6 else None,
                        "Synthetic UNKNOWN, never UNSAT." if effect_kind == 6 else None,
                        _time(530 + action_index),
                        _time(540 + action_index),
                    ),
                )

    for index in range(12):
        hypothesis_id = f"hypothesis-demo-{index % 10:02d}"
        parent = (
            f"hypothesis-revision-demo-{index - 10:02d}" if index >= 10 else None
        )
        statement = (
            "Targeted switches preserve useful diversity on the score-three plateau."
            if index % 4
            else (
                "A deliberately long synthetic hypothesis explores whether bounded "
                "mutation ancestry and cycle-profile feedback can distinguish a true "
                "local-search barrier from a transient plateau under equal budgets. "
                * 3
            ).strip()
        )
        connection.execute(
            """
            INSERT INTO research_hypotheses_v2
            (hypothesis_revision_id, hypothesis_id, campaign_id,
             parent_revision_id, statement, confidence, status,
             evidence_for_json, evidence_against_json,
             creating_decision_batch_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"hypothesis-revision-demo-{index:02d}",
                hypothesis_id,
                CAMPAIGN_ID,
                parent,
                statement,
                round(0.15 + (index % 9) * 0.09, 2),
                ("rejected" if index % 5 == 0 else "revised" if index >= 10 else "active"),
                _json([f"outcome-demo-{index:02d}"]),
                _json([f"metric-{index % 12:02d}-02"]),
                f"decision-batch-demo-{index % 12:02d}",
                _time(560 + index),
            ),
        )

    for index in range(40):
        candidate_id = (
            f"cand-{index:03d}"
            if index % 5 == 0
            else f"candidate-{_digest(f'candidate-{index}', seed)[:48]}"
        )
        lane_id = lane_ids[index % len(lane_ids)]
        witness = {"4": index % 4, "8": (index * 3) % 6, "16": (index * 5) % 5}
        connection.execute(
            """
            INSERT INTO campaign_candidates
            (candidate_id, campaign_id, lane_id, lane_version, checkpoint_ref,
             graph6, graph_sha256, score_json, state, artifact_ref,
             artifact_sha256, created_at, promoted_at, certification_status,
             certification_artifact_ref)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                CAMPAIGN_ID,
                lane_id,
                index % 12,
                f"checkpoints/candidate-{index:02d}.json",
                f"DEMO_GRAPH6_{index:03d}",
                _digest(f"graph-{index}", seed),
                _json(
                    {
                        "witness_counts": witness,
                        "weighted_penalty": witness["4"] * 16
                        + witness["8"] * 8
                        + witness["16"] * 4,
                    }
                ),
                "promoted" if index % 7 == 0 else "retained",
                f"best/{_digest(f'artifact-{index}', seed)[:20]}.json",
                _digest(f"candidate-artifact-{index}", seed),
                _time(600 + index),
                _time(650 + index) if index % 7 == 0 else None,
                (
                    "SYNTHETIC_DEMO_EXACT_PASS"
                    if index % 13 == 0
                    else "rejected_cycle_4"
                    if index % 4 == 1
                    else "pending"
                ),
                f"verification/candidate-{index:02d}.json" if index % 5 == 0 else None,
            ),
        )
    for index in range(8):
        candidate_id = (
            f"cand-{index * 5:03d}"
            if index * 5 % 5 == 0
            else f"candidate-{_digest(f'candidate-{index * 5}', seed)[:48]}"
        )
        connection.execute(
            """
            INSERT INTO campaign_verification_jobs
            (verification_job_id, campaign_id, candidate_id,
             requested_by_action_id, priority, state,
             certification_artifact_ref, certification_status, created_at,
             started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"verification-job-demo-{index:02d}",
                CAMPAIGN_ID,
                candidate_id,
                f"action-demo-{(index * 3) % 24:02d}",
                70 + index,
                "queued" if index < 2 else "running" if index < 4 else "completed",
                f"verification/job-{index:02d}.json",
                "SYNTHETIC_DEMO_EXACT_PASS" if index == 4 else "REJECTED" if index > 4 else None,
                _time(680 + index),
                _time(690 + index) if index >= 2 else None,
                _time(700 + index) if index >= 4 else None,
            ),
        )
    atomic_write_json(
        workspace / "active-research-campaign.json",
        {
            "campaign_id": CAMPAIGN_ID,
            "synthetic_data": True,
            "state": "running",
            "updated_at": FIXED_TIME,
        },
    )


def _action_parameters(
    action_type: str,
    index: int,
    lane_id: str,
    seed: int,
) -> dict[str, Any]:
    if action_type == "start_lane":
        return {
            "spec": {
                "algorithm": "iterated_local_search_tabu",
                "graph_family": "connected_cubic",
                "parameters": {
                    "order": 20,
                    "batch_candidates": 10000,
                    "witness_cap": 10000,
                    "tabu_tenure": 48,
                    "perturbation_interval": 200,
                    "mutation_weights": {
                        "uniform_two_edge_switch": 0.7,
                        "forbidden_cycle_break_switch": 0.3,
                    },
                },
                "seed": seed + index,
                "resource_share": 0.2,
            }
        }
    if action_type == "request_diagnostic":
        return {
            "diagnostic_type": (
                "mutation_ancestry" if index % 2 else "cycle_length_profile"
            ),
            "subject_ids": [lane_id, f"candidate-subject-{index:02d}"],
        }
    if action_type == "set_review_trigger":
        return {
            "review_trigger": {
                "event": "stagnation",
                "after_evaluations": 1500,
                "minimum_diversity": 0.2,
            }
        }
    if action_type == "promote_candidate":
        return {"candidate_id": f"candidate-subject-{index:02d}"}
    if action_type == "schedule_verification":
        return {
            "candidate_ids": [f"candidate-subject-{index:02d}"],
            "verification_priority": "high",
        }
    if action_type == "stop_lane":
        return {}
    if action_type == "patch_lane":
        return {
            "patch": {
                "witness_cap": 10000,
                "mutation_weights": {
                    "uniform_two_edge_switch": 0.35,
                    "forbidden_cycle_break_switch": 0.65,
                },
            }
        }
    if action_type == "restart_lane":
        return {
            "restart_spec": {
                "source": "recorded_best",
                "candidate_id": f"candidate-subject-{index:02d}",
            }
        }
    if action_type == "fork_lane":
        return {
            "checkpoint_id": f"checkpoint-demo-{index:02d}",
            "variants": [
                {"temperature": 2.0},
                {"temperature": 4.0},
            ],
        }
    return {
        "allocations": [
            {"lane_id": lane_id, "resource_share": 0.4},
            {"lane_id": "lane-00", "resource_share": 0.6},
        ]
    }


def _observed_effect(kind: int, index: int) -> dict[str, Any]:
    common = {
        "evaluations": 1000 + index * 50,
        "elapsed_seconds": round(8.0 + index * 0.4, 2),
        "throughput": round(8100 + (index % 5 - 2) * 420, 1),
        "accepted_mutations": 140 + index,
        "global_records": index % 4,
        "diversity": round(0.22 + (index % 6) * 0.07, 3),
        "operator_yield_change": round((index % 5 - 2) * 0.013, 3),
        "synthetic_data": True,
    }
    variants = (
        {
            "outcome": "score_improvement",
            "initial_score": 8,
            "best_score": 3,
            "exact_verifier_result": "not_requested",
        },
        {
            "outcome": "no_improvement",
            "initial_score": 3,
            "best_score": 3,
            "plateau_evaluations": 1500,
        },
        {
            "outcome": "regression",
            "initial_score": 3,
            "best_score": 5,
        },
        {
            "outcome": "plateau",
            "initial_score": 3,
            "best_score": 3,
            "plateau_evaluations": 6200,
        },
        {
            "outcome": "exact_verifier_rejection",
            "exact_verifier_result": "REJECTED_CYCLE_8",
        },
        {
            "outcome": "synthetic_demo_exact_pass",
            "exact_verifier_result": "SYNTHETIC_DEMO_PASS_NO_CLAIM",
        },
        {
            "outcome": "timeout",
            "exact_verifier_result": "UNKNOWN",
        },
        {
            "outcome": "diagnostic",
            "mutation_ancestry": {
                "retained_records": 8,
                "operators": {
                    "uniform_two_edge_switch": 3,
                    "forbidden_cycle_break_switch": 5,
                },
            },
            "cycle_profile": {"4": 0, "8": 2, "16": 1},
        },
    )
    return {**common, **variants[kind]}


def _populate_comparisons(connection: sqlite3.Connection, seed: int) -> None:
    root = source_root()
    if root is None:
        raise RuntimeError("the full UI fixture requires a source checkout")
    report = root / "docs/reports/M6_REDUCED_CONTEXT_SCREEN_RERUN.json"
    import_m6_context_report(Path(connection.execute("PRAGMA database_list").fetchone()[2]), report)
    _normalize_historical_import(connection)

    hashes = {
        key: _digest(f"ui-fixture-{key}", seed)
        for key in (
            "prompt",
            "output_schema",
            "applicable_action_space",
            "evidence_registry",
            "advisory_registry",
            "executable_registry",
            "base_instructions",
            "developer_instructions",
            "campaign_budget",
        )
    }
    state = {
        "schema_version": "2.0",
        "source_snapshot_id": "snapshot-demo-a4",
        "target_statement_id": "erdos_gyarfas",
        "status_timestamp": FIXED_TIME,
        "measurement_only": True,
        "synthetic_data": True,
        "latest_outcome": {
            "best_score": 3,
            "throughput": 8120.4,
            "exact_verifier_status": "REJECTED_CYCLE_8",
        },
    }
    state_json = _json(state)
    connection.execute(
        """
        INSERT INTO comparison_fixtures
        (fixture_id, display_name, fixture_type, source_artifact_reference,
         fixture_sha256, director_state_schema_version, target_statement_id,
         status_timestamp, serialized_bytes, estimated_client_owned_tokens,
         director_state_json, prompt_sha256, output_schema_sha256,
         applicable_action_space_sha256, evidence_registry_sha256,
         advisory_registry_sha256, executable_registry_sha256,
         base_instructions_sha256, developer_instructions_sha256, personality,
         campaign_budget_sha256, created_at)
        VALUES ('ui-demo-a4', 'Synthetic A4 UI fixture',
                'custom_director_state_json', 'fixture-summary.json', ?, '2.0',
                'erdos_gyarfas', ?, ?, 850, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
        """,
        (
            sha256(state_json.encode("ascii")).hexdigest(),
            FIXED_TIME,
            len(state_json),
            state_json,
            hashes["prompt"],
            hashes["output_schema"],
            hashes["applicable_action_space"],
            hashes["evidence_registry"],
            hashes["advisory_registry"],
            hashes["executable_registry"],
            hashes["base_instructions"],
            hashes["developer_instructions"],
            hashes["campaign_budget"],
            FIXED_TIME,
        ),
    )
    profiles = (
        ("gpt-5.6-luna", "medium", 0.55),
        ("gpt-5.6-luna", "high", 0.75),
        ("gpt-5.6-luna", "xhigh", 1.0),
        ("gpt-5.6-sol", "medium", 0.8),
        ("gpt-5.6-sol", "high", 1.15),
        ("gpt-5.6-sol", "xhigh", 1.5),
    )
    for index, (model, effort, multiplier) in enumerate(profiles):
        connection.execute(
            """
            INSERT INTO model_cost_profiles
            (profile_id, model, reasoning_effort, display_name,
             relative_cost_multiplier, api_input_per_million,
             api_cached_input_per_million, api_output_per_million, currency,
             source_label, effective_from, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'USD', ?, ?, 1, ?)
            """,
            (
                f"ui-cost-{model.removeprefix('gpt-5.6-')}-{effort}",
                model,
                effort,
                f"Synthetic {model} {effort}",
                multiplier,
                1.0 + index * 0.2,
                0.4 + index * 0.1,
                2.0 + index * 0.4,
                "synthetic UI demonstration rates; not pricing",
                FIXED_TIME,
                FIXED_TIME,
            ),
        )

    suites = (
        ("comparison-demo-completed", "Completed quality screen", "completed", 3, 3, None),
        ("comparison-demo-draft", "Draft custom matrix", "draft", 2, 0, None),
        ("comparison-demo-prepared", "Prepared exact plan", "prepared", 3, 0, None),
        ("comparison-demo-authorized", "Authorized not started", "authorized", 2, 0, None),
        ("comparison-demo-running", "Running bounded screen", "running", 4, 2, None),
        ("comparison-demo-failed", "Failed model contract", "failed", 2, 1, "Synthetic model contract mismatch."),
        ("comparison-demo-timeout", "Timed-out persistent arm", "failed", 2, 1, "Synthetic turn timeout."),
        ("comparison-demo-stopped", "Stopped operator review", "stopped", 3, 1, None),
    )
    fixture = connection.execute(
        "SELECT * FROM comparison_fixtures WHERE fixture_id='ui-demo-a4'"
    ).fetchone()
    assert fixture is not None
    for suite_index, (
        suite_id,
        name,
        status,
        planned,
        consumed,
        failure_reason,
    ) in enumerate(suites):
        fingerprint = _digest(f"plan-{suite_id}", seed)
        connection.execute(
            """
            INSERT INTO comparison_suites
            (suite_id, name, description, fixture_type, fixture_reference,
             fixture_sha256, created_at, created_by, status, measurement_only,
             execute_decisions, randomized_arm_order, ordering_seed,
             planned_inference_count, maximum_inference_starts,
             maximum_total_server_tokens,
             maximum_client_owned_tokens_per_turn, timeout_seconds, fail_closed,
             plan_fingerprint, authorization_status,
             consumed_inference_starts, notes, read_only,
             runtime_executed_elsewhere, recommendation_status,
             recommendation_basis, started_at, completed_at, failure_reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'deterministic_fixture', ?, 1, 0, ?,
                    ?, ?, ?, 60000, 12000, 300, 1, ?, ?, ?, ?, 0, 0, ?, ?,
                    ?, ?, ?)
            """,
            (
                suite_id,
                name,
                (
                    "Synthetic/demo comparison covering model, effort, context, "
                    "usage, validity, latency and ratings."
                ),
                fixture["fixture_type"],
                fixture["fixture_id"],
                fixture["fixture_sha256"],
                _time(720 + suite_index),
                status,
                int(suite_index % 3 == 0),
                seed + suite_index if suite_index % 3 == 0 else None,
                planned,
                planned,
                fingerprint if status != "draft" else None,
                (
                    "authorized"
                    if status in {"authorized", "running"}
                    else "consumed"
                    if status in {"completed", "failed", "stopped"}
                    else "unauthorized"
                ),
                consumed,
                "Synthetic data only.",
                "stateless_turns" if status == "completed" else None,
                "single synthetic UI fixture" if status == "completed" else None,
                _time(740 + suite_index) if status in {"running", "completed", "failed", "stopped"} else None,
                _time(760 + suite_index) if status in {"completed", "failed", "stopped"} else None,
                failure_reason,
            ),
        )
        arm_ids: list[str] = []
        for arm_index in range(planned):
            arm_id = f"arm-{suite_id.removeprefix('comparison-demo-')}-{arm_index:02d}"
            arm_ids.append(arm_id)
            model, effort, _multiplier = profiles[(suite_index + arm_index) % len(profiles)]
            mode = "persistent_thread" if arm_index % 2 else "stateless_turns"
            turn_status = _comparison_arm_status(status, arm_index, consumed)
            profile_id = f"ui-cost-{model.removeprefix('gpt-5.6-')}-{effort}"
            profile = connection.execute(
                "SELECT * FROM model_cost_profiles WHERE profile_id=?",
                (profile_id,),
            ).fetchone()
            assert profile is not None
            connection.execute(
                """
                INSERT INTO comparison_arms
                (arm_id, suite_id, display_name, model, reasoning_effort,
                 context_mode, repetition_index, planned_order,
                 effective_order, expected_model, expected_reasoning_effort,
                 effective_model, effective_reasoning_effort,
                 effective_context_mode, model_contract_matched, prompt_sha256,
                 director_state_sha256, output_schema_sha256,
                 evidence_registry_sha256, advisory_registry_sha256,
                 executable_registry_sha256,
                 applicable_action_space_sha256, base_instructions_sha256,
                 developer_instructions_sha256, campaign_budget_sha256, status,
                 cost_profile_id, relative_cost_multiplier_snapshot,
                 api_input_per_million_snapshot,
                 api_cached_input_per_million_snapshot,
                 api_output_per_million_snapshot, currency_snapshot)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    arm_id,
                    suite_id,
                    f"{model.removeprefix('gpt-5.6-').title()} {effort} {mode}",
                    model,
                    effort,
                    mode,
                    arm_index,
                    arm_index,
                    model,
                    effort,
                    model if turn_status not in {"planned", "failed"} else None,
                    effort if turn_status not in {"planned", "failed"} else None,
                    mode if turn_status not in {"planned", "failed"} else None,
                    0 if turn_status == "failed" else 1 if turn_status != "planned" else None,
                    fixture["prompt_sha256"],
                    fixture["fixture_sha256"],
                    fixture["output_schema_sha256"],
                    fixture["evidence_registry_sha256"],
                    fixture["advisory_registry_sha256"],
                    fixture["executable_registry_sha256"],
                    fixture["applicable_action_space_sha256"],
                    fixture["base_instructions_sha256"],
                    fixture["developer_instructions_sha256"],
                    fixture["campaign_budget_sha256"],
                    turn_status,
                    profile_id,
                    profile["relative_cost_multiplier"],
                    profile["api_input_per_million"],
                    profile["api_cached_input_per_million"],
                    profile["api_output_per_million"],
                    profile["currency"],
                ),
            )
            if arm_index < consumed:
                lifecycle = (
                    "timed_out"
                    if suite_id == "comparison-demo-timeout" and arm_index == 0
                    else "semantic_invalid"
                    if suite_id == "comparison-demo-failed" and arm_index == 0
                    else "completed"
                )
                _insert_comparison_turn(
                    connection,
                    suite_id=suite_id,
                    arm_id=arm_id,
                    turn_index=suite_index * 10 + arm_index,
                    lifecycle=lifecycle,
                    profile=profile,
                    missing_usage=(
                        suite_id == "comparison-demo-running" and arm_index == 1
                    ),
                )
        if status in {"authorized", "running", "completed", "failed", "stopped"}:
            connection.execute(
                """
                INSERT INTO comparison_authorizations
                (authorization_id, suite_id, plan_fingerprint,
                 maximum_inference_starts, authorized_models,
                 authorized_efforts, authorized_context_modes, authorized_at,
                 consumed_inference_starts, revoked_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    f"authorization-{suite_id}",
                    suite_id,
                    fingerprint,
                    planned,
                    _json(sorted({profiles[(suite_index + i) % len(profiles)][0] for i in range(planned)})),
                    _json(sorted({profiles[(suite_index + i) % len(profiles)][1] for i in range(planned)})),
                    _json(["persistent_thread", "stateless_turns"]),
                    _time(735 + suite_index),
                    consumed,
                    _time(760 + suite_index) if status in {"completed", "failed", "stopped"} else None,
                ),
            )

    completed_turns = connection.execute(
        """
        SELECT comparison_turn_id FROM comparison_turns
        WHERE suite_id='comparison-demo-completed'
        ORDER BY created_at
        """
    ).fetchall()
    for index, row in enumerate(completed_turns):
        connection.execute(
            """
            INSERT INTO manual_ratings
            (rating_id, comparison_turn_id, scientific_usefulness, clarity,
             novelty, would_execute, comment, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"manual-rating-demo-{index:02d}",
                row["comparison_turn_id"],
                3 + index % 3,
                4,
                2 + index,
                ("yes", "uncertain", "no")[index % 3],
                "Synthetic reviewer note for layout and history.",
                _time(790 + index),
            ),
        )
    if len(completed_turns) >= 2:
        connection.execute(
            """
            INSERT INTO pairwise_ratings
            (rating_id, suite_id, left_turn_id, right_turn_id, preferred,
             comment, blind_order_seed, created_at)
            VALUES ('pairwise-rating-demo-00', 'comparison-demo-completed',
                    ?, ?, 'left', 'Synthetic blind comparison.', ?, ?)
            """,
            (
                completed_turns[0]["comparison_turn_id"],
                completed_turns[1]["comparison_turn_id"],
                seed,
                _time(800),
            ),
        )


def _normalize_historical_import(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT comparison_turn_id, arm_id FROM comparison_turns
        WHERE suite_id='historical-m6-context-screen'
        ORDER BY created_at
        """
    ).fetchall()
    for row in rows:
        slot = str(row["arm_id"]).removeprefix("historical-")
        connection.execute(
            "UPDATE comparison_turns SET comparison_turn_id=? WHERE comparison_turn_id=?",
            (f"historical-m6-turn-{slot}", row["comparison_turn_id"]),
        )
    for table in (
        "comparison_fixtures",
        "comparison_suites",
        "comparison_turns",
        "model_cost_profiles",
    ):
        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})")
        }
        assignments = []
        if "created_at" in columns:
            assignments.append("created_at='2026-07-25T12:00:00Z'")
        if "completed_at" in columns:
            assignments.append(
                "completed_at=CASE WHEN completed_at IS NULL THEN NULL "
                "ELSE '2026-07-25T12:00:00Z' END"
            )
        if assignments:
            connection.execute(f"UPDATE {table} SET {', '.join(assignments)}")


def _comparison_arm_status(status: str, arm_index: int, consumed: int) -> str:
    if arm_index >= consumed:
        return "inference_started" if status == "running" and arm_index == consumed else "planned"
    if status == "failed":
        return "timed_out" if arm_index == 0 else "failed"
    if status == "stopped":
        return "aborted"
    return "completed"


def _insert_comparison_turn(
    connection: sqlite3.Connection,
    *,
    suite_id: str,
    arm_id: str,
    turn_index: int,
    lifecycle: str,
    profile: sqlite3.Row,
    missing_usage: bool,
) -> None:
    completed = lifecycle == "completed"
    semantic_valid = 0 if lifecycle == "semantic_invalid" else 1 if completed else None
    schema_valid = 1 if lifecycle in {"completed", "semantic_invalid"} else None
    action = (
        "request_diagnostic"
        if turn_index % 3 == 0
        else "start_lane"
        if turn_index % 3 == 1
        else "schedule_verification"
    )
    decision = {
        "schema_version": "1.0",
        "actions": [
            {
                "action_id": f"comparison-action-{turn_index:02d}",
                "type": action,
                "rationale": (
                    "Use the supplied synthetic evidence to measure one bounded "
                    "decision without executing it."
                ),
                "spec": _action_parameters(
                    "request_diagnostic" if action == "request_diagnostic" else "start_lane",
                    turn_index,
                    "lane-00",
                    DEFAULT_UI_FIXTURE_SEED,
                ),
            }
        ],
        "measurement_only": True,
    }
    raw_decision = {
        **decision,
        "synthetic_transport_note": "removed by deterministic normalization",
    }
    input_tokens = None if missing_usage or not completed else 3200 + turn_index * 37
    output_tokens = None if missing_usage or not completed else 480 + turn_index * 11
    total_tokens = (
        None
        if input_tokens is None or output_tokens is None
        else input_tokens + output_tokens
    )
    connection.execute(
        """
        INSERT INTO comparison_turns
        (comparison_turn_id, suite_id, arm_id, app_server_turn_record_id,
         lifecycle_status, thread_lifecycle, schema_valid, semantic_valid,
         evidence_references_valid, action_inside_applicable_space,
         executable_targets_valid, implemented_parameters_only,
         budgets_respected, no_false_counterexample_claim, no_tool_request,
         no_code_request, no_shell_request, no_measurement_execution_request,
         selected_action, selected_algorithm, selected_parameters_json,
         raw_decision_json, normalized_decision_json, validation_issues_json,
         applicable_action_space_json, active_executable_lane_count,
         active_candidate_target_count, historical_evidence_target_count,
         measurement_only, executed, input_tokens, cached_input_tokens,
         cache_write_input_tokens, output_tokens, reasoning_output_tokens,
         server_reported_total_tokens, first_item_latency_seconds,
         final_answer_latency_seconds, total_wall_seconds,
         retry_count_reaching_inference, tool_call_count,
         validation_issue_count, best_score_before, best_score_after,
         time_to_improvement, candidate_evaluations, cpu_seconds,
         exact_verifier_result, cost_profile_id,
         relative_cost_multiplier_snapshot, api_input_per_million_snapshot,
         api_cached_input_per_million_snapshot,
         api_output_per_million_snapshot, currency_snapshot, created_at,
         completed_at)
        VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0,
                0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"comparison-turn-demo-{turn_index:03d}",
            suite_id,
            arm_id,
            lifecycle,
            "fresh" if "stateless" in arm_id or turn_index % 2 == 0 else "resumed",
            schema_valid,
            semantic_valid,
            1 if schema_valid else None,
            1 if schema_valid else None,
            1 if schema_valid else None,
            1 if schema_valid else None,
            1 if schema_valid else None,
            1 if schema_valid else None,
            1 if schema_valid else None,
            1 if schema_valid else None,
            1 if schema_valid else None,
            1 if schema_valid else None,
            action,
            "iterated_local_search_tabu" if action == "start_lane" else None,
            _json(
                {
                    "order": 20,
                    "witness_cap": 10000,
                    "mutation_weights": {
                        "uniform_two_edge_switch": 0.7,
                        "forbidden_cycle_break_switch": 0.3,
                    },
                }
            ),
            _json(raw_decision),
            _json(decision),
            _json(
                ["Synthetic semantic rejection for UI display."]
                if lifecycle == "semantic_invalid"
                else []
            ),
            _json(["start_lane", "request_diagnostic", "schedule_verification"]),
            0,
            3,
            12,
            input_tokens,
            None if input_tokens is None else input_tokens // 3,
            None if input_tokens is None else input_tokens // 20,
            output_tokens,
            None if output_tokens is None else output_tokens // 2,
            total_tokens,
            None if not completed else 0.8 + turn_index * 0.03,
            None if not completed else 1.4 + turn_index * 0.05,
            300.0 if lifecycle == "timed_out" else 2.0 + turn_index * 0.07,
            1 if lifecycle == "semantic_invalid" else 0,
            8.0,
            3.0 if completed else None,
            1.1 if completed else None,
            10000 if completed else None,
            1.8 if completed else None,
            "REJECTED_CYCLE_8" if completed else None,
            profile["profile_id"],
            profile["relative_cost_multiplier"],
            profile["api_input_per_million"],
            profile["api_cached_input_per_million"],
            profile["api_output_per_million"],
            profile["currency"],
            _time(810 + turn_index),
            _time(811 + turn_index) if completed else None,
        ),
    )


def _required_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = (
        "runs",
        "run_metrics",
        "candidates",
        "research_campaigns",
        "research_lanes",
        "lane_metric_windows",
        "campaign_candidates",
        "director_actions",
        "director_action_outcomes",
        "research_hypotheses_v2",
        "app_server_turns",
        "comparison_suites",
        "comparison_arms",
        "comparison_turns",
        "manual_ratings",
        "pairwise_ratings",
        "model_cost_profiles",
    )
    return {
        table: int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
        for table in tables
    }


def _logical_workspace_sha256(
    connection: sqlite3.Connection,
    workspace: Path,
) -> str:
    tables = [
        str(row["name"])
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
            ORDER BY name
            """
        )
    ]
    database: dict[str, list[str]] = {}
    for table in tables:
        rows = [
            _json(list(row))
            for row in connection.execute(f'SELECT * FROM "{table}"')
        ]
        database[table] = sorted(rows)
    files: dict[str, str] = {}
    for path in sorted(value for value in workspace.rglob("*") if value.is_file()):
        relative = path.relative_to(workspace).as_posix()
        if relative in {"workspace.json", "fixture-summary.json"}:
            continue
        if relative.startswith("results.sqlite3"):
            continue
        files[relative] = sha256(path.read_bytes()).hexdigest()
    payload = _json(
        {
            "fixture_version": FIXTURE_VERSION,
            "database": database,
            "files": files,
        }
    )
    return sha256(payload.encode("ascii")).hexdigest()
