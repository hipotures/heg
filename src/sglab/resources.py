from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from subprocess import PIPE, Popen, TimeoutExpired
from typing import Sequence
import os
import resource
import shutil
import signal


@dataclass(frozen=True, slots=True)
class ProcessResult:
    status: str
    returncode: int | None
    stdout: bytes
    stderr: bytes


def recommended_workers(requested: int | None = None, reserve_threads: int = 2) -> int:
    available = max(1, (os.cpu_count() or 1) - max(2, reserve_threads))
    conservative_default = min(12, available)
    return max(1, min(requested or conservative_default, available))


def set_address_space_limit(limit_bytes: int | None) -> None:
    if limit_bytes is None or limit_bytes <= 0:
        return
    resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))


def current_rss_bytes(pid: int | None = None) -> int:
    status = Path(f"/proc/{pid or os.getpid()}/status")
    try:
        for line in status.read_text(encoding="ascii").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (FileNotFoundError, PermissionError, ValueError):
        return 0
    return 0


def disk_free_bytes(path: str | Path) -> int:
    return shutil.disk_usage(Path(path)).free


def run_bounded(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    output_limit_bytes: int = 1024 * 1024,
    memory_limit_bytes: int | None = None,
    cwd: str | Path | None = None,
) -> ProcessResult:
    """Run an external tool in its own process group with hard output bounds."""

    def child_setup() -> None:
        set_address_space_limit(memory_limit_bytes)

    process = Popen(
        list(command),
        cwd=cwd,
        stdout=PIPE,
        stderr=PIPE,
        start_new_session=True,
        preexec_fn=child_setup,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        status = "OK" if process.returncode == 0 else "ERROR"
    except TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        stdout, stderr = process.communicate()
        status = "UNKNOWN_TIMEOUT"
    if len(stdout) > output_limit_bytes or len(stderr) > output_limit_bytes:
        return ProcessResult(
            "ERROR_OUTPUT_LIMIT",
            process.returncode,
            stdout[:output_limit_bytes],
            stderr[:output_limit_bytes],
        )
    return ProcessResult(status, process.returncode, stdout, stderr)
