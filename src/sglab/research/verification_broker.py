from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from multiprocessing import get_context
from pathlib import Path
from queue import Empty
from time import monotonic
from typing import Any
import hashlib
import json

from ..artifacts import hash_file
from ..certification import certify
from ..model import BitGraph
from ..resources import set_address_space_limit
from .lanes import LaneManager
from .store import ResearchStore


@dataclass(slots=True)
class _RunningVerification:
    job_id: str
    process: Any
    results: Any
    started: float
    artifact_relative: str


def _verification_worker(
    graph6: str,
    target: str,
    output_dir: str,
    binary: str | None,
    timeout_seconds: float,
    verifier_memory_bytes: int,
    broker_memory_bytes: int,
    results: Any,
) -> None:
    set_address_space_limit(broker_memory_bytes)
    try:
        manifest = certify(
            BitGraph.from_graph6(graph6),
            Path(output_dir),
            target=target,
            binary=Path(binary) if binary else None,
            timeout_seconds=timeout_seconds,
            memory_limit_bytes=verifier_memory_bytes,
        )
        results.put({"ok": True, "manifest": manifest}, timeout=1)
    except BaseException as error:
        results.put(
            {
                "ok": False,
                "error": f"{type(error).__name__}: {error}"[:2000],
            },
            timeout=1,
        )


class M4VerificationBroker:
    """Bounded queue around the existing two-path M4 certifier."""

    def __init__(
        self,
        *,
        store: ResearchStore,
        manager: LaneManager,
        campaign_id: str,
        campaign_dir: Path,
        binary: Path | None = None,
        max_queue: int = 32,
        timeout_seconds: float = 60,
        verifier_memory_bytes: int = 512 * 1024 * 1024,
        broker_memory_bytes: int = 1024 * 1024 * 1024,
    ):
        if max_queue < 1:
            raise ValueError("verification queue limit must be positive")
        if timeout_seconds <= 0:
            raise ValueError("verification timeout must be positive")
        self.store = store
        self.manager = manager
        self.campaign_id = campaign_id
        self.campaign_dir = campaign_dir.resolve()
        self.binary = binary.resolve() if binary is not None else None
        self.max_queue = max_queue
        self.timeout_seconds = timeout_seconds
        self.verifier_memory_bytes = verifier_memory_bytes
        self.broker_memory_bytes = broker_memory_bytes
        self.context = get_context("spawn")
        self.running: _RunningVerification | None = None
        self.events: list[dict[str, Any]] = []

    def dispatch_pending_actions(self) -> list[str]:
        applied: list[str] = []
        for action in self.store.pending_candidate_actions(self.campaign_id):
            action_id = str(action["action_id"])
            if _expired(str(action["lease_expires_at"])):
                self.store.record_action_outcome(
                    action_id=action_id,
                    status="rejected_lease_expired",
                    failure_kind="action_lease_expired",
                    failure_detail="candidate action lease expired",
                )
                self.events.append({"reason": "action_lease_expired"})
                continue
            parameters = json.loads(str(action["parameters_json"]))
            if action["action_type"] == "promote_candidate":
                candidate_ids = [str(parameters["candidate_id"])]
                priority = int(action["priority"])
            else:
                candidate_ids = [
                    str(value) for value in parameters["candidate_ids"]
                ]
                priority = int(parameters["verification_priority"])
            queue_depth = self.store.connection.execute(
                """
                SELECT count(*) FROM campaign_verification_jobs
                WHERE campaign_id=? AND state IN ('queued', 'running')
                """,
                (self.campaign_id,),
            ).fetchone()[0]
            if int(queue_depth) + len(candidate_ids) > self.max_queue:
                self.store.record_action_outcome(
                    action_id=action_id,
                    status="failed",
                    failure_kind="verification_queue_full",
                    failure_detail="bounded M4 queue has no capacity",
                )
                self.events.append({"reason": "resource_pressure"})
                continue
            job_ids = [
                _job_id(self.campaign_id, candidate_id)
                for candidate_id in candidate_ids
            ]
            self.store.queue_verification_action(
                action_id=action_id,
                candidate_ids=candidate_ids,
                priority=priority,
                job_ids=job_ids,
            )
            applied.append(action_id)
        return applied

    def start_ready(self) -> str | None:
        if self.running is not None:
            return None
        jobs = self.store.queued_verification_jobs(self.campaign_id, 1)
        if not jobs:
            return None
        job = jobs[0]
        candidate = self.store.campaign_candidate(str(job["candidate_id"]))
        job_id = str(job["verification_job_id"])
        relative = str(Path("verifications") / job_id)
        output = self.campaign_dir / relative
        output.mkdir(parents=True, exist_ok=True)
        results = self.context.Queue(maxsize=1)
        process = self.context.Process(
            target=_verification_worker,
            args=(
                str(candidate["graph6"]),
                str(self.store.campaign(self.campaign_id)["target"]),
                str(output),
                str(self.binary) if self.binary is not None else None,
                self.timeout_seconds,
                self.verifier_memory_bytes,
                self.broker_memory_bytes,
                results,
            ),
            name=f"sglab-m4-{job_id}",
        )
        if not self.store.mark_verification_started(job_id):
            return None
        process.start()
        self.running = _RunningVerification(
            job_id=job_id,
            process=process,
            results=results,
            started=monotonic(),
            artifact_relative=relative,
        )
        return job_id

    def poll(self) -> dict[str, Any] | None:
        running = self.running
        if running is None:
            return None
        try:
            result = running.results.get_nowait()
        except Empty:
            result = None
        deadline = 2 * self.timeout_seconds + 30
        if result is None and monotonic() - running.started > deadline:
            running.process.kill()
            running.process.join(timeout=1)
            result = {
                "ok": False,
                "error": "verification broker wall-time limit exceeded",
            }
        if result is None and not running.process.is_alive():
            running.process.join(timeout=1)
            result = {
                "ok": False,
                "error": f"verification process exited {running.process.exitcode}",
            }
        if result is None:
            return None
        running.process.join(timeout=1)
        if result["ok"]:
            manifest_path = (
                self.campaign_dir
                / running.artifact_relative
                / "manifest.json"
            )
            try:
                persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                persisted = None
            if (
                not isinstance(persisted, dict)
                or persisted != result["manifest"]
                or not _valid_manifest(persisted)
            ):
                status = "TOOL_FAILURE"
            else:
                status = str(persisted["status"])
            artifact_ref = str(
                Path(running.artifact_relative) / "manifest.json"
            )
            manifest_sha256 = (
                hash_file(manifest_path) if manifest_path.is_file() else None
            )
        else:
            status = "TOOL_FAILURE"
            artifact_ref = running.artifact_relative
            manifest_sha256 = None
        if status == "COUNTEREXAMPLE_VERIFIED":
            self.manager.pause_all()
        terminal = self.store.complete_verification_job(
            job_id=running.job_id,
            status=status,
            artifact_ref=artifact_ref,
        )
        event = {
            "kind": "verification_result",
            "reason": (
                "verifier_disagreement"
                if status == "VERIFIER_DISAGREEMENT"
                else "verification_result"
            ),
            "verification_job_id": running.job_id,
            "status": status,
            "artifact_ref": artifact_ref,
            "manifest_sha256": manifest_sha256,
            "terminal": terminal,
            "error": result.get("error"),
        }
        self.events.append(event)
        if running.process.is_alive():
            running.process.kill()
            running.process.join(timeout=1)
        running.results.close()
        self.running = None
        return event

    def pump(self) -> list[dict[str, Any]]:
        self.dispatch_pending_actions()
        self.start_ready()
        event = self.poll()
        return [event] if event is not None else []

    def shutdown(self) -> None:
        if self.running is None:
            return
        if self.running.process.is_alive():
            self.running.process.kill()
        self.running.process.join(timeout=1)
        self.running.results.close()
        self.running = None


def _job_id(campaign_id: str, candidate_id: str) -> str:
    digest = hashlib.sha256(
        f"{campaign_id}:{candidate_id}".encode()
    ).hexdigest()[:24]
    return f"verification-{digest}"


def _expired(value: str) -> bool:
    return (
        datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
        <= datetime.now(UTC)
    )


def _valid_manifest(value: dict[str, Any]) -> bool:
    status = value.get("status")
    if status not in {
        "COUNTEREXAMPLE_VERIFIED",
        "INVALID_CANDIDATE",
        "UNKNOWN_TIMEOUT",
        "UNKNOWN_MEMORY_LIMIT",
        "TOOL_FAILURE",
        "VERIFIER_DISAGREEMENT",
    }:
        return False
    verifiers = value.get("verifiers")
    if not isinstance(verifiers, list) or len(verifiers) != 2:
        return False
    implementations = {
        str(verifier.get("implementation"))
        for verifier in verifiers
        if isinstance(verifier, dict)
    }
    if implementations != {"python-reference-dfs", "cpp17-bitset-dfs"}:
        return False
    if status == "COUNTEREXAMPLE_VERIFIED":
        statuses = {str(verifier.get("status")) for verifier in verifiers}
        return statuses == {"VERIFIED", "ABSENT"} and all(
            verifier.get("complete") is True for verifier in verifiers
        )
    return True
