from __future__ import annotations

from pathlib import Path
import json
import sys
import tempfile
import unittest

from sglab.research.app_server_client import (
    AppServerClient,
    AppServerConfig,
    AppServerTurnTimeout,
)
from sglab.research.context_screen import decision_context_for_snapshot
from sglab.research.director import ActiveDirector
from sglab.research.store import ResearchStore


FAKE = Path(__file__).parent / "fixtures" / "fake_app_server.py"


def timeout_snapshot() -> dict:
    return {
        "schema_version": "3.0",
        "snapshot_id": "snapshot-timeout",
        "created_at": "2026-07-24T00:00:00Z",
        "campaign": {
            "campaign_id": "campaign-timeout",
            "state": "running",
            "state_version": 0,
            "stop_mode": "until_success",
            "elapsed_seconds": 0,
            "remaining_seconds": None,
        },
        "target": {
            "target_id": "erdos_gyarfas",
            "immutable_definition_hash": "a" * 64,
            "success_authority": "M4_independent_verifier",
        },
        "lanes": [],
        "hypotheses": [],
        "global_best": None,
        "recent_actions": [],
        "available_evidence_ids": [],
    }


class IncompleteTurnLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def run_timeout_shape(
        self, root: Path, *, mode: str
    ) -> tuple[ResearchStore, ActiveDirector]:
        store = ResearchStore(root / "results.sqlite3")
        store.create_campaign(
            campaign_id="campaign-timeout",
            target="erdos_gyarfas",
            target_definition_sha256="a" * 64,
            stop_mode="until_success",
            deadline_at=None,
        )
        snapshot = timeout_snapshot()
        store.record_snapshot(
            snapshot_id="snapshot-timeout",
            campaign_id="campaign-timeout",
            campaign_state_version=0,
            high_water={},
            artifact_ref="snapshots/snapshot-timeout.json",
            artifact_sha256="b" * 64,
            payload_bytes=100,
        )
        store.record_trigger(
            trigger_id="trigger-timeout",
            campaign_id="campaign-timeout",
            campaign_state_version=0,
            reasons=["measurement"],
            first_event_at="2026-07-24T00:00:00Z",
            snapshot_id="snapshot-timeout",
        )
        client = AppServerClient(
            AppServerConfig(
                application_data=root / ".sglab",
                launcher=(
                    sys.executable,
                    str(FAKE),
                    f"--fake-mode={mode}",
                ),
                disabled_features=(),
                request_timeout_seconds=1,
                turn_timeout_seconds=0.2,
                timeout_drain_seconds=0.1,
                usage_wait_seconds=0.1,
            )
        )
        director = ActiveDirector(
            client=client,
            store=store,
            campaign_id="campaign-timeout",
            campaign_dir=root / "campaign",
            codex_version="fake",
            executable_sha256="c" * 64,
            protocol_schema_sha256="d" * 64,
        )
        await director.start()
        with self.assertRaisesRegex(AppServerTurnTimeout, "timed out"):
            await director.request_decision_once(
                snapshot=snapshot,
                trigger_id="trigger-timeout",
                context=decision_context_for_snapshot(snapshot),
            )
        await director.close()
        return store, director

    async def test_timeout_persists_started_turn_and_nullable_usage(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store, _ = await self.run_timeout_shape(
                root, mode="p2-timeout"
            )
            row = store.connection.execute(
                "SELECT * FROM app_server_turns"
            ).fetchone()
            self.assertIsNotNone(row["request_id"])
            self.assertEqual(
                row["thread_id"],
                "019f953e-5817-7c21-ae03-79c0ad6942eb",
            )
            self.assertEqual(
                row["turn_id"],
                "019f953e-e784-7241-bd0d-28b92c67570b",
            )
            self.assertEqual(row["lifecycle_status"], "timed_out")
            reasoning_ids = [
                "rs_07a914ce88aabd5b016a63a59d53a48191a3a8198fe946f174",
                "rs_07a914ce88aabd5b016a63a5a6f36c8191a70be144eec325a2",
            ]
            self.assertEqual(
                json.loads(row["reasoning_item_ids_json"]),
                reasoning_ids,
            )
            self.assertGreaterEqual(row["latest_event_sequence"], 5)
            self.assertIsNotNone(row["turn_started_at"])
            self.assertIsNone(row["response_artifact_ref"])
            self.assertIsNone(row["final_agent_item_id"])
            for field in (
                "input_tokens",
                "cached_input_tokens",
                "cache_write_input_tokens",
                "output_tokens",
                "reasoning_output_tokens",
                "total_tokens",
                "raw_usage_json",
            ):
                self.assertIsNone(row[field], field)
            wire = root / "campaign" / row["wire_log_artifact_ref"]
            self.assertTrue(wire.is_file())
            self.assertIn(b'"method":"turn/interrupt"', wire.read_bytes())
            self.assertIsNotNone(row["wire_log_sha256"])
            self.assertFalse(
                store.record_turn_event(
                    row["turn_record_id"],
                    event_sequence=row["latest_event_sequence"],
                    lifecycle_status="timed_out",
                    request_id=row["request_id"],
                    thread_id=row["thread_id"],
                    turn_id=row["turn_id"],
                    items=(
                        (reasoning_ids[0], "reasoning"),
                        (reasoning_ids[1], "reasoning"),
                    ),
                )
            )
            self.assertEqual(
                store.connection.execute(
                    "SELECT count(*) FROM app_server_turns"
                ).fetchone()[0],
                1,
            )
            database_path = store.path
            store.close()
            reopened = ResearchStore(database_path)
            try:
                retained = reopened.connection.execute(
                    "SELECT * FROM app_server_turns"
                ).fetchone()
                self.assertEqual(
                    retained["turn_id"],
                    "019f953e-e784-7241-bd0d-28b92c67570b",
                )
                self.assertEqual(
                    retained["lifecycle_status"], "timed_out"
                )
                self.assertEqual(
                    json.loads(retained["reasoning_item_ids_json"]),
                    reasoning_ids,
                )
                self.assertEqual(
                    reopened.connection.execute(
                        "PRAGMA integrity_check"
                    ).fetchone()[0],
                    "ok",
                )
            finally:
                reopened.close()

    async def test_late_abort_updates_existing_timeout_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store, _ = await self.run_timeout_shape(
                Path(directory), mode="p2-late-abort"
            )
            try:
                rows = store.connection.execute(
                    "SELECT * FROM app_server_turns"
                ).fetchall()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["lifecycle_status"], "aborted")
                self.assertIn(
                    "timeout followed by terminal status interrupted",
                    rows[0]["terminal_reason"],
                )
                self.assertEqual(
                    json.loads(rows[0]["reasoning_item_ids_json"]),
                    [
                        "rs_07a914ce88aabd5b016a63a59d53a48191a3a8198fe946f174",
                        "rs_07a914ce88aabd5b016a63a5a6f36c8191a70be144eec325a2",
                    ],
                )
                self.assertIsNone(rows[0]["total_tokens"])
            finally:
                store.close()
