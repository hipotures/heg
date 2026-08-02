"""Durable, human-readable projections for research artifacts.

SQLite rows and the raw App Server files remain authoritative.  This module
only projects those records into bounded operator-facing files and never
changes scientific state.  The projection is deliberately idempotent: a
turn is assigned a stable sequence from its provenance record and files are
rewritten only when their bytes differ.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json
import os
import re
import sqlite3

from ..state import atomic_write_json


CAPSULE_SCHEMA_VERSION = "1.0"
MAX_RAW_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_MARKDOWN_BYTES = 128 * 1024
MAX_EVENT_RECORDS = 4096
_TURN_DIRECTORY = re.compile(r"^turn-(\d{4,})$")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        try:
            if path.read_bytes() == payload:
                return
        except OSError:
            pass
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _write_text(path: Path, text: str) -> None:
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_MARKDOWN_BYTES:
        encoded = encoded[:MAX_MARKDOWN_BYTES]
        encoded += b"\n\n[bounded projection truncated]\n"
    _write_bytes(path, encoded)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write_json(path, value)


def _safe_relative(root: Path, reference: str | None) -> Path | None:
    if not reference:
        return None
    relative = Path(str(reference))
    if relative.is_absolute() or ".." in relative.parts:
        return None
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        return None
    if candidate.is_symlink():
        return None
    return candidate


def _read_json(path: Path | None) -> Any:
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _unavailable(reference: str | None, reason: str) -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "source_reference": reference,
    }


def _copy_or_mark(source: Path | None, target: Path, reference: str | None) -> dict[str, Any]:
    if source is None or not source.is_file():
        marker = _unavailable(reference, "source artifact is unavailable")
        _write_json(target, marker)
        return marker
    try:
        size = source.stat().st_size
    except OSError:
        marker = _unavailable(reference, "source artifact cannot be inspected")
        _write_json(target, marker)
        return marker
    digest = _sha256_file(source)
    if size > MAX_RAW_ARTIFACT_BYTES:
        marker = {
            "available": False,
            "reason": "source artifact exceeds capsule bound",
            "source_reference": reference,
            "source_bytes": size,
            "source_sha256": digest,
            "max_bytes": MAX_RAW_ARTIFACT_BYTES,
        }
        _write_json(target, marker)
        return marker
    _write_bytes(target, source.read_bytes())
    return {
        "available": True,
        "source_reference": reference,
        "source_bytes": size,
        "source_sha256": digest,
        "capsule_path": str(target),
    }


def _truncate(value: Any, limit: int = 12_000) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, indent=2)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[bounded projection truncated]"


def _event_projection(wire_path: Path | None) -> dict[str, Any]:
    if wire_path is None or not wire_path.is_file():
        return {"available": False, "reason": "wire artifact is unavailable", "events": []}
    events: list[dict[str, Any]] = []
    try:
        with wire_path.open("r", encoding="utf-8") as handle:
            for sequence, line in enumerate(handle):
                if sequence >= MAX_EVENT_RECORDS:
                    break
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    events.append({"sequence": sequence, "parse_error": True})
                    continue
                if isinstance(value, dict):
                    events.append(
                        {
                            "sequence": sequence,
                            "type": value.get("type") or value.get("event"),
                            "method": value.get("method"),
                            "id": value.get("id"),
                            "timestamp": value.get("timestamp") or value.get("at"),
                        }
                    )
                else:
                    events.append({"sequence": sequence, "type": type(value).__name__})
    except (OSError, UnicodeDecodeError):
        return {"available": False, "reason": "wire artifact cannot be read", "events": []}
    return {
        "available": True,
        "source_bytes": wire_path.stat().st_size,
        "source_sha256": _sha256_file(wire_path),
        "event_count": len(events),
        "truncated": len(events) >= MAX_EVENT_RECORDS,
        "events": events,
    }


def _validation_payload(row: sqlite3.Row) -> dict[str, Any]:
    raw = row["validation_issues_json"]
    try:
        issues = json.loads(str(raw or "[]"))
    except json.JSONDecodeError:
        issues = []
    if not isinstance(issues, list):
        issues = []
    bounded: list[dict[str, str]] = []
    for issue in issues[:64]:
        if isinstance(issue, dict):
            bounded.append(
                {
                    "path": str(issue.get("path", ""))[:512],
                    "message": str(issue.get("message", ""))[:2000],
                }
            )
    return {
        "status": str(row["status"] or "unknown"),
        "lifecycle_status": str(row["lifecycle_status"] or "unknown"),
        "error_kind": row["error_kind"],
        "error_detail": row["error_detail"],
        "terminal_reason": row["terminal_reason"],
        "issue_count": int(row["validation_issue_count"] or len(bounded)),
        "issues": bounded,
    }


def _turn_prompt_payload(request: Any) -> dict[str, Any]:
    if not isinstance(request, dict) or not isinstance(request.get("prompt"), str):
        return {}
    try:
        payload = json.loads(str(request["prompt"]))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _turn_objective(request: Any) -> str:
    payload = _turn_prompt_payload(request)
    return _truncate(payload.get("objective") or "Unavailable", 4000)


def _turn_available_actions(request: Any) -> str:
    payload = _turn_prompt_payload(request)
    applicable = payload.get("applicable_action_description")
    actions = applicable.get("actions", []) if isinstance(applicable, dict) else []
    names = [
        str(action.get("type", action.get("action_type", "unknown")))
        for action in actions[:64]
        if isinstance(action, dict)
    ]
    return _truncate(names, 6000)


def _turn_validation_summary(validation: dict[str, Any]) -> str:
    issues = validation.get("issues", [])
    if not isinstance(issues, list) or not issues:
        return f"{validation.get('status', 'unknown')} (none)"
    return _truncate(
        [
            f"{issue.get('path', '')}: {issue.get('message', '')}"
            for issue in issues
            if isinstance(issue, dict)
        ],
        6000,
    )


def _turn_request_markdown(
    *,
    experiment_id: str,
    sequence: int,
    row: sqlite3.Row,
    request: Any,
    validation: dict[str, Any],
    provenance: dict[str, Any],
) -> str:
    if not isinstance(request, dict):
        request = {}
    prompt = request.get("prompt") if isinstance(request, dict) else None
    if not isinstance(prompt, str):
        prompt = "Unavailable: the historical request did not retain prompt text."
    try:
        prompt_payload = json.loads(prompt)
    except (TypeError, json.JSONDecodeError):
        prompt_payload = {}
    if not isinstance(prompt_payload, dict):
        prompt_payload = {}
    objective = prompt_payload.get("objective") or "Unavailable"
    target = prompt_payload.get("immutable_target")
    target_statement = (
        target.get("statement") if isinstance(target, dict) else "Unavailable"
    )
    applicable = prompt_payload.get("applicable_action_description")
    available_actions = applicable.get("actions", []) if isinstance(applicable, dict) else []
    action_names = [
        str(action.get("type", action.get("action_type", "unknown")))
        for action in available_actions[:64]
        if isinstance(action, dict)
    ]
    state = prompt_payload.get("director_state_v2")
    state_summary = {
        key: state.get(key)
        for key in ("schema_version", "active_lane_count", "available_lane_slots")
        if isinstance(state, dict) and key in state
    }
    ranking = prompt_payload.get("proposal_ranking_contract")
    return "\n".join(
        [
            f"# Director turn {sequence:04d} request",
            "",
            f"- Experiment: `{experiment_id}`",
            f"- Turn record: `{row['turn_record_id']}`",
            f"- Campaign: `{row['campaign_id']}`",
            f"- Started: `{row['started_at']}`",
            f"- Lifecycle: `{row['lifecycle_status']}`",
            f"- Director model: `{provenance.get('model') or 'unavailable'}`",
            f"- Reasoning effort: `{provenance.get('effort') or 'unavailable'}`",
            "",
            "## Scientific task and committed request",
            "",
            f"- Objective: {_truncate(objective, 4000)}",
            f"- Immutable target: {_truncate(target_statement, 4000)}",
            f"- Committed state summary: `{_truncate(state_summary, 6000)}`",
            f"- Available actions: `{_truncate(action_names, 6000)}`",
            f"- Executable target registry: `{request.get('executable_target_registry_artifact_ref') or 'unavailable'}`",
            f"- Proposal ranking contract: `{_truncate(ranking, 4000)}`",
            "",
            "## Full committed prompt",
            "",
            _truncate(prompt, 70_000),
            "",
            "## Request identity",
            "",
            f"- Snapshot: `{row['snapshot_id']}`",
            f"- Trigger: `{row['trigger_id']}`",
            f"- Request SHA-256: `{row['request_sha256'] or 'unavailable'}`",
            "",
            "## Validation at request projection",
            "",
            f"- Status: `{validation['status']}`",
            f"- Issues: `{validation['issue_count']}`",
            "",
            "Raw request: [request.json](request.json)",
            "Raw records: [raw/](raw/)",
        ]
    ) + "\n"


def _turn_response_markdown(
    *,
    experiment_id: str,
    sequence: int,
    row: sqlite3.Row,
    response: Any,
    validation: dict[str, Any],
    usage: dict[str, Any],
) -> str:
    response = response if isinstance(response, dict) else {}
    actions = response.get("actions")
    if not isinstance(actions, list):
        actions = []
    hypotheses = response.get("hypothesis_updates")
    if not isinstance(hypotheses, list):
        hypotheses = []
    action_lines = []
    for action in actions[:64]:
        if isinstance(action, dict):
            target = action.get("target_lane_id") or action.get("target") or "none"
            parameters = action.get("parameters") or {}
            action_lines.append(
                f"- `{action.get('type', 'unknown')}`: "
                f"target `{target}`; parameters `{_truncate(parameters, 3000)}`; "
                f"{_truncate(action.get('rationale', ''), 1000)}"
            )
    hypothesis_lines = []
    for update in hypotheses[:64]:
        hypothesis_lines.append(f"- {_truncate(update, 1000)}")
    issue_lines = [
        f"- `{item['path']}`: {item['message']}"
        for item in validation["issues"]
    ]
    if not action_lines:
        action_lines = ["- None retained."]
    if not hypothesis_lines:
        hypothesis_lines = ["- None retained."]
    if not issue_lines:
        issue_lines = ["- None retained."]
    return "\n".join(
        [
            f"# Director turn {sequence:04d} response",
            "",
            f"- Experiment: `{experiment_id}`",
            f"- Turn record: `{row['turn_record_id']}`",
            f"- Completed: `{row['completed_at'] or 'in progress'}`",
            f"- Status: `{row['status']}` / `{row['lifecycle_status']}`",
            "",
            "## Assessment",
            "",
            _truncate(response.get("campaign_assessment", "Unavailable"), 12_000),
            "",
            "## Hypothesis updates",
            "",
            *hypothesis_lines,
            "",
            "## Actions",
            "",
            *action_lines,
            "",
            "## Next review",
            "",
            _truncate(response.get("next_review", "Unavailable"), 8_000),
            "",
            "## Validation",
            "",
            f"- Issue count: `{validation['issue_count']}`",
            *issue_lines,
            f"- Error kind: `{validation['error_kind'] or 'none'}`",
            f"- Error detail: `{validation['error_detail'] or 'none'}`",
            "",
            "## Usage",
            "",
            _truncate(usage, 4_000),
            "",
            "Raw response: [response.json](response.json)",
            "Raw records: [raw/](raw/)",
        ]
    ) + "\n"


def _capsule_sequence_map(capsules: Path) -> dict[str, int]:
    mapping: dict[str, int] = {}
    if not capsules.is_dir():
        return mapping
    for directory in capsules.iterdir():
        if not directory.is_dir():
            continue
        match = _TURN_DIRECTORY.fullmatch(directory.name)
        if match is None:
            continue
        provenance = _read_json(directory / "provenance.json")
        if isinstance(provenance, dict) and isinstance(
            provenance.get("turn_record_id"), str
        ):
            mapping[str(provenance["turn_record_id"])] = int(match.group(1))
    return mapping


def _experiment_id(workspace: Path) -> str:
    state = _read_json(workspace / ".sglab" / "experiment-state.json")
    if isinstance(state, dict) and isinstance(state.get("experiment_id"), str):
        return str(state["experiment_id"])
    return workspace.name


def _turn_rows(database: Path) -> list[sqlite3.Row]:
    uri = f"{database.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=2)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "app_server_turns" not in tables:
            return []
        return list(
            connection.execute(
                """
                SELECT t.*, s.model_requested AS model, s.effort_requested AS effort,
                       s.context_mode AS session_context_mode
                FROM app_server_turns AS t
                LEFT JOIN app_server_sessions AS s
                  ON s.session_record_id=t.session_record_id
                ORDER BY COALESCE(t.started_at, ''), t.turn_record_id
                """
            )
        )
    finally:
        connection.close()


def _copy_referenced_artifacts(
    *,
    request: Any,
    campaign_dir: Path,
    raw_dir: Path,
    refs: dict[str, dict[str, Any]],
) -> None:
    if not isinstance(request, dict):
        return
    referenced = raw_dir / "referenced"
    for key, value in sorted(request.items()):
        if not key.endswith("_artifact_ref") or not isinstance(value, str):
            continue
        source = _safe_relative(campaign_dir, value)
        target_name = re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".bin"
        refs[key] = _copy_or_mark(source, referenced / target_name, value)


def _copy_row_artifacts(
    *,
    row: sqlite3.Row,
    campaign_dir: Path,
    raw_dir: Path,
    refs: dict[str, dict[str, Any]],
) -> None:
    """Copy durable row-level references without changing their bytes."""

    for key in ("evidence_registry_artifact_ref",):
        try:
            value = row[key]
        except (IndexError, KeyError):
            value = None
        if not isinstance(value, str) or not value:
            continue
        source = _safe_relative(campaign_dir, value)
        target_name = re.sub(r"[^A-Za-z0-9_.-]", "_", key) + ".bin"
        refs[key] = _copy_or_mark(
            source,
            raw_dir / "referenced" / target_name,
            value,
        )


def _project_turn(
    *,
    workspace: Path,
    experiment_id: str,
    sequence: int,
    row: sqlite3.Row,
) -> dict[str, Any]:
    campaign_dir = workspace / "research-campaigns" / str(row["campaign_id"])
    capsule = workspace / "artifacts" / "director-turns" / f"turn-{sequence:04d}"
    capsule.mkdir(parents=True, exist_ok=True)
    request_ref = row["request_artifact_ref"]
    response_ref = row["response_artifact_ref"]
    wire_ref = row["wire_log_artifact_ref"]
    request_source = _safe_relative(campaign_dir, request_ref)
    response_source = _safe_relative(campaign_dir, response_ref)
    wire_source = _safe_relative(campaign_dir, wire_ref)
    request = _read_json(request_source)
    response = _read_json(response_source)
    validation = _validation_payload(row)
    usage = {
        "input_tokens": row["input_tokens"],
        "cached_input_tokens": row["cached_input_tokens"],
        "output_tokens": row["output_tokens"],
        "reasoning_output_tokens": row["reasoning_output_tokens"],
        "total_tokens": row["total_tokens"],
        "wall_seconds": row["wall_seconds"],
        "raw_usage": _read_json(None),
    }
    raw_usage = row["raw_usage_json"]
    if raw_usage:
        try:
            usage["raw_usage"] = json.loads(str(raw_usage))
        except json.JSONDecodeError:
            usage["raw_usage"] = {"available": False, "reason": "invalid stored usage JSON"}
    provenance = {
        "schema_version": CAPSULE_SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "campaign_id": row["campaign_id"],
        "turn_record_id": row["turn_record_id"],
        "sequence": sequence,
        "snapshot_id": row["snapshot_id"],
        "trigger_id": row["trigger_id"],
        "thread_id": row["thread_id"],
        "turn_id": row["turn_id"],
        "model": row["model"],
        "effort": row["effort"],
        "context_mode": row["session_context_mode"],
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "request_reference": request_ref,
        "request_sha256": row["request_sha256"],
        "response_reference": response_ref,
        "response_sha256": row["response_sha256"],
        "wire_reference": wire_ref,
        "wire_sha256": row["wire_log_sha256"],
        "raw_records_authoritative": True,
    }
    _copy_or_mark(request_source, capsule / "request.json", request_ref)
    _copy_or_mark(response_source, capsule / "response.json", response_ref)
    raw_dir = capsule / "raw"
    _copy_or_mark(request_source, raw_dir / "request.json", request_ref)
    _copy_or_mark(response_source, raw_dir / "response.json", response_ref)
    _copy_or_mark(wire_source, raw_dir / "wire.jsonl", wire_ref)
    referenced: dict[str, dict[str, Any]] = {}
    _copy_referenced_artifacts(
        request=request,
        campaign_dir=campaign_dir,
        raw_dir=raw_dir,
        refs=referenced,
    )
    _copy_row_artifacts(
        row=row,
        campaign_dir=campaign_dir,
        raw_dir=raw_dir,
        refs=referenced,
    )
    provenance["referenced_artifacts"] = referenced
    events = _event_projection(wire_source)
    _write_json(capsule / "validation.json", validation)
    _write_json(capsule / "usage.json", usage)
    _write_json(capsule / "provenance.json", provenance)
    _write_json(capsule / "events.json", events)
    _write_text(
        capsule / "request.md",
        _turn_request_markdown(
            experiment_id=experiment_id,
            sequence=sequence,
            row=row,
            request=request,
            validation=validation,
            provenance=provenance,
        ),
    )
    _write_text(
        capsule / "response.md",
        _turn_response_markdown(
            experiment_id=experiment_id,
            sequence=sequence,
            row=row,
            response=response,
            validation=validation,
            usage=usage,
        ),
    )
    _write_text(
        capsule / "README.md",
        "\n".join(
            [
                f"# Director turn {sequence:04d}",
                "",
                f"Experiment: `{experiment_id}`",
                f"Turn record: `{row['turn_record_id']}`",
                f"Status: `{row['status']}` / `{row['lifecycle_status']}`",
                f"Director model: `{row['model'] or 'unavailable'}`",
                f"Reasoning effort: `{row['effort'] or 'unavailable'}`",
                f"Started: `{row['started_at']}`; completed: `{row['completed_at'] or 'in progress'}`",
                "",
                f"Scientific objective: `{_turn_objective(request)}`",
                f"Available actions: `{_turn_available_actions(request)}`",
                f"Executable targets: `{request.get('executable_target_registry_artifact_ref') if isinstance(request, dict) else 'unavailable'}`",
                f"Assessment: `{_truncate(response.get('campaign_assessment', 'Unavailable'), 4000) if isinstance(response, dict) else 'Unavailable'}`",
                f"Validation issues: `{_turn_validation_summary(validation)}`",
                f"Wall seconds: `{usage.get('wall_seconds') if usage.get('wall_seconds') is not None else 'unavailable'}`",
                "",
                "The request capsule contains the committed scientific task, state summary, available actions, and executable-target references.",
                "The response capsule contains the assessment, hypotheses, actions, targets, parameters, and next review.",
                "",
                "Readable views:",
                "- [request.md](request.md)",
                "- [response.md](response.md)",
                "- [validation.json](validation.json)",
                "- [usage.json](usage.json)",
                "- [provenance.json](provenance.json)",
                "- [events.json](events.json)",
                "",
                "Raw request/response/wire records are copied under [raw/](raw/).",
                "The SQLite row and original campaign artifacts remain authoritative.",
            ]
        )
        + "\n",
    )
    return {
        "sequence": sequence,
        "directory": str(capsule.relative_to(workspace)),
        "turn_record_id": str(row["turn_record_id"]),
        "status": str(row["status"]),
        "lifecycle_status": str(row["lifecycle_status"]),
        "started_at": row["started_at"],
        "completed_at": row["completed_at"],
        "validation_issue_count": validation["issue_count"],
    }


def project_director_turn_capsules(
    workspace: Path,
    *,
    campaign_id: str | None = None,
) -> dict[str, Any]:
    """Project all retained App Server turns into stable readable capsules."""

    workspace = workspace.resolve()
    database = workspace / "results.sqlite3"
    capsules = workspace / "artifacts" / "director-turns"
    capsules.mkdir(parents=True, exist_ok=True)
    rows = [
        row for row in _turn_rows(database)
        if campaign_id is None or str(row["campaign_id"]) == campaign_id
    ] if database.is_file() else []
    mapping = _capsule_sequence_map(capsules)
    used = set(mapping.values())
    next_sequence = max(used, default=0) + 1
    records: list[dict[str, Any]] = []
    for row in rows:
        turn_id = str(row["turn_record_id"])
        sequence = mapping.get(turn_id)
        if sequence is None:
            sequence = next_sequence
            next_sequence += 1
        records.append(
            _project_turn(
                workspace=workspace,
                experiment_id=_experiment_id(workspace),
                sequence=sequence,
                row=row,
            )
        )
    records.sort(key=lambda item: int(item["sequence"]))
    latest = records[-1] if records else None
    return {
        "schema_version": CAPSULE_SCHEMA_VERSION,
        "experiment_id": _experiment_id(workspace),
        "turn_count": len(records),
        "turns": records,
        "latest": latest,
        "artifact_index": str((workspace / "artifacts" / "README.md").relative_to(workspace)),
    }


def write_artifact_index(
    workspace: Path,
    *,
    projection: dict[str, Any] | None = None,
) -> Path:
    """Write the concise workspace artifact index and return its path."""

    workspace = workspace.resolve()
    root = workspace / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    if projection is None:
        projection = project_director_turn_capsules(workspace)
    lines = [
        "# HEG artifact index",
        "",
        f"Experiment: `{projection.get('experiment_id', workspace.name)}`",
        "",
        "## Imported proposal-ranking archive",
        "",
        "- [Mutation Forge Stage 4R archive](../../../artifacts/proposal-ranking/mutation_forge_stage4r_v1/README.md)",
        "- [Import manifest](../../../artifacts/proposal-ranking/mutation_forge_stage4r_v1/import-manifest.json)",
        "- [Champion proof](../../../artifacts/proposal-ranking/mutation_forge_stage4r_v1/champion.json)",
        "",
        "## Director turn capsules",
        "",
        f"Total projected turns: **{projection.get('turn_count', 0)}**",
        "",
    ]
    turns = projection.get("turns", [])
    if not isinstance(turns, list) or not turns:
        lines.append("No Director turns are retained yet.")
    else:
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            directory = str(turn.get("directory", ""))
            relative_directory = (
                directory.removeprefix("artifacts/")
                if directory.startswith("artifacts/")
                else directory
            )
            lines.append(
                f"- [turn-{int(turn.get('sequence', 0)):04d}]("
                f"{relative_directory}/README.md) — `{turn.get('status')}` / "
                f"`{turn.get('lifecycle_status')}`, validation issues: "
                f"`{turn.get('validation_issue_count', 0)}`; "
                f"[request]({relative_directory}/request.md), "
                f"[response]({relative_directory}/response.md), "
                f"[validation]({relative_directory}/validation.json), "
                f"[usage]({relative_directory}/usage.json)"
            )
    latest = projection.get("latest")
    latest_directory = (
        str(latest.get("directory", "")).removeprefix("artifacts/")
        if isinstance(latest, dict)
        else ""
    )
    lines.extend(
        [
            "",
            "## Latest turn",
            "",
            (
                f"Latest capsule: [{latest_directory}/README.md]"
                f"({latest_directory}/README.md)"
                if isinstance(latest, dict)
                else "No Director turn has been projected yet."
            ),
            "",
            "Raw JSON/JSONL remains available in each capsule's `raw/` directory; these readable files are a bounded projection, not a replacement for the authoritative records.",
        ]
    )
    path = root / "README.md"
    _write_text(path, "\n".join(lines) + "\n")
    return path


def migrate_workspace_artifacts(
    workspace: Path,
    *,
    campaign_id: str | None = None,
) -> dict[str, Any]:
    """Idempotently project turns and refresh the workspace index."""

    workspace = workspace.resolve()
    # The index is workspace-scoped and must never hide an older campaign's
    # capsules merely because a newly completed turn supplied a campaign ID.
    # Keep the keyword for callers that already pass it; all retained turns
    # are projected into the same chronological index.
    del campaign_id
    projection = project_director_turn_capsules(workspace)
    index = write_artifact_index(workspace, projection=projection)
    projection["artifact_index"] = str(index.relative_to(workspace))
    if isinstance(projection.get("latest"), dict):
        projection["latest_turn_capsule"] = str(
            Path(str(projection["latest"]["directory"]))
        )
    else:
        projection["latest_turn_capsule"] = None
    return projection


def artifact_paths(workspace: Path) -> dict[str, str | None]:
    """Return only stable public paths for CLI/API projections."""

    root = workspace.resolve() / "artifacts"
    latest: Path | None = None
    capsules = root / "director-turns"
    if capsules.is_dir():
        directories = [
            path for path in capsules.iterdir()
            if path.is_dir() and _TURN_DIRECTORY.fullmatch(path.name)
        ]
        if directories:
            latest = max(directories, key=lambda path: int(_TURN_DIRECTORY.fullmatch(path.name).group(1)))
    return {
        "artifact_index": "artifacts/README.md" if (root / "README.md").is_file() else None,
        "latest_turn_capsule": (
            str(latest.relative_to(workspace)) if latest is not None else None
        ),
    }


def verify_import_manifest(archive: Path) -> dict[str, Any]:
    """Verify the byte-preserving Mutation Forge import without rewriting it.

    The manifest intentionally excludes its own bytes from ``files`` because a
    self-hash would be circular.  It is nevertheless required to exist, while
    ``generated_files`` enumerates the other human-facing proof documents.
    Returning a report (rather than raising) lets a doctor command and focused
    tests show every missing, changed, duplicated, or extra path at once.
    """

    root = archive.resolve()
    manifest_path = root / "import-manifest.json"
    errors: list[dict[str, Any]] = []
    if not manifest_path.is_file():
        return {
            "ok": False,
            "archive": str(root),
            "errors": [{"kind": "missing", "path": "import-manifest.json"}],
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return {
            "ok": False,
            "archive": str(root),
            "errors": [{"kind": "invalid_manifest", "detail": str(error)}],
        }
    entries = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(entries, list):
        return {
            "ok": False,
            "archive": str(root),
            "errors": [{"kind": "invalid_manifest", "detail": "files is not a list"}],
        }
    expected: dict[str, dict[str, Any]] = {}
    duplicate_paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            errors.append({"kind": "invalid_entry", "entry": entry})
            continue
        relative = str(entry["path"])
        candidate = _safe_relative(root, relative)
        if candidate is None or relative in {"", "."}:
            errors.append({"kind": "unsafe_path", "path": relative})
            continue
        if relative in expected:
            duplicate_paths.append(relative)
        expected[relative] = entry
    if duplicate_paths:
        errors.append({"kind": "duplicate", "paths": sorted(set(duplicate_paths))})
    generated = manifest.get("generated_files", [])
    if not isinstance(generated, list):
        generated = []
        errors.append({"kind": "invalid_manifest", "detail": "generated_files is not a list"})
    generated_paths = {
        str(value) for value in generated if isinstance(value, str) and value
    }
    generated_hashes = manifest.get("generated_file_hashes", {})
    if not isinstance(generated_hashes, dict):
        generated_hashes = {}
        errors.append(
            {"kind": "invalid_manifest", "detail": "generated_file_hashes is not a map"}
        )
    allowed_paths = set(expected) | generated_paths | {"import-manifest.json"}
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    for relative in sorted(set(expected) - actual_paths):
        errors.append({"kind": "missing", "path": relative})
    for relative in sorted(actual_paths - allowed_paths):
        errors.append({"kind": "extra", "path": relative})
    for relative, expected_sha in sorted(generated_hashes.items()):
        path = root / str(relative)
        if not path.is_file():
            errors.append({"kind": "missing", "path": str(relative)})
            continue
        actual_sha = _sha256_file(path)
        if actual_sha != expected_sha:
            errors.append(
                {
                    "kind": "changed",
                    "path": str(relative),
                    "expected": expected_sha,
                    "actual": actual_sha,
                }
            )
    changed: list[str] = []
    for relative, entry in sorted(expected.items()):
        path = root / relative
        if not path.is_file():
            continue
        actual_size = path.stat().st_size
        actual_sha = _sha256_file(path)
        if actual_size != entry.get("bytes") or actual_sha != entry.get("sha256"):
            changed.append(relative)
    if changed:
        errors.append({"kind": "changed", "paths": changed})
    champion = manifest.get("champion") if isinstance(manifest, dict) else None
    if isinstance(champion, dict):
        source_relative = champion.get("source_path")
        source_path = _safe_relative(root, source_relative)
        if source_path is None or not source_path.is_file():
            errors.append({"kind": "champion_missing", "path": source_relative})
        else:
            source_sha = _sha256_file(source_path)
            if source_sha != champion.get("source_sha256"):
                errors.append(
                    {
                        "kind": "champion_changed",
                        "path": source_relative,
                        "expected": champion.get("source_sha256"),
                        "actual": source_sha,
                    }
                )
        policy_reference = champion.get("heg_policy_path")
        if isinstance(policy_reference, str) and len(root.parents) > 2:
            policy_path = (root.parents[2] / policy_reference).resolve()
            if policy_path.is_file() and source_path is not None and source_path.is_file():
                policy_sha = _sha256_file(policy_path)
                source_sha = _sha256_file(source_path)
                if policy_sha != source_sha:
                    errors.append(
                        {
                            "kind": "champion_policy_mismatch",
                            "path": policy_reference,
                            "expected": source_sha,
                            "actual": policy_sha,
                        }
                    )
    report = {
        "ok": not errors,
        "archive": str(root),
        "manifest": str(manifest_path),
        "imported_file_count": len(entries),
        "actual_file_count": len(actual_paths),
        "imported_bytes": manifest.get("imported_bytes"),
        "duplicate_paths": sorted(set(duplicate_paths)),
        "errors": errors,
    }
    return report
