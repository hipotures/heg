from __future__ import annotations

from pathlib import Path
import asyncio
import stat
import sys
import tempfile
import unittest

from sglab.research.app_server_client import (
    AppServerClient,
    AppServerConfig,
    AppServerError,
)
from sglab.research.auth import (
    auth_is_imported,
    import_authorized_auth,
    prepare_private_directories,
)
from sglab.cli import build_parser


FAKE = Path(__file__).parent / "fixtures" / "fake_app_server.py"


class AppServerClientTests(unittest.IsolatedAsyncioTestCase):
    def config(self, root: Path, mode: str = "normal") -> AppServerConfig:
        return AppServerConfig(
            application_data=root,
            launcher=(sys.executable, str(FAKE), f"--fake-mode={mode}"),
            disabled_features=(),
            request_timeout_seconds=1,
            turn_timeout_seconds=0.2 if mode == "timeout" else 2,
            usage_wait_seconds=0.2,
        )

    async def test_persisted_structured_turn_and_usage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = AppServerClient(self.config(Path(directory)))
            await client.start()
            self.assertEqual(client.disabled_skill_paths, ("/fake/SKILL.md",))
            session = await client.start_thread("Return only JSON.")
            self.assertEqual(session.thread_id, "thread-test")
            self.assertEqual(session.session_id, "session-test")
            self.assertEqual(session.thread_path, "/fake/rollout.jsonl")
            result = await client.turn(
                session,
                "test",
                output_schema={
                    "type": "object",
                    "required": ["ok"],
                    "properties": {"ok": {"type": "boolean"}},
                },
            )
            self.assertEqual(result.parsed, {"ok": True})
            self.assertEqual(result.usage.total_tokens, 15)
            self.assertEqual(result.usage.input_tokens, 10)
            self.assertEqual(result.usage.cached_input_tokens, 3)
            self.assertEqual(result.usage.output_tokens, 5)
            self.assertEqual(result.usage.reasoning_output_tokens, 2)
            self.assertEqual(client.unsupported_server_requests, 1)
            self.assertIn(b"turn/completed", client.wire_bytes)
            resumed = await client.resume_thread(
                session.thread_id, "Return only JSON."
            )
            self.assertTrue(resumed.resumed)
            self.assertEqual(resumed.thread_id, session.thread_id)
            await client.close()

    async def test_malformed_json_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            async with AppServerClient(
                self.config(Path(directory), "malformed")
            ) as client:
                session = await client.start_thread("Return only JSON.")
                with self.assertRaisesRegex(AppServerError, "malformed"):
                    await client.turn(session, "test")

    async def test_timeout_kills_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = AppServerClient(self.config(Path(directory), "timeout"))
            await client.start()
            session = await client.start_thread("Return only JSON.")
            with self.assertRaisesRegex(AppServerError, "timed out"):
                await client.turn(session, "test")
            self.assertIsNone(client.process)


class DirectorAuthTests(unittest.TestCase):
    def test_auth_import_is_explicit_and_copies_only_auth(self) -> None:
        with tempfile.TemporaryDirectory() as source_dir, tempfile.TemporaryDirectory() as data_dir:
            source = Path(source_dir)
            (source / "auth.json").write_text('{"secret":"not-logged"}\n')
            (source / "config.toml").write_text("model='must-not-copy'\n")
            destination = import_authorized_auth(source, Path(data_dir))
            self.assertTrue(auth_is_imported(Path(data_dir)))
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
            self.assertFalse((destination.parent / "config.toml").exists())
            home, work = prepare_private_directories(Path(data_dir))
            self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(work.stat().st_mode), 0o700)

    def test_ai_director_commands_require_explicit_paths(self) -> None:
        parser = build_parser()
        auth = parser.parse_args(
            [
                "ai-director",
                "auth-import",
                "--workspace",
                "/tmp/work",
                "--from-codex-home",
                "/tmp/codex",
            ]
        )
        self.assertEqual(auth.ai_director_command, "auth-import")
        preflight = parser.parse_args(
            ["ai-director", "preflight", "--workspace", "/tmp/work"]
        )
        self.assertEqual(preflight.codex, "codex")
