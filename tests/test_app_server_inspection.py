from pathlib import Path
import sqlite3
import tempfile
import unittest

from sglab.research.inspection import (
    inspect_persisted_sessions,
    validate_thread_path,
)


class AppServerInspectionTests(unittest.TestCase):
    def test_inspection_uses_opaque_sqlite_thread_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "private-runtime"
            opaque = runtime / "not-a-session-layout" / "opaque.data"
            opaque.parent.mkdir(parents=True)
            opaque.write_text('{"type":"session_meta"}\n', encoding="utf-8")
            database_path = root / "results.sqlite3"
            database = sqlite3.connect(database_path)
            database.execute(
                """
                CREATE TABLE app_server_sessions (
                    session_record_id TEXT,
                    campaign_id TEXT,
                    thread_id TEXT,
                    thread_path TEXT,
                    started_at TEXT,
                    last_resumed_at TEXT
                )
                """
            )
            database.execute(
                "INSERT INTO app_server_sessions VALUES (?, ?, ?, ?, ?, ?)",
                ("session-1", "campaign-1", "thread-1", str(opaque), "now", None),
            )
            database.commit()
            database.close()

            sessions = inspect_persisted_sessions(database_path, runtime)
            self.assertEqual(len(sessions), 1)
            self.assertTrue(sessions[0]["valid"])
            self.assertEqual(sessions[0]["path"], str(opaque))

    def test_thread_path_must_exist_inside_private_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "private-runtime"
            runtime.mkdir()
            outside = root / "outside.jsonl"
            outside.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "escapes"):
                validate_thread_path(str(outside), runtime)
            with self.assertRaisesRegex(ValueError, "absolute"):
                validate_thread_path("relative.jsonl", runtime)
