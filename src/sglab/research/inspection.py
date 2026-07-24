from __future__ import annotations

from pathlib import Path
from typing import Any
import sqlite3


def validate_thread_path(thread_path: str, runtime_root: Path) -> Path:
    """Resolve an app-server-provided path without assuming its layout."""

    candidate = Path(thread_path)
    if not candidate.is_absolute():
        raise ValueError("thread.path is not absolute")
    root = runtime_root.resolve()
    resolved = candidate.resolve(strict=True)
    if not resolved.is_file():
        raise ValueError("thread.path is not a regular file")
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("thread.path escapes the private runtime root") from error
    return resolved


def inspect_persisted_sessions(
    database_path: Path,
    runtime_root: Path,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    if not database_path.is_file():
        return []
    connection = sqlite3.connect(
        f"{database_path.resolve().as_uri()}?mode=ro",
        uri=True,
    )
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT session_record_id, campaign_id, thread_id, thread_path,
                   started_at, last_resumed_at
            FROM app_server_sessions
            WHERE thread_path IS NOT NULL
            ORDER BY COALESCE(last_resumed_at, started_at) DESC, rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    finally:
        connection.close()
    sessions: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            path = validate_thread_path(str(row["thread_path"]), runtime_root)
        except (OSError, ValueError) as error:
            item.update({"valid": False, "error": str(error)})
        else:
            stat = path.stat()
            item.update(
                {
                    "valid": True,
                    "path": str(path),
                    "bytes": stat.st_size,
                    "mode": oct(stat.st_mode & 0o777),
                }
            )
        sessions.append(item)
    return sessions
