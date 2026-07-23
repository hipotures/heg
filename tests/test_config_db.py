import sqlite3
import tempfile
import unittest
from pathlib import Path

from sglab.config import merge_config
from sglab.db import SCHEMA_VERSION, connect


class ConfigAndDatabaseTests(unittest.TestCase):
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
