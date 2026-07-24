from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json

from .protocol import canonical_json
from .store import ResearchStore


def audit_campaign_artifacts(
    *,
    store: ResearchStore,
    campaign_id: str,
    campaign_dir: Path,
) -> dict[str, Any]:
    """Verify immutable snapshot and Director response hashes for replay."""

    root = campaign_dir.resolve()
    checked = 0
    failures: list[dict[str, str]] = []
    snapshots = store.connection.execute(
        """
        SELECT snapshot_id, artifact_ref, artifact_sha256
        FROM director_snapshots WHERE campaign_id=?
        """,
        (campaign_id,),
    ).fetchall()
    for row in snapshots:
        checked += 1
        _check_file(
            root,
            str(row["artifact_ref"]),
            str(row["artifact_sha256"]),
            failures,
            raw=True,
        )
    turns = store.connection.execute(
        """
        SELECT turn_record_id, response_artifact_ref, response_sha256
        FROM app_server_turns
        WHERE campaign_id=? AND response_artifact_ref IS NOT NULL
        """,
        (campaign_id,),
    ).fetchall()
    for row in turns:
        checked += 1
        _check_file(
            root,
            str(row["response_artifact_ref"]),
            str(row["response_sha256"]),
            failures,
            raw=False,
        )
    return {
        "campaign_id": campaign_id,
        "checked_artifacts": checked,
        "failures": failures,
        "valid": not failures,
    }


def recorded_decisions(
    *,
    store: ResearchStore,
    campaign_id: str,
    campaign_dir: Path,
) -> dict[str, dict[str, Any]]:
    root = campaign_dir.resolve()
    rows = store.connection.execute(
        """
        SELECT b.snapshot_id, b.response_artifact_ref, b.response_sha256
        FROM director_action_batches b
        WHERE b.campaign_id=? AND b.response_artifact_ref IS NOT NULL
        ORDER BY b.created_at, b.rowid
        """,
        (campaign_id,),
    ).fetchall()
    decisions: dict[str, dict[str, Any]] = {}
    for row in rows:
        path = _safe_path(root, str(row["response_artifact_ref"]))
        payload = json.loads(path.read_text(encoding="utf-8"))
        encoded = canonical_json(payload, max_bytes=128 * 1024)
        if hashlib.sha256(encoded).hexdigest() != row["response_sha256"]:
            raise RuntimeError("recorded decision hash mismatch")
        decisions[str(row["snapshot_id"])] = payload
    return decisions


def _check_file(
    root: Path,
    relative: str,
    expected: str,
    failures: list[dict[str, str]],
    *,
    raw: bool,
) -> None:
    try:
        path = _safe_path(root, relative)
        payload = path.read_bytes()
        if not raw:
            parsed = json.loads(payload)
            payload = canonical_json(parsed, max_bytes=128 * 1024)
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected:
            failures.append({"artifact_ref": relative, "failure": "hash_mismatch"})
    except (OSError, ValueError, json.JSONDecodeError) as error:
        failures.append(
            {
                "artifact_ref": relative,
                "failure": f"{type(error).__name__}: {error}"[:500],
            }
        )


def _safe_path(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError:
        raise ValueError("replay artifact escaped campaign directory") from None
    return path
