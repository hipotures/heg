from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable
import json
import sqlite3

SCHEMA_VERSION = 1


def connect(path: str | Path) -> sqlite3.Connection:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        migrate(connection)
    except BaseException:
        connection.close()
        raise
    return connection


def migrate(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"database schema {version} is newer than supported {SCHEMA_VERSION}")
    if version == 0:
        connection.executescript(
            """
            CREATE TABLE runs (
                run_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                target TEXT NOT NULL,
                status TEXT NOT NULL,
                parameters_json TEXT NOT NULL,
                environment_json TEXT NOT NULL
            );
            CREATE TABLE run_metrics (
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                recorded_at TEXT NOT NULL,
                candidates INTEGER NOT NULL,
                improvements INTEGER NOT NULL,
                candidates_per_second REAL NOT NULL,
                rss_bytes INTEGER NOT NULL
            );
            CREATE TABLE candidates (
                candidate_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                graph6 TEXT NOT NULL,
                order_n INTEGER NOT NULL,
                size_m INTEGER NOT NULL,
                score_json TEXT NOT NULL,
                verification_status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX candidates_run_score ON candidates(run_id, created_at);
            CREATE TABLE candidate_scores (
                candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
                component TEXT NOT NULL,
                value REAL NOT NULL,
                PRIMARY KEY(candidate_id, component)
            );
            CREATE TABLE artifacts (
                artifact_id INTEGER PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                candidate_id TEXT,
                kind TEXT NOT NULL,
                path TEXT NOT NULL,
                sha256 TEXT NOT NULL
            );
            CREATE TABLE verifications (
                verification_id INTEGER PRIMARY KEY,
                candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id),
                verifier TEXT NOT NULL,
                status TEXT NOT NULL,
                complete INTEGER NOT NULL,
                elapsed_seconds REAL NOT NULL,
                report_json TEXT NOT NULL
            );
            CREATE TABLE benchmarks (
                benchmark_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                report_json TEXT NOT NULL
            );
            CREATE TABLE tool_versions (
                name TEXT PRIMARY KEY,
                version TEXT,
                path TEXT
            );
            PRAGMA user_version=1;
            """
        )
        connection.commit()


def insert_run(
    connection: sqlite3.Connection,
    run_id: str,
    created_at: str,
    target: str,
    parameters: dict[str, Any],
    environment: dict[str, Any],
) -> None:
    connection.execute(
        "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
        (
            run_id,
            created_at,
            target,
            "RUNNING",
            json.dumps(parameters, sort_keys=True),
            json.dumps(environment, sort_keys=True),
        ),
    )
    connection.commit()


def set_run_status(connection: sqlite3.Connection, run_id: str, status: str) -> None:
    connection.execute("UPDATE runs SET status=? WHERE run_id=?", (status, run_id))
    connection.commit()


def insert_metrics(connection: sqlite3.Connection, rows: Iterable[tuple[Any, ...]]) -> None:
    connection.executemany("INSERT INTO run_metrics VALUES (?, ?, ?, ?, ?, ?)", rows)
    connection.commit()


def checkpoint(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA wal_checkpoint(PASSIVE)")
