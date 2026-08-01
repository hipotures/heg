from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html import escape
from pathlib import Path
from subprocess import DEVNULL, Popen
from threading import Lock
from urllib.parse import parse_qs, urlparse
from typing import Any
import hmac
import json
import mimetypes
import os
import re
import sqlite3
import sys
import time

from .comparison_web import (
    blind_page,
    comparison_detail_page,
    comparisons_page,
    cost_profiles_page,
    error_page,
    new_comparison_page,
)
from .comparisons import (
    ComparisonStore,
    ModelCatalog,
    canonical_sha256,
    default_context_summary,
)
from .comparison_worker import (
    process_is_live,
    recover_stale_workers,
    request_stop,
)
from .resources import recommended_workers
from .locations import asset_path
from .research.auth import auth_is_imported
from .research.catalog import normalize_proposal_ranking_catalog_id
from .research.campaign import (
    campaign_application_data,
    campaign_status,
    parse_duration,
    request_campaign_control,
)
from .research.continuity import repository_commit
from .research.resume import build_resume_preview
from .research.visualization import (
    VisualizationNotFoundError,
    VisualizationUnavailableError,
    campaign_graph_visualization,
    campaign_visualization_series,
)
from .search import ALGORITHMS, MODES
from .state import atomic_write_json, next_control, read_json, utc_now

ARTIFACT_PATTERN = re.compile(r"^[0-9a-f]{20}\.(?:graph6|json|svg)$")
MAX_JSON_RESPONSE = 2 * 1024 * 1024
COMPARISON_PATH = re.compile(
    r"^/comparisons/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})(/blind)?$"
)
CAMPAIGN_TURN_COMMUNICATION_PATH = re.compile(
    r"^/api/research-campaign/turn/"
    r"([A-Za-z0-9][A-Za-z0-9._:-]{0,127})/communication$"
)


def _read_campaign_turn_artifact(
    campaign_dir: Path,
    artifact_ref: str | None,
) -> Any:
    if not artifact_ref:
        return None
    relative = Path(artifact_ref)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("invalid campaign turn artifact reference")
    root = campaign_dir.resolve()
    candidate = root / relative
    if candidate.is_symlink():
        raise ValueError("campaign turn artifact is unavailable")
    path = candidate.resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError("campaign turn artifact is unavailable")
    body = path.read_bytes()
    if len(body) > MAX_JSON_RESPONSE:
        raise ValueError("campaign turn artifact exceeds configured limit")
    return json.loads(body)


def _campaign_attempt_is_persisted(
    workspace: Path, attempt_id: str
) -> bool:
    database = (workspace / "results.sqlite3").resolve()
    try:
        connection = sqlite3.connect(
            f"{database.as_uri()}?mode=ro", uri=True, timeout=0.1
        )
        try:
            return (
                connection.execute(
                    """
                    SELECT 1 FROM campaign_execution_attempts
                    WHERE attempt_id=?
                    """,
                    (attempt_id,),
                ).fetchone()
                is not None
            )
        finally:
            connection.close()
    except sqlite3.OperationalError:
        return False


class DashboardServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        workspace: Path,
        static_dir: Path,
        token: str | None = None,
    ):
        self.workspace = workspace.resolve()
        self.static_dir = static_dir.resolve()
        self.token = token
        self.runner: Popen[bytes] | None = None
        self.campaign_runner: Popen[bytes] | None = None
        self.comparison_runners: dict[str, Popen[bytes]] = {}
        self.launch_lock = Lock()
        super().__init__(address, DashboardHandler)

    def service_actions(self) -> None:
        super().service_actions()
        with self.launch_lock:
            self._reap_comparison_workers_locked()
            if (
                self.campaign_runner is not None
                and self.campaign_runner.poll() is not None
            ):
                self.campaign_runner = None

    def server_close(self) -> None:
        with self.launch_lock:
            self._reap_comparison_workers_locked()
            if (
                self.campaign_runner is not None
                and self.campaign_runner.poll() is not None
            ):
                self.campaign_runner = None
        super().server_close()

    def _reap_comparison_workers_locked(self) -> None:
        reaped: list[tuple[str, Popen[bytes], int]] = []
        for suite_id, process in list(self.comparison_runners.items()):
            return_code = process.poll()
            if return_code is None:
                continue
            reaped.append((suite_id, process, return_code))
            del self.comparison_runners[suite_id]
        if not reaped:
            return
        with ComparisonStore(self.workspace / "results.sqlite3") as store:
            with store.connection:
                for suite_id, process, return_code in reaped:
                    store.connection.execute(
                        """
                        UPDATE comparison_execution_attempts
                        SET process_reap_status='reaped',
                            process_reaped_at=?,
                            process_return_code=?
                        WHERE suite_id=? AND pid=?
                          AND process_reaped_at IS NULL
                        """,
                        (
                            utc_now(),
                            return_code,
                            suite_id,
                            process.pid,
                        ),
                    )

    def start_comparison(
        self, suite_id: str
    ) -> tuple[int, dict[str, Any]]:
        with self.launch_lock:
            self._reap_comparison_workers_locked()
            recover_stale_workers(self.workspace / "results.sqlite3")
            current = self.comparison_runners.get(suite_id)
            if current is not None and current.poll() is None:
                return 409, {"error": "comparison worker is already active"}
            with ComparisonStore(
                self.workspace / "results.sqlite3"
            ) as store:
                try:
                    suite = store._suite_row(suite_id)
                except KeyError:
                    return 404, {"error": "comparison suite not found"}
                if suite["read_only"]:
                    return 409, {"error": "historical comparison suite is read-only"}
                if suite["status"] != "authorized":
                    return 409, {"error": "comparison suite is not authorized"}
                current_fingerprint = canonical_sha256(
                    store.plan_payload(suite_id)
                )
                if current_fingerprint != suite["plan_fingerprint"]:
                    store.invalidate_authorization(suite_id)
                    return 409, {"error": "plan changed after authorization"}
                active_leases = list(store.connection.execute(
                    """
                    SELECT pid, lease_expires_at FROM comparison_worker_leases
                    WHERE released_at IS NULL
                    """,
                ))
                active = sum(
                    str(row["lease_expires_at"]) > utc_now()
                    or process_is_live(int(row["pid"]))
                    for row in active_leases
                )
                try:
                    maximum_concurrent = int(
                        os.environ.get(
                            "SGLAB_COMPARISON_MAX_CONCURRENT", "1"
                        )
                    )
                except ValueError:
                    return 500, {
                        "error": "invalid server comparison concurrency setting"
                    }
                if not 1 <= maximum_concurrent <= 8:
                    return 500, {
                        "error": "server comparison concurrency is out of bounds"
                    }
                if active >= maximum_concurrent:
                    return 409, {
                        "error": "maximum concurrent comparison suites reached"
                    }
            command = [
                sys.executable,
                "-m",
                "sglab",
                "comparisons",
                "worker",
                "--workspace",
                str(self.workspace),
                "--suite-id",
                suite_id,
            ]
            log_dir = self.workspace / "logs" / "comparison-workers"
            log_dir.mkdir(parents=True, exist_ok=True)
            worker_log = log_dir / f"{suite_id}.log"
            if worker_log.is_file() and worker_log.stat().st_size >= 16 * 1024 * 1024:
                os.replace(worker_log, worker_log.with_suffix(".log.1"))
            allowed_environment = {
                key: value
                for key, value in os.environ.items()
                if key
                in {
                    "PATH",
                    "PYTHONPATH",
                    "LANG",
                    "LC_ALL",
                    "TZ",
                    "SGLAB_CODEX_AUTH_SOURCE",
                    "SGLAB_COMPARISON_CODEX_LAUNCHER_JSON",
                    "SGLAB_COMPARISON_MAX_CONCURRENT",
                }
            }
            with worker_log.open("ab") as log:
                process = Popen(
                    command,
                    stdin=DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                    env=allowed_environment,
                )
            self.comparison_runners[suite_id] = process
            deadline = time.monotonic() + 2.0
            lease: Any = None
            while time.monotonic() < deadline and process.poll() is None:
                with ComparisonStore(
                    self.workspace / "results.sqlite3"
                ) as store:
                    lease = store.connection.execute(
                        """
                        SELECT lease_id, pid, process_group_id, acquired_at
                        FROM comparison_worker_leases
                        WHERE suite_id=? AND released_at IS NULL
                        ORDER BY acquired_at DESC LIMIT 1
                        """,
                        (suite_id,),
                    ).fetchone()
                if lease is not None:
                    break
                time.sleep(0.02)
            if lease is None:
                return 409, {
                    "error": (
                        "comparison worker exited or failed preflight before "
                        "acquiring its lease"
                    )
                }
            return 202, {
                "accepted": True,
                "state": "running",
                "pid": process.pid,
                "lease_id": lease["lease_id"],
            }

    def current_run_dir(self) -> Path | None:
        state = read_json(self.workspace / "state.json", default={})
        raw = state.get("run_dir")
        if raw:
            candidate = Path(str(raw)).resolve()
            if self.workspace in candidate.parents and candidate.is_dir():
                return candidate
        if (self.workspace / "run.json").is_file():
            return self.workspace
        return None

    def start_run(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        with self.launch_lock:
            return self._start_run_locked(payload)

    def _start_run_locked(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if (
            self.runner is not None and self.runner.poll() is None
        ) or _workspace_run_is_live(self):
            return 409, {"error": "a dashboard-started run is already active"}
        try:
            order = _integer(payload, "order", 4, 128)
            workers = _integer(payload, "workers", 1, max(1, recommended_workers(256)))
            seed = _integer(payload, "seed", 0, 2**31 - 1)
            wall_seconds = _integer(payload, "wall_seconds", 1, 7 * 86400)
            memory_high = _integer(payload, "memory_high_bytes", 0, 2**63 - 1)
            memory_limit = _integer(payload, "memory_limit_bytes", 0, 2**63 - 1)
            mode = str(payload.get("mode", "cubic_first"))
            algorithm = str(payload.get("algorithm", "simulated_annealing"))
            target = str(payload.get("target", "erdos_gyarfas"))
            notes = str(payload.get("notes", ""))
        except (TypeError, ValueError) as error:
            return 400, {"error": str(error)}
        if target != "erdos_gyarfas":
            return 400, {"error": "unsupported target"}
        if mode not in MODES or algorithm not in ALGORITHMS:
            return 400, {"error": "unsupported mode or algorithm"}
        if mode == "cubic_first" and order % 2:
            return 400, {"error": "cubic_first requires an even order"}
        if mode == "minimal_structure_mixed_degree" and order < 5:
            return 400, {
                "error": ("minimal_structure_mixed_degree requires order at least 5")
            }
        if memory_high and memory_limit and memory_high > memory_limit:
            return 400, {"error": "memory high cannot exceed memory limit"}
        if len(notes) > 500:
            return 400, {"error": "notes exceed 500 characters"}
        command = [
            sys.executable,
            "-m",
            "sglab",
            "run",
            "--target",
            target,
            "--order",
            str(order),
            "--mode",
            mode,
            "--algorithm",
            algorithm,
            "--workers",
            str(workers),
            "--seed",
            str(seed),
            "--time-limit",
            str(wall_seconds),
            "--memory-limit",
            str(memory_limit),
            "--memory-high",
            str(memory_high),
            f"--notes={notes}",
            "--workspace",
            str(self.workspace),
        ]
        logs = self.workspace / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        runner_log = logs / "dashboard-runner.log"
        if runner_log.is_file() and runner_log.stat().st_size >= 16 * 1024 * 1024:
            os.replace(runner_log, runner_log.with_suffix(".log.1"))
        with runner_log.open("ab") as log:
            self.runner = Popen(
                command,
                stdin=DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,
                env=os.environ.copy(),
            )
        request = next_control(self.workspace, "START")
        atomic_write_json(self.workspace / "launch.json", {**payload, **request})
        return 202, {"accepted": True, "pid": self.runner.pid, **request}

    def start_campaign(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        with self.launch_lock:
            if (
                self.campaign_runner is not None
                and self.campaign_runner.poll() is None
            ) or _research_campaign_is_live(self):
                return 409, {"error": "a research campaign is already active"}
            if set(payload) - {
                "stop_mode",
                "duration",
                "director_mode",
                "passive_seed",
                "proposal_ranking",
            }:
                return 400, {"error": "unsupported campaign input"}
            director_mode = str(payload.get("director_mode", "llm"))
            if director_mode not in {"llm", "passive"}:
                return 400, {"error": "invalid director mode"}
            try:
                passive_seed = int(payload.get("passive_seed", 0))
            except (TypeError, ValueError):
                return 400, {"error": "passive_seed must be an integer"}
            if not 0 <= passive_seed < 2**63:
                return 400, {"error": "passive_seed is outside its bounds"}
            try:
                proposal_ranking = normalize_proposal_ranking_catalog_id(
                    payload.get("proposal_ranking")
                )
            except ValueError as error:
                return 400, {"error": str(error)}
            if proposal_ranking is not None and director_mode != "llm":
                return 400, {
                    "error": "proposal-ranking activation requires LLM Director mode"
                }
            if (
                director_mode == "llm"
                and not auth_is_imported(self.workspace / ".sglab")
            ):
                return 409, {
                    "error": (
                        "Director authentication has not been explicitly imported"
                    )
                }
            stop_mode = payload.get("stop_mode")
            command = [
                sys.executable,
                "-m",
                "sglab",
                "research-campaign",
                "start",
                "--workspace",
                str(self.workspace),
                "--director-mode",
                director_mode,
                "--passive-seed",
                str(passive_seed),
            ]
            if proposal_ranking is not None:
                command.extend(("--proposal-ranking", proposal_ranking))
            if stop_mode == "time_limit":
                duration = payload.get("duration")
                if not isinstance(duration, str):
                    return 400, {"error": "duration must be a string"}
                try:
                    parse_duration(duration)
                except ValueError as error:
                    return 400, {"error": str(error)}
                command.extend(("--time-limit", duration))
            elif stop_mode == "until_success":
                if payload.get("duration") not in (None, ""):
                    return 400, {
                        "error": "until-success does not accept a duration"
                    }
                command.append("--until-success")
            else:
                return 400, {"error": "invalid campaign stop mode"}
            logs = self.workspace / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            runner_log = logs / "research-campaign-runner.log"
            if runner_log.is_file() and runner_log.stat().st_size >= 16 * 1024 * 1024:
                os.replace(runner_log, runner_log.with_suffix(".log.1"))
            with runner_log.open("ab") as log:
                self.campaign_runner = Popen(
                    command,
                    stdin=DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                    env=os.environ.copy(),
                )
            return 202, {
                "accepted": True,
                "pid": self.campaign_runner.pid,
                "target": "erdos_gyarfas",
                "stop_mode": stop_mode,
                "director_mode": director_mode,
                "proposal_ranking": proposal_ranking,
                "proposal_ranking_enabled": proposal_ranking is not None,
            }

    def resume_campaign(
        self, payload: dict[str, Any], *, preview_only: bool = False
    ) -> tuple[int, dict[str, Any]]:
        allowed = {
            "campaign_id",
            "additional_time",
            "cpu_workers",
            "maximum_active_lanes",
            "maximum_aggregate_resource_share",
            "lane_memory_bytes",
            "verifier_concurrency",
            "verifier_memory_bytes",
            "verification_queue_depth",
            "repair_acknowledgement",
            "director_mode",
        }
        if set(payload) - allowed:
            return 400, {"error": "unsupported campaign resume input"}
        campaign_id = payload.get("campaign_id")
        additional_time = payload.get("additional_time")
        if not isinstance(campaign_id, str) or not campaign_id:
            return 400, {"error": "campaign_id is required"}
        if not isinstance(additional_time, str):
            return 400, {"error": "additional_time must be a string"}
        try:
            additional_seconds = parse_duration(additional_time)
        except ValueError as error:
            return 400, {"error": str(error)}
        overrides = {
            key: payload[key]
            for key in (
                "cpu_workers",
                "maximum_active_lanes",
                "maximum_aggregate_resource_share",
                "lane_memory_bytes",
                "verifier_concurrency",
                "verifier_memory_bytes",
                "verification_queue_depth",
            )
            if payload.get(key) is not None
        }
        try:
            preview = build_resume_preview(
                self.workspace,
                campaign_id,
                additional_wall_seconds=additional_seconds,
                resource_overrides=overrides,
                repair_acknowledgement=payload.get(
                    "repair_acknowledgement"
                ),
                code_commit=repository_commit(
                    Path(__file__).resolve().parents[2]
                ),
                director_mode=(
                    str(payload["director_mode"])
                    if payload.get("director_mode") is not None
                    else None
                ),
            )
        except (RuntimeError, ValueError) as error:
            return 409, {"error": str(error)}
        if preview_only:
            return 200, preview
        with self.launch_lock:
            if (
                self.campaign_runner is not None
                and self.campaign_runner.poll() is None
            ) or _research_campaign_is_live(self):
                return 409, {"error": "a research campaign is already active"}
            requested_mode = str(
                preview["requested_director_mode"]
            )
            if (
                requested_mode == "llm"
                and not auth_is_imported(
                    campaign_application_data(
                        self.workspace, campaign_id
                    )
                )
            ):
                return 409, {
                    "error": (
                        "Director authentication has not been explicitly "
                        "imported for this campaign"
                    )
                }
            command = [
                sys.executable,
                "-m",
                "sglab",
                "research-campaign",
                "resume",
                "--workspace",
                str(self.workspace),
                "--campaign-id",
                campaign_id,
                "--additional-time",
                additional_time,
            ]
            flags = {
                "cpu_workers": "--cpu-workers",
                "maximum_active_lanes": "--max-active-lanes",
                "maximum_aggregate_resource_share": (
                    "--aggregate-lane-resource-share"
                ),
                "lane_memory_bytes": "--lane-memory-bytes",
                "verifier_concurrency": "--verifier-concurrency",
                "verifier_memory_bytes": "--verifier-memory-bytes",
                "verification_queue_depth": "--verification-queue-depth",
            }
            for key, flag in flags.items():
                if key in overrides:
                    command.extend((flag, str(overrides[key])))
            acknowledgement = payload.get("repair_acknowledgement")
            if isinstance(acknowledgement, str) and acknowledgement:
                command.extend(
                    ("--repair-acknowledgement", acknowledgement)
                )
            if payload.get("director_mode") is not None:
                command.extend(
                    ("--director-mode", requested_mode)
                )
            logs = self.workspace / "logs"
            logs.mkdir(parents=True, exist_ok=True)
            runner_log = logs / "research-campaign-runner.log"
            with runner_log.open("ab") as log:
                process = Popen(
                    command,
                    stdin=DEVNULL,
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                    env=os.environ.copy(),
                )
            self.campaign_runner = process
            attempt_id = str(preview["proposed_attempt_id"])
            startup_deadline = time.monotonic() + 5.0
            startup_confirmed = False
            while time.monotonic() < startup_deadline:
                if _campaign_attempt_is_persisted(
                    self.workspace, attempt_id
                ):
                    startup_confirmed = True
                    break
                return_code = process.poll()
                if return_code is not None:
                    self.campaign_runner = None
                    return 500, {
                        "error": (
                            "campaign resume process exited before startup "
                            f"(return code {return_code}); inspect "
                            "logs/research-campaign-runner.log"
                        )
                    }
                time.sleep(0.05)
            return 202, {
                "accepted": True,
                "pid": process.pid,
                "campaign_id": campaign_id,
                "attempt_id": attempt_id,
                "startup_confirmed": startup_confirmed,
                "director_mode": requested_mode,
            }


class DashboardHandler(BaseHTTPRequestHandler):
    server: DashboardServer

    def _with_workspace_identity(self, body: bytes) -> bytes:
        label = (
            f"{self.server.workspace.parent.name}/"
            f"{self.server.workspace.name}"
        )
        identity = (
            '<aside aria-label="Workspace identity" '
            'style="margin:0 0 1rem;padding:.65rem .85rem;'
            'border:1px solid var(--line);border-radius:9px;'
            'background:var(--surface-2);color:var(--muted)">'
            f'Workspace <strong style="color:var(--text)">{escape(label)}</strong>'
            "</aside>"
        ).encode("utf-8")
        return body.replace(b"<main>", b"<main>" + identity, 1)

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        if len(body) > MAX_JSON_RESPONSE:
            status, body = 507, b'{"error":"response exceeds configured limit"}'
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, status: int, body: bytes) -> None:
        body = self._with_workspace_identity(body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'",
        )
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        if self.server.token is None:
            return True
        supplied = self.headers.get("Authorization", "")
        expected = f"Bearer {self.server.token}"
        return hmac.compare_digest(supplied, expected)

    def _require_authorized(self) -> bool:
        if self._authorized():
            return True
        self._json(401, {"error": "bearer token required"})
        return False

    def _body(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json(400, {"error": "invalid Content-Length"})
            return None
        if length <= 0 or length > 64 * 1024:
            self._json(400, {"error": "invalid request size"})
            return None
        try:
            value = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "invalid JSON"})
            return None
        if not isinstance(value, dict):
            self._json(400, {"error": "expected a JSON object"})
            return None
        return value

    def _serve_static(self, relative: str) -> None:
        if relative in {"", "/"}:
            relative = "index.html"
        candidate = (self.server.static_dir / relative.lstrip("/")).resolve()
        if self.server.static_dir not in candidate.parents:
            self.send_error(403)
            return
        if not candidate.is_file():
            self.send_error(404)
            return
        body = candidate.read_bytes()
        if candidate.name == "index.html":
            body = self._with_workspace_identity(body)
        content_type = (
            mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        )
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self' 'unsafe-inline'; "
            "script-src 'self' 'unsafe-inline'",
        )
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/") and not self._require_authorized():
            return
        if parsed.path == "/comparisons":
            self._html(200, comparisons_page())
            return
        if parsed.path == "/comparisons/new":
            with ComparisonStore(
                self.server.workspace / "results.sqlite3",
                read_only=True,
            ) as store:
                fixtures = [
                    dict(row)
                    for row in store.connection.execute(
                        "SELECT fixture_id, display_name FROM comparison_fixtures "
                        "ORDER BY display_name"
                    )
                ]
                catalog = store.catalog.as_dict()
            self._html(200, new_comparison_page(catalog, fixtures))
            return
        comparison_match = COMPARISON_PATH.fullmatch(parsed.path)
        if comparison_match:
            suite_id = comparison_match.group(1)
            with ComparisonStore(
                self.server.workspace / "results.sqlite3",
                read_only=True,
            ) as store:
                try:
                    store.suite_detail(suite_id)
                except KeyError:
                    self._html(
                        404,
                        error_page(
                            404,
                            "Comparison not found",
                            "No comparison suite exists with that identifier.",
                        ),
                    )
                    return
            body = (
                blind_page(suite_id)
                if comparison_match.group(2)
                else comparison_detail_page(suite_id)
            )
            self._html(200, body)
            return
        if parsed.path == "/model-cost-profiles":
            self._html(200, cost_profiles_page(ModelCatalog.load().as_dict()))
            return
        if parsed.path == "/api/comparisons":
            filters = {
                key: values[0]
                for key, values in parse_qs(parsed.query).items()
                if key in {"model", "effort", "context_mode", "fixture", "status"}
                and values
                and values[0]
            }
            with ComparisonStore(
                self.server.workspace / "results.sqlite3",
                read_only=True,
            ) as store:
                suites = store.list_suites(filters)
            self._json(200, {"suites": suites})
            return
        if parsed.path == "/api/comparisons-summary":
            with ComparisonStore(
                self.server.workspace / "results.sqlite3",
                read_only=True,
            ) as store:
                suites = store.list_suites()
            self._json(
                200,
                {
                    **default_context_summary(),
                    "last_suite": suites[0] if suites else None,
                },
            )
            return
        progress_match = re.fullmatch(
            r"/api/comparisons/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})/"
            r"(progress|turns)",
            parsed.path,
        )
        if progress_match:
            suite_id, view = progress_match.groups()
            recover_stale_workers(self.server.workspace / "results.sqlite3")
            with ComparisonStore(
                self.server.workspace / "results.sqlite3",
                read_only=True,
            ) as store:
                try:
                    detail = store.suite_detail(suite_id)
                except KeyError:
                    self._json(404, {"error": "comparison suite not found"})
                    return
            if view == "turns":
                self._json(200, {"turns": detail["turns"]})
            else:
                self._json(
                    200,
                    {
                        "suite": detail["suite"],
                        "worker": detail["worker"],
                        "arms": detail["arms"],
                        "turns": detail["turns"],
                    },
                )
            return
        api_match = re.fullmatch(
            r"/api/comparisons/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})",
            parsed.path,
        )
        if api_match:
            with ComparisonStore(
                self.server.workspace / "results.sqlite3",
                read_only=True,
            ) as store:
                try:
                    detail = store.suite_detail(
                        api_match.group(1),
                        blind=parse_qs(parsed.query).get("blind") == ["1"],
                    )
                except KeyError:
                    self._json(404, {"error": "comparison suite not found"})
                    return
            configured_auth = os.environ.get("SGLAB_CODEX_AUTH_SOURCE")
            detail["auth_availability"] = {
                "configured": bool(configured_auth),
                "available": bool(
                    configured_auth and Path(configured_auth).is_file()
                ),
                "source_path_exposed": False,
            }
            self._json(200, detail)
            return
        if parsed.path == "/api/model-cost-profiles":
            with ComparisonStore(
                self.server.workspace / "results.sqlite3",
                read_only=True,
            ) as store:
                profiles = [
                    dict(row)
                    for row in store.connection.execute(
                        "SELECT * FROM model_cost_profiles "
                        "ORDER BY effective_from DESC, created_at DESC"
                    )
                ]
            self._json(200, {"profiles": profiles})
            return
        if parsed.path == "/api/status":
            self._json(
                200,
                read_json(
                    self.server.workspace / "state.json",
                    default={"status": "IDLE", "updated_at": utc_now()},
                ),
            )
            return
        communication_match = CAMPAIGN_TURN_COMMUNICATION_PATH.fullmatch(
            parsed.path
        )
        if communication_match:
            database = self.server.workspace / "results.sqlite3"
            connection = sqlite3.connect(
                f"{database.resolve().as_uri()}?mode=ro",
                uri=True,
                timeout=2,
            )
            connection.row_factory = sqlite3.Row
            try:
                row = connection.execute(
                    """
                    SELECT campaign_id, request_artifact_ref, request_sha256,
                           response_artifact_ref, response_sha256
                    FROM app_server_turns WHERE turn_record_id=?
                    """,
                    (communication_match.group(1),),
                ).fetchone()
            finally:
                connection.close()
            if row is None:
                self._json(404, {"error": "campaign turn not found"})
                return
            campaign_dir = (
                self.server.workspace
                / "research-campaigns"
                / str(row["campaign_id"])
            )
            try:
                request = _read_campaign_turn_artifact(
                    campaign_dir,
                    row["request_artifact_ref"],
                )
                response = _read_campaign_turn_artifact(
                    campaign_dir,
                    row["response_artifact_ref"],
                )
            except (OSError, ValueError, json.JSONDecodeError) as error:
                self._json(409, {"error": str(error)})
                return
            self._json(
                200,
                {
                    "turn_record_id": communication_match.group(1),
                    "request": request,
                    "request_sha256": row["request_sha256"],
                    "response": response,
                    "response_sha256": row["response_sha256"],
                },
            )
            return
        if parsed.path == "/api/research-campaign":
            self._json(200, campaign_status(self.server.workspace))
            return
        if parsed.path == "/api/research-campaign/visualization/graph":
            query = parse_qs(parsed.query)
            source = query.get("source", ["global_best"])
            lane_id = query.get("lane_id", [None])
            candidate_id = query.get("candidate_id", [None])
            if (
                len(source) != 1
                or len(lane_id) != 1
                or len(candidate_id) != 1
                or any(
                    value is not None and len(value) > 128
                    for value in (source[0], lane_id[0], candidate_id[0])
                )
            ):
                self._json(400, {"error": "invalid visualization query"})
                return
            try:
                value = campaign_graph_visualization(
                    self.server.workspace,
                    source=source[0],
                    lane_id=lane_id[0],
                    candidate_id=candidate_id[0],
                )
            except VisualizationNotFoundError as error:
                self._json(404, {"error": str(error.args[0])})
                return
            except VisualizationUnavailableError as error:
                self._json(409, {"error": str(error)})
                return
            except ValueError as error:
                self._json(400, {"error": str(error)})
                return
            self._json(200, value)
            return
        if parsed.path == "/api/research-campaign/visualization/series":
            try:
                value = campaign_visualization_series(self.server.workspace)
            except VisualizationNotFoundError as error:
                self._json(404, {"error": str(error.args[0])})
                return
            self._json(200, value)
            return
        if parsed.path == "/api/logs":
            limit = _query_limit(parsed.query, default=50, maximum=500)
            if limit is None:
                self._json(400, {"error": "invalid limit"})
                return
            run_dir = self.server.current_run_dir()
            path = (run_dir or self.server.workspace) / "events.jsonl"
            self._json(200, {"lines": _bounded_tail(path, limit)})
            return
        if parsed.path == "/api/runs":
            runs = []
            root = self.server.workspace / "runs"
            for path in sorted(root.glob("*/run.json"), reverse=True)[:100]:
                try:
                    record = read_json(path)
                    state = read_json(path.parent / "state.json", default={})
                    runs.append(
                        {
                            **record,
                            "live_status": state.get("status", "UNKNOWN"),
                            "elapsed_seconds": state.get("elapsed_seconds", 0),
                            "candidates": state.get("throughput", {}).get(
                                "candidates", 0
                            ),
                            "candidates_per_second": state.get("throughput", {}).get(
                                "candidates_per_second", 0
                            ),
                            "best_score": state.get("best", {})
                            .get("score", {})
                            .get("ordering_key"),
                        }
                    )
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
            self._json(200, {"runs": runs})
            return
        if parsed.path == "/api/candidates":
            limit = _query_limit(parsed.query, default=50, maximum=200)
            if limit is None:
                self._json(400, {"error": "invalid limit"})
                return
            run_dir = self.server.current_run_dir()
            records = []
            if run_dir is not None:
                for path in (run_dir / "best").glob("*.json"):
                    try:
                        records.append(read_json(path))
                    except (OSError, ValueError, json.JSONDecodeError):
                        continue
            records.sort(
                key=lambda record: tuple(
                    record.get("score", {}).get("ordering_key", [10**9] * 5)
                )
            )
            self._json(200, {"candidates": records[:limit]})
            return
        if parsed.path.startswith("/api/artifact/"):
            filename = parsed.path.removeprefix("/api/artifact/")
            if not ARTIFACT_PATTERN.fullmatch(filename):
                self._json(400, {"error": "invalid artifact id"})
                return
            run_dir = self.server.current_run_dir()
            if run_dir is None:
                self._json(404, {"error": "no current run"})
                return
            path = (run_dir / "best" / filename).resolve()
            if path.parent != (run_dir / "best").resolve() or not path.is_file():
                self._json(404, {"error": "artifact not found"})
                return
            body = path.read_bytes()
            if len(body) > MAX_JSON_RESPONSE:
                self._json(507, {"error": "artifact exceeds configured limit"})
                return
            self.send_response(200)
            self.send_header(
                "Content-Type",
                mimetypes.guess_type(filename)[0] or "application/octet-stream",
            )
            self.send_header("Content-Length", str(len(body)))
            self.send_header(
                "Content-Disposition", f'attachment; filename="{filename}"'
            )
            self.end_headers()
            self.wfile.write(body)
            return
        self._serve_static(parsed.path)

    def do_POST(self) -> None:  # noqa: N802
        if not self._require_authorized():
            return
        if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != (
            "application/json"
        ):
            self._json(415, {"error": "Content-Type must be application/json"})
            return
        parsed = urlparse(self.path)
        payload = self._body()
        if payload is None:
            return
        if parsed.path == "/api/comparisons":
            with ComparisonStore(
                self.server.workspace / "results.sqlite3"
            ) as store:
                try:
                    suite_id = store.create_suite(payload)
                except ValueError as error:
                    self._json(400, {"error": str(error)})
                    return
            self._json(201, {"suite_id": suite_id, "status": "draft"})
            return
        comparison_api = re.fullmatch(
            r"/api/comparisons/([A-Za-z0-9][A-Za-z0-9._:-]{0,127})/"
            r"(prepare|authorize|start|stop|ratings|pairwise-ratings)",
            parsed.path,
        )
        if comparison_api:
            suite_id, action = comparison_api.groups()
            try:
                with ComparisonStore(
                    self.server.workspace / "results.sqlite3"
                ) as store:
                    if action == "prepare":
                        response = store.prepare(suite_id)
                    elif action == "authorize":
                        if set(payload) != {"plan_fingerprint"}:
                            raise ValueError(
                                "authorization requires only plan_fingerprint"
                            )
                        response = {
                            "authorization_id": store.authorize(
                                suite_id, payload["plan_fingerprint"]
                            )
                        }
                    elif action == "start":
                        if payload:
                            raise ValueError("start accepts no browser parameters")
                        status, response = self.server.start_comparison(
                            suite_id
                        )
                        self._json(status, response)
                        return
                    elif action == "stop":
                        if payload:
                            raise ValueError("stop accepts no browser parameters")
                        stop_request_id = request_stop(
                            self.server.workspace / "results.sqlite3",
                            suite_id,
                        )
                        stop_row = store.connection.execute(
                            """
                            SELECT state FROM comparison_stop_requests
                            WHERE stop_request_id=?
                            """,
                            (stop_request_id,),
                        ).fetchone()
                        response = {
                            "accepted": True,
                            "state": (
                                str(stop_row["state"])
                                if stop_row is not None
                                else "stop_requested"
                            ),
                            "stop_request_id": stop_request_id,
                        }
                    elif action == "ratings":
                        response = {
                            "rating_id": store.add_manual_rating(
                                suite_id, payload
                            )
                        }
                    else:
                        response = {
                            "rating_id": store.add_pairwise_rating(
                                suite_id, payload
                            )
                        }
            except KeyError:
                self._json(404, {"error": "comparison suite not found"})
                return
            except (TypeError, ValueError) as error:
                self._json(400, {"error": str(error)})
                return
            self._json(200, response)
            return
        if parsed.path == "/api/model-cost-profiles":
            with ComparisonStore(
                self.server.workspace / "results.sqlite3"
            ) as store:
                try:
                    profile_id = store.create_cost_profile(payload)
                except ValueError as error:
                    self._json(400, {"error": str(error)})
                    return
            self._json(201, {"profile_id": profile_id})
            return
        if parsed.path == "/api/runs":
            status, response = self.server.start_run(payload)
            self._json(status, response)
            return
        if parsed.path == "/api/research-campaign":
            status, response = self.server.start_campaign(payload)
            self._json(status, response)
            return
        if parsed.path == "/api/research-campaign/resume-preview":
            status, response = self.server.resume_campaign(
                payload, preview_only=True
            )
            self._json(status, response)
            return
        if parsed.path == "/api/research-campaign/resume":
            status, response = self.server.resume_campaign(payload)
            self._json(status, response)
            return
        if parsed.path == "/api/research-campaign/control":
            action = payload.get("action")
            if action not in {"PAUSE", "STOP"}:
                self._json(400, {"error": "unsupported action"})
                return
            if not _research_campaign_is_live(self.server):
                self._json(409, {"error": "no active research campaign"})
                return
            request = request_campaign_control(
                self.server.workspace, str(action)
            )
            self._json(202, {"accepted": True, **request})
            return
        if parsed.path != "/api/control":
            self._json(404, {"error": "not found"})
            return
        action = payload.get("action")
        if action not in {"PAUSE", "RESUME", "STOP"}:
            self._json(400, {"error": "unsupported action"})
            return
        request = next_control(self.server.workspace, str(action))
        self._json(202, {"accepted": True, **request})

    def log_message(self, format: str, *args: object) -> None:
        return


def _integer(payload: dict[str, Any], key: str, minimum: int, maximum: int) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{key} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} must be between {minimum} and {maximum}")
    return value


def _workspace_run_is_live(server: DashboardServer) -> bool:
    state = read_json(server.workspace / "state.json", default={})
    if state.get("status") not in {
        "RUNNING",
        "PAUSED",
        "PAUSED_MEMORY_HIGH",
        "STOPPING",
        "VERIFYING_FINALIST",
    }:
        return False
    run_dir = server.current_run_dir()
    if run_dir is None:
        return False
    run_record = read_json(run_dir / "run.json", default={})
    try:
        pid = int(run_record.get("environment", {}).get("pid", 0))
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        command = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (OSError, PermissionError):
        return False
    return b"sglab" in command


def _research_campaign_is_live(server: DashboardServer) -> bool:
    state = campaign_status(server.workspace)
    if state.get("state") in {
        None,
        "IDLE",
        "NOT_FOUND",
        "SCHEMA_UNAVAILABLE",
    }:
        return False
    try:
        pid = int(state.get("process", {}).get("pid", 0))
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        command = Path(f"/proc/{pid}/cmdline").read_bytes()
    except (OSError, PermissionError):
        return False
    return b"research-campaign" in command and b"sglab" in command


def _query_limit(query: str, *, default: int, maximum: int) -> int | None:
    raw = parse_qs(query).get("limit", [str(default)])[0]
    try:
        return max(1, min(maximum, int(raw)))
    except ValueError:
        return None


def _bounded_tail(path: Path, limit: int) -> list[str]:
    if not path.exists():
        return []
    with path.open("rb") as handle:
        size = handle.seek(0, os.SEEK_END)
        handle.seek(max(0, size - 256 * 1024))
        data = handle.read()
    return data.decode("utf-8", errors="replace").splitlines()[-limit:]


def create_server(
    workspace: Path,
    host: str,
    port: int,
    *,
    token: str | None = None,
) -> DashboardServer:
    static_dir = asset_path("web")
    return DashboardServer(
        (host, port),
        workspace=workspace,
        static_dir=static_dir,
        token=(
            token
            if token is not None
            else os.environ.get("SGLAB_DASHBOARD_TOKEN")
            or os.environ.get("SGLAB_WEB_TOKEN")
        ),
    )


def serve(workspace: Path, host: str, port: int) -> None:
    server = create_server(workspace, host, port)
    bound_host, bound_port = server.server_address
    print(f"Dashboard: http://{bound_host}:{bound_port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
