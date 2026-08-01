from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
import hashlib
import json
import os
import sqlite3
import zipfile

from ..state import utc_now
from .catalog import normalize_proposal_ranking_catalog_id
from .store import ResearchStore


EXCLUDED_NAMES = {"auth.json"}
EXCLUDED_PARTS = {
    ".codex",
    "codex-home",
    "exports",
    "private-home",
    "sqlite-home",
}


def export_campaign(
    *,
    store: ResearchStore,
    campaign_id: str,
    campaign_dir: Path,
    output: Path,
    maximum_files: int = 10_000,
    maximum_input_bytes: int = 512 * 1024 * 1024,
) -> dict[str, Any]:
    """Create an atomic reproducibility ZIP using SQLite Online Backup."""

    root = campaign_dir.resolve()
    target = output.resolve()
    if maximum_files < 1 or maximum_input_bytes < 1:
        raise ValueError("export limits must be positive")
    files: list[tuple[str, bytes]] = []
    total = 0
    with TemporaryDirectory(prefix="sglab-export-") as temporary:
        database_path = Path(temporary) / "campaign.sqlite3"
        destination = sqlite3.connect(database_path)
        store.connection.backup(destination)
        integrity = str(destination.execute("PRAGMA integrity_check").fetchone()[0])
        user_version = int(destination.execute("PRAGMA user_version").fetchone()[0])
        destination.close()
        if integrity != "ok":
            raise RuntimeError(f"export database integrity failure: {integrity}")
        database_bytes = database_path.read_bytes()
        files.append(("campaign.sqlite3", database_bytes))
        total += len(database_bytes)
        campaign = store.campaign(campaign_id)
        plan = {}
        plan_path = root / "campaign-plan.json"
        if plan_path.is_file():
            try:
                plan = json.loads(plan_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise RuntimeError("campaign plan is unavailable for export") from error
        try:
            proposal_ranking = normalize_proposal_ranking_catalog_id(
                plan.get("proposal_ranking")
            )
        except ValueError as error:
            raise RuntimeError(str(error)) from error
        scheduler = store.connection.execute(
            """
            SELECT policy_id, policy_version, scheduler_state_version,
                   state_version, rng_seed, rng_counter
            FROM passive_scheduler_states WHERE campaign_id=?
            """,
            (campaign_id,),
        ).fetchone()

        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(root)
            if (
                path.resolve() == target
                or path.name in EXCLUDED_NAMES
                or set(relative.parts) & EXCLUDED_PARTS
                or path.name.endswith(("-wal", "-shm"))
                or path.suffix == ".sqlite3"
            ):
                continue
            payload = path.read_bytes()
            total += len(payload)
            if total > maximum_input_bytes:
                raise RuntimeError("campaign export input byte limit exceeded")
            files.append((relative.as_posix(), payload))
            if len(files) > maximum_files:
                raise RuntimeError("campaign export file-count limit exceeded")

        manifest = {
            "schema_version": "1.0",
            "campaign_id": campaign_id,
            "director_mode": str(
                campaign.get("director_mode", "llm")
            ),
            "plan_fingerprint": plan.get("plan_fingerprint"),
            "proposal_ranking": proposal_ranking,
            "proposal_ranking_enabled": proposal_ranking is not None,
            "passive_scheduler": (
                dict(scheduler) if scheduler is not None else None
            ),
            "created_at": utc_now(),
            "database": {
                "path": "campaign.sqlite3",
                "user_version": user_version,
                "integrity_check": integrity,
                "sha256": hashlib.sha256(database_bytes).hexdigest(),
            },
            "files": [
                {
                    "path": name,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                for name, payload in files
            ],
            "authentication_included": False,
        }
        manifest_bytes = (
            json.dumps(
                manifest,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            )
            + "\n"
        ).encode("ascii")
        temporary_output = target.with_suffix(target.suffix + ".tmp")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(
            temporary_output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
        ) as archive:
            for name, payload in files:
                _write_deterministic(archive, name, payload)
            _write_deterministic(archive, "manifest.json", manifest_bytes)
        with temporary_output.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary_output, target)
    return {
        **manifest,
        "archive_path": str(target),
        "archive_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "archive_bytes": target.stat().st_size,
    }


def _write_deterministic(
    archive: zipfile.ZipFile, name: str, payload: bytes
) -> None:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    archive.writestr(info, payload)
