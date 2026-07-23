from __future__ import annotations

from pathlib import Path
from datetime import UTC, datetime
import fcntl
import hashlib
import json
import os
from typing import Any


def atomic_write_json(path: str | Path, data: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    payload = json.dumps(data, sort_keys=True, indent=2) + "\n"
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    try:
        directory_fd = os.open(target.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def read_json(
    path: str | Path, default: dict[str, Any] | None = None
) -> dict[str, Any]:
    target = Path(path)
    if not target.exists():
        return {} if default is None else default
    with target.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {target}")
    return value


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def append_event(
    path: str | Path,
    event: str,
    *,
    max_bytes: int = 16 * 1024 * 1024,
    **fields: Any,
) -> None:
    """Append one structured event while keeping the active log bounded."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = {"at": utc_now(), "event": event, **fields}
    line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
    encoded = line.encode("utf-8")
    if max_bytes >= 512 and len(encoded) > max_bytes:
        line = (
            json.dumps(
                {
                    "at": record["at"],
                    "event": event,
                    "detail_sha256": hashlib.sha256(encoded).hexdigest(),
                    "original_bytes": len(encoded),
                    "truncated": True,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
    if (
        target.exists()
        and target.stat().st_size + len(line.encode("utf-8")) > max_bytes
    ):
        rotated = target.with_suffix(target.suffix + ".1")
        os.replace(target, rotated)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()


def next_control(workspace: str | Path, action: str) -> dict[str, Any]:
    root = Path(workspace)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".control.lock"
    with lock_path.open("a", encoding="ascii") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        current = read_json(root / "control.json", default={"version": 0})
        request = {
            "version": int(current.get("version", 0)) + 1,
            "requested_at": utc_now(),
            "action": action,
        }
        atomic_write_json(root / "control.json", request)
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return request
