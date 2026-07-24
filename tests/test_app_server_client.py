from __future__ import annotations

from pathlib import Path
import asyncio
import json
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
            self.assertEqual(result.usage.cache_write_input_tokens, 4)
            self.assertEqual(result.usage.output_tokens, 5)
            self.assertEqual(result.usage.reasoning_output_tokens, 2)
            self.assertEqual(result.usage.raw["total"]["totalTokens"], 15)
            self.assertEqual(result.final_agent_item_id, "item-1")
            self.assertEqual(client.unsupported_server_requests, 1)
            self.assertIn(b"turn/completed", client.wire_bytes)
            taken = client.take_wire_bytes()
            self.assertIn(b"turn/completed", taken)
            self.assertEqual(client.wire_bytes, b"")
            resumed = await client.resume_thread(
                session.thread_id, "Return only JSON."
            )
            self.assertTrue(resumed.resumed)
            self.assertEqual(resumed.thread_id, session.thread_id)
            self.assertEqual(await client.compact_thread(resumed), {})
            await client.close()
            self.assertEqual(client.last_shutdown_mode, "graceful")
            self.assertTrue(
                (
                    Path(directory) / "director" / "audit" / "skills-before.json"
                ).is_file()
            )
            post = Path(directory) / "director" / "audit" / "skills-after.json"
            self.assertFalse(
                json.loads(post.read_text())["data"][0]["skills"][0]["enabled"]
            )

    async def test_usage_grace_keeps_newest_event(self) -> None:
        expected = {
            "no-usage": None,
            "normal": 15,
            "partial-final-usage": 15,
            "duplicate-usage": 16,
        }
        for mode, total in expected.items():
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                client = AppServerClient(self.config(Path(directory), mode))
                await client.start()
                session = await client.start_thread("Return only JSON.")
                result = await client.turn(session, "test")
                self.assertEqual(
                    result.usage.total_tokens if result.usage else None,
                    total,
                )
                if mode == "duplicate-usage":
                    self.assertEqual(result.usage.input_tokens, 11)
                    self.assertEqual(result.usage.cache_write_input_tokens, 6)
                await client.close()

    async def test_skill_errors_and_relative_paths_block_threads(self) -> None:
        for mode, message in (
            ("skill-errors", "returned errors"),
            ("relative-skill", "not absolute"),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                client = AppServerClient(self.config(Path(directory), mode))
                try:
                    with self.assertRaisesRegex(AppServerError, message):
                        await client.start()
                    self.assertFalse(client.skills_isolated)
                finally:
                    await client.close()

    async def test_inconsistent_item_id_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            async with AppServerClient(
                self.config(Path(directory), "bad-item-correlation")
            ) as client:
                session = await client.start_thread("Return only JSON.")
                with self.assertRaisesRegex(AppServerError, "unknown itemId"):
                    await client.turn(session, "test")

    async def test_command_is_strict_and_has_no_invalid_view_image_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = AppServerClient(self.config(Path(directory)))
            command = client._command()
            self.assertIn("--strict-config", command)
            self.assertNotIn("tools.view_image=false", command)
            self.assertNotEqual(client.home, client.sqlite_home)
            self.assertTrue(client.home.is_absolute())
            self.assertTrue(client.sqlite_home.is_absolute())

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
            home, sqlite_home, work = prepare_private_directories(Path(data_dir))
            self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(sqlite_home.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(work.stat().st_mode), 0o700)
            self.assertEqual(len({home, sqlite_home, work}), 3)

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
