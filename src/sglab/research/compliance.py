from __future__ import annotations

from pathlib import Path
from typing import Any
import asyncio
import os
import sqlite3

from ..resources import run_bounded
from .app_server_client import AppServerClient, AppServerConfig
from .app_server_protocol import generate_protocol_preflight
from .inspection import inspect_persisted_sessions


USAGE_FIELDS = {
    "inputTokens",
    "cachedInputTokens",
    "cacheWriteInputTokens",
    "outputTokens",
    "reasoningOutputTokens",
    "totalTokens",
}


def _skills(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    return [
        skill
        for entry in payload.get("data", [])
        if isinstance(entry, dict)
        for skill in entry.get("skills", [])
        if isinstance(skill, dict)
    ]


def _skill_errors_empty(payload: dict[str, Any] | None) -> bool:
    return bool(
        isinstance(payload, dict)
        and isinstance(payload.get("data"), list)
        and all(
            isinstance(entry, dict)
            and isinstance(entry.get("errors"), list)
            and not entry["errors"]
            for entry in payload["data"]
        )
    )


def invalid_config_rejected(client: AppServerClient) -> bool:
    environment = os.environ.copy()
    environment.update(client.config.environment)
    environment["CODEX_HOME"] = str(client.home)
    environment["CODEX_SQLITE_HOME"] = str(client.sqlite_home)
    result = run_bounded(
        [
            *client._command(),
            "-c",
            "sglab_intentionally_unknown_config_field=true",
        ],
        timeout_seconds=10,
        output_limit_bytes=64 * 1024,
        cwd=client.work,
        environment=environment,
    )
    detail = (result.stdout + result.stderr).decode("utf-8", errors="replace").lower()
    return (
        result.returncode not in (None, 0)
        and "unknown" in detail
        and "sglab_intentionally_unknown_config_field" in detail
    )


def _opaque_thread_path_check(client: AppServerClient) -> bool:
    audit_dir = client.config.application_data.resolve() / "director" / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    opaque = client.home / "opaque-audit-location" / "payload.bin"
    opaque.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    opaque.write_bytes(b"no-model compliance audit\n")
    database_path = audit_dir / "opaque-thread-path.sqlite3"
    database = sqlite3.connect(database_path)
    try:
        database.executescript(
            """
            CREATE TABLE IF NOT EXISTS app_server_sessions (
                session_record_id TEXT,
                campaign_id TEXT,
                thread_id TEXT,
                thread_path TEXT,
                started_at TEXT,
                last_resumed_at TEXT
            );
            DELETE FROM app_server_sessions;
            """
        )
        database.execute(
            "INSERT INTO app_server_sessions VALUES (?, ?, ?, ?, ?, ?)",
            (
                "audit-session",
                "audit-campaign",
                "audit-thread",
                str(opaque),
                "now",
                None,
            ),
        )
        database.commit()
    finally:
        database.close()
    sessions = inspect_persisted_sessions(database_path, client.home)
    return (
        len(sessions) == 1
        and sessions[0].get("valid") is True
        and sessions[0].get("path") == str(opaque.resolve())
    )


async def run_no_model_compliance_audit(
    *,
    codex: str,
    application_data: Path,
) -> dict[str, Any]:
    """Exercise startup and protocol controls without starting a model turn."""

    failures: list[str] = []
    try:
        preflight = generate_protocol_preflight(codex)
    except BaseException as error:
        preflight = {}
        failures.append(f"schema preflight {type(error).__name__}: {error}")
    client = AppServerClient(
        AppServerConfig(
            application_data=application_data,
            launcher=(codex,),
            request_timeout_seconds=30,
            graceful_shutdown_seconds=3,
            termination_timeout_seconds=2,
        )
    )
    checks: dict[str, Any] = {
        "strict_config_startup": False,
        "target_version": (
            preflight.get("codex_version_output") == "codex-cli 0.145.0"
        ),
        "experimental_schema_discovery": bool(
            preflight.get("experimental_schema_discovery")
        ),
        "invalid_config_rejected": invalid_config_rejected(client),
        "skill_list_errors_empty": False,
        "all_skill_paths_absolute": False,
        "all_skills_disabled": False,
        "post_reload_active_skills": -1,
        "private_codex_home": (
            client.home.is_absolute()
            and client.home.is_dir()
            and (client.home.stat().st_mode & 0o777) == 0o700
        ),
        "separate_codex_sqlite_home": (
            client.sqlite_home.is_absolute()
            and client.sqlite_home.is_dir()
            and client.sqlite_home != client.home
            and (client.sqlite_home.stat().st_mode & 0o777) == 0o700
        ),
        "thread_path_is_opaque": False,
        "usage_schema_complete": USAGE_FIELDS.issubset(
            set(preflight.get("usage_fields", []))
        ),
        "graceful_shutdown_tested": False,
        "failures": failures,
        "ok": False,
    }
    try:
        await client.start()
        checks["strict_config_startup"] = True
        before = client.skill_list_before
        after = client.skill_list_after
        before_skills = _skills(before)
        after_skills = _skills(after)
        checks["skill_list_errors_empty"] = (
            _skill_errors_empty(before) and _skill_errors_empty(after)
        )
        checks["all_skill_paths_absolute"] = all(
            isinstance(skill.get("path"), str)
            and Path(skill["path"]).is_absolute()
            for skill in (*before_skills, *after_skills)
        )
        checks["all_skills_disabled"] = (
            client.skills_isolated
            and len(client.disabled_skill_paths) == len(before_skills)
            and all(skill.get("enabled") is not True for skill in after_skills)
        )
        checks["post_reload_active_skills"] = sum(
            skill.get("enabled") is True for skill in after_skills
        )

        checks["thread_path_is_opaque"] = _opaque_thread_path_check(client)
    except BaseException as error:
        checks["failures"].append(f"{type(error).__name__}: {error}")
    finally:
        try:
            await client.close()
        except BaseException as error:
            checks["failures"].append(
                f"shutdown {type(error).__name__}: {error}"
            )
    checks["graceful_shutdown_tested"] = client.last_shutdown_mode == "graceful"
    boolean_checks = (
        "strict_config_startup",
        "target_version",
        "experimental_schema_discovery",
        "invalid_config_rejected",
        "skill_list_errors_empty",
        "all_skill_paths_absolute",
        "all_skills_disabled",
        "private_codex_home",
        "separate_codex_sqlite_home",
        "thread_path_is_opaque",
        "usage_schema_complete",
        "graceful_shutdown_tested",
    )
    for name in boolean_checks:
        if checks[name] is not True:
            checks["failures"].append(f"{name}=false")
    if checks["post_reload_active_skills"] != 0:
        checks["failures"].append(
            "post_reload_active_skills="
            f"{checks['post_reload_active_skills']}"
        )
    checks["failures"] = list(dict.fromkeys(checks["failures"]))
    checks["ok"] = not checks["failures"]
    checks["codex_version_output"] = preflight.get("codex_version_output")
    checks["skill_audit_artifacts"] = {
        "pre_disable": str(
            application_data.resolve() / "director" / "audit" / "skills-before.json"
        ),
        "post_disable": str(
            application_data.resolve() / "director" / "audit" / "skills-after.json"
        ),
    }
    return checks
