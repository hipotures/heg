from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from subprocess import Popen, TimeoutExpired
from typing import Mapping, Sequence
import os
import math
import resource
import shutil
import signal
import tempfile


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


def process_tree_rss_bytes(pid: int) -> int:
    """Return RSS for one process and its current Linux descendants."""

    pending = [pid]
    seen: set[int] = set()
    total = 0
    while pending:
        current = pending.pop()
        if current in seen or current <= 0:
            continue
        seen.add(current)
        total += current_rss_bytes(current)
        children_path = Path(
            f"/proc/{current}/task/{current}/children"
        )
        try:
            pending.extend(
                int(value)
                for value in children_path.read_text(
                    encoding="ascii"
                ).split()
            )
        except (FileNotFoundError, PermissionError, ValueError):
            continue
    return total


def disk_free_bytes(path: str | Path) -> int:
    return shutil.disk_usage(Path(path)).free


def sqlite_size_bytes(path: str | Path) -> int:
    database = Path(path)
    return sum(
        candidate.stat().st_size
        for candidate in (
            database,
            Path(f"{database}-wal"),
            Path(f"{database}-shm"),
        )
        if candidate.is_file()
    )


def run_bounded(
    command: Sequence[str],
    *,
    timeout_seconds: float,
    output_limit_bytes: int = 1024 * 1024,
    memory_limit_bytes: int | None = None,
    cwd: str | Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> ProcessResult:
    """Run an external tool in its own process group with hard output bounds."""

    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if output_limit_bytes < 1:
        raise ValueError("output_limit_bytes must be positive")
    if memory_limit_bytes is not None and memory_limit_bytes < 0:
        raise ValueError("memory_limit_bytes cannot be negative")

    def child_setup() -> None:
        set_address_space_limit(memory_limit_bytes)
        file_limit = output_limit_bytes + 1
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))

    with (
        tempfile.TemporaryFile() as stdout_file,
        tempfile.TemporaryFile() as stderr_file,
    ):
        try:
            process = Popen(
                list(command),
                cwd=cwd,
                env=environment,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=True,
                preexec_fn=child_setup,
            )
        except OSError as error:
            stderr = f"{type(error).__name__}: {error}".encode("utf-8")
            return ProcessResult(
                "TOOL_FAILURE",
                None,
                b"",
                stderr[:output_limit_bytes],
            )
        try:
            process.communicate(timeout=timeout_seconds)
            status = "OK" if process.returncode == 0 else "ERROR"
        except TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.communicate()
            status = "UNKNOWN_TIMEOUT"

        stdout_size = os.fstat(stdout_file.fileno()).st_size
        stderr_size = os.fstat(stderr_file.fileno()).st_size
        stdout_file.seek(0)
        stdout = stdout_file.read(output_limit_bytes)
        stderr_file.seek(0)
        stderr = stderr_file.read(max(0, output_limit_bytes - len(stdout)))
        if (
            status != "UNKNOWN_TIMEOUT"
            and stdout_size + stderr_size > output_limit_bytes
        ):
            status = "ERROR_OUTPUT_LIMIT"
        return ProcessResult(status, process.returncode, stdout, stderr)
