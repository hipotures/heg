import sqlite3
import tempfile
import unittest
from pathlib import Path

from sglab.config import merge_config
from sglab.db import (
    ACTIVE_DIRECTOR_SCHEMA_SQL,
    BASE_SCHEMA_SQL,
    SCHEMA_VERSION,
    connect,
    insert_metrics,
    insert_run,
    prune_metrics,
)


class ConfigAndDatabaseTests(unittest.TestCase):
    def test_reviewed_m6_migration_matches_runtime_sql(self) -> None:
        reviewed = (
            Path(__file__).parents[1]
            / "sql"
            / "007_active_director.sql"
        ).read_text(encoding="utf-8")

        def normalize(value: str) -> str:
            return " ".join(
                line.strip()
                for line in value.splitlines()
                if line.strip() and not line.lstrip().startswith("--")
            )

        self.assertEqual(
            normalize(reviewed),
            normalize(ACTIVE_DIRECTOR_SCHEMA_SQL),
        )

    def test_recursive_config_merge(self) -> None:
        base = {"runtime": {"workers": 2, "queue": 4}, "name": "base"}
        merged = merge_config(base, {"runtime": {"workers": 3}})
        self.assertEqual(merged["runtime"], {"workers": 3, "queue": 4})
        self.assertEqual(base["runtime"]["workers"], 2)

    def test_database_migration_is_idempotent_and_wal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "results.sqlite3"
            connection = connect(path)
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0],
                SCHEMA_VERSION,
            )
            self.assertEqual(
                connection.execute("PRAGMA journal_mode").fetchone()[0].lower(),
                "wal",
            )
            insert_run(connection, "run", "now", "target", {}, {})
            insert_metrics(
                connection,
                (("run", str(index), index, 0, 1.0, 1) for index in range(5)),
            )
            prune_metrics(connection, max_rows=2)
            self.assertEqual(
                connection.execute("SELECT count(*) FROM run_metrics").fetchone()[0],
                2,
            )
            connection.close()
            connect(path).close()

    def test_newer_database_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "future.sqlite3"
            raw = sqlite3.connect(path)
            raw.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
            raw.close()
            with self.assertRaises(RuntimeError):
                connect(path)

    def test_schema_v7_lane_shape_is_forward_completed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy-v7.sqlite3"
            database = sqlite3.connect(path)
            database.executescript(
                """
                CREATE TABLE research_campaigns (
                    campaign_id TEXT PRIMARY KEY,
                    target TEXT NOT NULL
                );
                CREATE TABLE research_lanes (
                    lane_id TEXT PRIMARY KEY,
                    campaign_id TEXT NOT NULL,
                    state TEXT NOT NULL
                );
                INSERT INTO research_campaigns VALUES
                    ('campaign-1', 'hidden_witness');
                INSERT INTO research_lanes VALUES
                    ('lane-1', 'campaign-1', 'running');
                PRAGMA user_version=7;
                """
            )
            database.close()
            migrated = connect(path)
            columns = {
                row[1]
                for row in migrated.execute(
                    "PRAGMA table_info(research_lanes)"
                )
            }
            self.assertIn("target", columns)
            self.assertIn("parent_checkpoint_ref", columns)
            self.assertEqual(
                migrated.execute(
                    "SELECT target FROM research_lanes WHERE lane_id='lane-1'"
                ).fetchone()[0],
                "hidden_witness",
            )
            migrated.close()

    def test_v1_migration_runs_only_on_online_backup_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "original.sqlite3"
            snapshot = root / "snapshot.sqlite3"
            source = sqlite3.connect(original)
            source.executescript(BASE_SCHEMA_SQL)
            source.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
                ("legacy", "now", "erdos_gyarfas", "RUNNING", "{}", "{}"),
            )
            source.commit()
            destination = sqlite3.connect(snapshot)
            source.backup(destination)
            destination.close()
            source.close()

            migrated = connect(snapshot)
            self.assertEqual(
                migrated.execute("PRAGMA user_version").fetchone()[0],
                SCHEMA_VERSION,
            )
            self.assertEqual(
                migrated.execute("PRAGMA integrity_check").fetchone()[0],
                "ok",
            )
            self.assertEqual(
                migrated.execute(
                    "SELECT status FROM runs WHERE run_id='legacy'"
                ).fetchone()[0],
                "RUNNING",
            )
            tables = {
                row[0]
                for row in migrated.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            self.assertIn("research_campaigns", tables)
            self.assertIn("director_actions", tables)
            migrated.close()

            untouched = sqlite3.connect(original)
            self.assertEqual(untouched.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertNotIn(
                "research_campaigns",
                {
                    row[0]
                    for row in untouched.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                },
            )
            untouched.close()
