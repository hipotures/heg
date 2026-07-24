from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json
import shutil
import tempfile

from ..resources import run_bounded
from ..state import utc_now


SCHEMA_BUNDLES = (
    "codex_app_server_protocol.schemas.json",
    "codex_app_server_protocol.v2.schemas.json",
)

REQUIRED_SCHEMA_FILES = (
    "v1/InitializeParams.json",
    "v2/SkillsListParams.json",
    "v2/SkillsConfigWriteParams.json",
    "v2/ThreadStartParams.json",
    "v2/ThreadResumeParams.json",
    "v2/TurnStartParams.json",
    "v2/ItemCompletedNotification.json",
    "v2/TurnCompletedNotification.json",
    "v2/ThreadTokenUsageUpdatedNotification.json",
    "v2/ErrorNotification.json",
    "v2/ThreadStatusChangedNotification.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha256(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _text_result(command: list[str], timeout: float = 30) -> str:
    result = run_bounded(
        command,
        timeout_seconds=timeout,
        output_limit_bytes=4 * 1024 * 1024,
    )
    if result.status != "OK":
        detail = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(f"{command[0]} preflight failed: {result.status}: {detail}")
    return result.stdout.decode("utf-8", errors="strict").strip()


def generate_protocol_preflight(codex: str = "codex") -> dict[str, Any]:
    version_output = _text_result([codex, "--version"])
    features_output = _text_result([codex, "features", "list"])
    executable = shutil.which(codex)
    if executable is None:
        raise RuntimeError(f"Codex executable not found: {codex}")
    resolved_executable = Path(executable).resolve()
    with tempfile.TemporaryDirectory(prefix="sglab-app-server-schema-") as directory:
        schema_dir = Path(directory)
        _text_result(
            [
                codex,
                "app-server",
                "generate-json-schema",
                "--out",
                str(schema_dir),
            ],
            timeout=120,
        )
        selected = (*SCHEMA_BUNDLES, *REQUIRED_SCHEMA_FILES)
        schema_hashes = {
            relative: _sha256(schema_dir / relative) for relative in selected
        }
        canonical_schema_hashes = {
            relative: _canonical_json_sha256(schema_dir / relative)
            for relative in selected
        }
        thread_start = json.loads(
            (schema_dir / "v2/ThreadStartParams.json").read_text(encoding="utf-8")
        )
        turn_start = json.loads(
            (schema_dir / "v2/TurnStartParams.json").read_text(encoding="utf-8")
        )
    features = []
    for line in features_output.splitlines():
        fields = line.split()
        if len(fields) >= 3:
            features.append(
                {"name": fields[0], "stage": " ".join(fields[1:-1]), "enabled": fields[-1] == "true"}
            )
    return {
        "created_at": utc_now(),
        "codex_version_output": version_output,
        "codex_executable": str(resolved_executable),
        "codex_executable_sha256": _sha256(resolved_executable),
        "features": features,
        "schema_hashes": schema_hashes,
        "canonical_schema_hashes": canonical_schema_hashes,
        "thread_start_fields": sorted(thread_start.get("properties", {})),
        "turn_start_fields": sorted(turn_start.get("properties", {})),
    }
