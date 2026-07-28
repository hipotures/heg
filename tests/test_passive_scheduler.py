import asyncio
import json
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from queue import Queue
from unittest.mock import patch

from sglab.cli import build_parser
from sglab.db import SCHEMA_VERSION, connect
from sglab.research.campaign import (
    ResearchCampaignRunner,
    campaign_status,
    request_campaign_control,
)
from sglab.research.resume import build_resume_preview
from sglab.research.passive import (
    DeterministicReviewTrigger,
    PassiveScheduler,
)
from sglab.research.store import ResearchStore
from sglab.research.validation import DecisionContext
from sglab.web import DashboardServer


CAMPAIGN_ID = "campaign-passive-test"


def _snapshot(
    *,
    snapshot_id: str = "snapshot-passive",
    state_version: int = 0,
    lanes: list[dict] | None = None,
) -> dict:
    return {
        "snapshot_id": snapshot_id,
        "campaign": {"state_version": state_version},
        "target": {"target_id": "erdos_gyarfas"},
        "lanes": lanes or [],
        "global_best": None,
        "verification": {"jobs": []},
    }


def _context(
    *,
    snapshot_id: str = "snapshot-passive",
    lanes: list[dict] | None = None,
    maximum: int = 4,
) -> DecisionContext:
    lanes = lanes or []
    lane_versions = {
        str(lane["lane_id"]): int(lane["lane_version"])
        for lane in lanes
    }
    checkpoint_ids = frozenset(
        str(lane["checkpoint_id"])
        for lane in lanes
        if lane.get("checkpoint_id")
    )
    return DecisionContext(
        snapshot_id=snapshot_id,
        evidence_ids=frozenset(),
        lane_versions=lane_versions,
        lane_algorithms={
            str(lane["lane_id"]): str(lane["algorithm"])
            for lane in lanes
        },
        checkpoint_ids=checkpoint_ids,
        candidate_ids=frozenset(),
        max_active_lanes=maximum,
        executable_target_ids=frozenset(lane_versions) | checkpoint_ids,
    )


class PassiveSchedulerUnitTests(unittest.TestCase):
    def test_schema_16_online_backup_migrates_without_rewriting_llm_batch(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source.sqlite3"
            with ResearchStore(source_path) as store:
                store.create_campaign(
                    campaign_id=CAMPAIGN_ID,
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="until_success",
                    deadline_at=None,
                )
                store.record_snapshot(
                    snapshot_id="snapshot-legacy",
                    campaign_id=CAMPAIGN_ID,
                    campaign_state_version=0,
                    high_water={},
                    artifact_ref="snapshots/legacy.json",
                    artifact_sha256="b" * 64,
                    payload_bytes=100,
                )
                store.record_trigger(
                    trigger_id="trigger-legacy",
                    campaign_id=CAMPAIGN_ID,
                    campaign_state_version=0,
                    reasons=["bootstrap"],
                    first_event_at="2026-07-28T00:00:00Z",
                    snapshot_id="snapshot-legacy",
                )
                store.record_session(
                    record_id="session-legacy",
                    campaign_id=CAMPAIGN_ID,
                    thread_id="thread-legacy",
                    session_id=None,
                    thread_path=None,
                    parent_thread_id=None,
                    model="gpt-5.6-luna",
                    effort="high",
                    codex_version="test",
                    executable_sha256="c" * 64,
                    protocol_schema_sha256="d" * 64,
                )
                store.begin_turn(
                    turn_record_id="turn-legacy",
                    session_record_id="session-legacy",
                    campaign_id=CAMPAIGN_ID,
                    thread_id="thread-legacy",
                    snapshot_id="snapshot-legacy",
                    trigger_id="trigger-legacy",
                    request_artifact_ref="requests/legacy.json",
                    request_sha256="e" * 64,
                    wire_artifact_ref="wire/legacy.jsonl",
                )
                store.complete_turn(
                    "turn-legacy",
                    turn_id="turn-legacy",
                    status="completed_valid",
                    usage={
                        "input_tokens": 1,
                        "cached_input_tokens": 0,
                        "cache_write_input_tokens": 0,
                        "output_tokens": 1,
                        "reasoning_output_tokens": 0,
                        "total_tokens": 2,
                    },
                    wall_seconds=0.1,
                )
                store.connection.execute(
                    """
                    INSERT INTO director_action_batches
                    (decision_batch_id, campaign_id, snapshot_id, trigger_id,
                     turn_record_id, scheduler_decision_id,
                     campaign_assessment, next_review_json,
                     validation_status, response_artifact_ref,
                     response_sha256, created_at)
                    VALUES ('batch-legacy', ?, 'snapshot-legacy',
                            'trigger-legacy', 'turn-legacy', NULL,
                            'historical assessment', '{}', 'accepted',
                            'responses/legacy.json', ?, ?)
                    """,
                    (
                        CAMPAIGN_ID,
                        "f" * 64,
                        "2026-07-28T00:00:01Z",
                    ),
                )
                store.connection.commit()
                store.connection.execute("PRAGMA foreign_keys=OFF")
                store.connection.executescript(
                    """
                    BEGIN IMMEDIATE;
                    CREATE TABLE director_action_batches_v16 (
                        decision_batch_id TEXT PRIMARY KEY,
                        campaign_id TEXT NOT NULL
                            REFERENCES research_campaigns(campaign_id),
                        snapshot_id TEXT NOT NULL
                            REFERENCES director_snapshots(snapshot_id),
                        trigger_id TEXT NOT NULL
                            REFERENCES director_triggers(trigger_id),
                        turn_record_id TEXT NOT NULL
                            REFERENCES app_server_turns(turn_record_id),
                        campaign_assessment TEXT NOT NULL,
                        next_review_json TEXT NOT NULL,
                        validation_status TEXT NOT NULL,
                        response_artifact_ref TEXT,
                        response_sha256 TEXT,
                        created_at TEXT NOT NULL
                    );
                    INSERT INTO director_action_batches_v16
                    SELECT decision_batch_id, campaign_id, snapshot_id,
                           trigger_id, turn_record_id, campaign_assessment,
                           next_review_json, validation_status,
                           response_artifact_ref, response_sha256, created_at
                    FROM director_action_batches;
                    DROP TABLE director_action_batches;
                    ALTER TABLE director_action_batches_v16
                        RENAME TO director_action_batches;
                    DROP TABLE passive_scheduler_states;
                    DROP TABLE passive_scheduler_decisions;
                    ALTER TABLE research_campaigns DROP COLUMN director_mode;
                    ALTER TABLE campaign_execution_attempts
                        DROP COLUMN director_mode;
                    ALTER TABLE campaign_execution_attempts
                        DROP COLUMN previous_director_mode;
                    ALTER TABLE campaign_execution_attempts
                        DROP COLUMN mode_transition_json;
                    ALTER TABLE campaign_execution_attempts
                        DROP COLUMN contract_fingerprint;
                    PRAGMA user_version=16;
                    COMMIT;
                    """
                )
                store.connection.execute("PRAGMA foreign_keys=ON")
                backup_path = root / "snapshot.sqlite3"
                backup = sqlite3.connect(backup_path)
                store.connection.backup(backup)
                backup.close()

            migrated = connect(backup_path)
            try:
                self.assertEqual(
                    migrated.execute("PRAGMA user_version").fetchone()[0],
                    SCHEMA_VERSION,
                )
                self.assertEqual(
                    migrated.execute(
                        "PRAGMA integrity_check"
                    ).fetchone()[0],
                    "ok",
                )
                self.assertEqual(
                    migrated.execute("PRAGMA foreign_key_check").fetchall(),
                    [],
                )
                row = migrated.execute(
                    """
                    SELECT turn_record_id, scheduler_decision_id,
                           campaign_assessment, response_sha256
                    FROM director_action_batches
                    WHERE decision_batch_id='batch-legacy'
                    """
                ).fetchone()
                self.assertEqual(
                    tuple(row),
                    (
                        "turn-legacy",
                        None,
                        "historical assessment",
                        "f" * 64,
                    ),
                )
                self.assertEqual(
                    migrated.execute(
                        """
                        SELECT director_mode FROM research_campaigns
                        WHERE campaign_id=?
                        """,
                        (CAMPAIGN_ID,),
                    ).fetchone()[0],
                    "llm",
                )
            finally:
                migrated.close()

    def test_dashboard_starts_passive_mode_without_auth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = object.__new__(DashboardServer)
            server.workspace = root
            server.campaign_runner = None
            server.launch_lock = threading.Lock()
            with patch("sglab.web.Popen") as launch:
                launch.return_value.pid = 4413
                launch.return_value.poll.return_value = None
                status, result = server.start_campaign(
                    {
                        "stop_mode": "time_limit",
                        "duration": "1m",
                        "director_mode": "passive",
                        "passive_seed": 37,
                    }
                )
            self.assertEqual(status, 202)
            self.assertEqual(result["director_mode"], "passive")
            command = launch.call_args.args[0]
            self.assertIn("--director-mode", command)
            self.assertIn("passive", command)
            self.assertIn("--passive-seed", command)
            self.assertIn("37", command)

    def test_cli_and_resume_preview_make_mode_selection_explicit(self) -> None:
        parsed = build_parser().parse_args(
            [
                "research-campaign",
                "prepare",
                "--workspace",
                "/tmp/passive",
                "--time-limit",
                "1h",
                "--director-mode",
                "passive",
                "--passive-seed",
                "37",
            ]
        )
        self.assertEqual(parsed.director_mode, "passive")
        self.assertEqual(parsed.passive_seed, 37)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign_dir = root / "research-campaigns" / CAMPAIGN_ID
            campaign_dir.mkdir(parents=True)
            plan = {
                "campaign_id": CAMPAIGN_ID,
                "director_mode": "llm",
                "target": "erdos_gyarfas",
                "director": {
                    "model": "gpt-5.6-luna",
                    "reasoning_effort": "high",
                    "context_mode": "stateless_turns",
                },
                "passive_scheduler": {
                    "policy_id": "balanced_v1",
                    "policy_version": 1,
                    "seed": 37,
                },
            }
            (campaign_dir / "campaign-plan.json").write_text(
                json.dumps(plan), encoding="utf-8"
            )
            with ResearchStore(root / "results.sqlite3") as store:
                store.create_campaign(
                    campaign_id=CAMPAIGN_ID,
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="until_success",
                    deadline_at=None,
                    director_mode="llm",
                )
                store.finish_campaign(
                    CAMPAIGN_ID,
                    terminal_kind="stopped_by_operator",
                )
            preview = build_resume_preview(
                root,
                CAMPAIGN_ID,
                additional_wall_seconds=60,
                code_commit="a" * 40,
                director_mode="passive",
            )
            self.assertEqual(preview["previous_director_mode"], "llm")
            self.assertEqual(preview["requested_director_mode"], "passive")
            self.assertTrue(preview["mode_transition"]["changed"])
            with ResearchStore(root / "results.sqlite3") as store:
                with store.connection:
                    store.connection.execute(
                        """
                        UPDATE research_campaigns SET director_mode='passive'
                        WHERE campaign_id=?
                        """,
                        (CAMPAIGN_ID,),
                    )
            reverse = build_resume_preview(
                root,
                CAMPAIGN_ID,
                additional_wall_seconds=60,
                code_commit="a" * 40,
                director_mode="llm",
            )
            self.assertEqual(reverse["previous_director_mode"], "passive")
            self.assertEqual(reverse["requested_director_mode"], "llm")
            self.assertTrue(reverse["mode_transition"]["changed"])

    def test_fixed_seed_and_state_produce_identical_reviewed_actions(self) -> None:
        decisions = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as directory:
                with ResearchStore(Path(directory) / "results.sqlite3") as store:
                    store.create_campaign(
                        campaign_id=CAMPAIGN_ID,
                        target="erdos_gyarfas",
                        target_definition_sha256="a" * 64,
                        stop_mode="until_success",
                        deadline_at=None,
                        director_mode="passive",
                    )
                    scheduler = PassiveScheduler(
                        store=store,
                        campaign_id=CAMPAIGN_ID,
                        seed=91,
                    )
                    asyncio.run(scheduler.start())
                    evidence = asyncio.run(
                        scheduler.decide(
                            snapshot=_snapshot(),
                            trigger_id="trigger-passive",
                            context=_context(),
                        )
                    )
                    self.assertTrue(
                        evidence.validation.accepted,
                        evidence.validation.issues,
                    )
                    decisions.append(evidence.decision)
                    self.assertEqual(
                        store.connection.execute(
                            "SELECT count(*) FROM app_server_sessions"
                        ).fetchone()[0],
                        0,
                    )
                    self.assertEqual(
                        store.connection.execute(
                            "SELECT count(*) FROM app_server_turns"
                        ).fetchone()[0],
                        0,
                    )
        self.assertEqual(decisions[0], decisions[1])
        self.assertEqual(
            [
                action["spec"]["algorithm"]
                for action in decisions[0]["actions"]
            ],
            [
                "random_restart",
                "simulated_annealing",
                "iterated_local_search",
                "iterated_local_search_tabu",
            ],
        )

    def test_state_and_rng_lineage_are_committed_without_a_model_turn(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with ResearchStore(Path(directory) / "results.sqlite3") as store:
                store.create_campaign(
                    campaign_id=CAMPAIGN_ID,
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="until_success",
                    deadline_at=None,
                    director_mode="passive",
                )
                store.record_snapshot(
                    snapshot_id="snapshot-passive",
                    campaign_id=CAMPAIGN_ID,
                    campaign_state_version=0,
                    high_water={},
                    artifact_ref="snapshots/passive.json",
                    artifact_sha256="b" * 64,
                    payload_bytes=100,
                )
                store.record_trigger(
                    trigger_id="trigger-passive",
                    campaign_id=CAMPAIGN_ID,
                    campaign_state_version=0,
                    reasons=["bootstrap"],
                    first_event_at="2026-07-28T00:00:00Z",
                    snapshot_id="snapshot-passive",
                )
                scheduler = PassiveScheduler(
                    store=store,
                    campaign_id=CAMPAIGN_ID,
                    seed=91,
                )
                asyncio.run(scheduler.start())
                evidence = asyncio.run(
                    scheduler.decide(
                        snapshot=_snapshot(),
                        trigger_id="trigger-passive",
                        context=_context(),
                    )
                )
                statuses = store.commit_decision_batch(
                    decision_batch_id="decision-batch-passive",
                    campaign_id=CAMPAIGN_ID,
                    snapshot_id="snapshot-passive",
                    trigger_id="trigger-passive",
                    turn_record_id=None,
                    decision=evidence.decision,
                    scheduler_decision_id=evidence.source_record_id,
                    scheduler_metadata=evidence.source_metadata,
                )
                self.assertTrue(
                    all(status == "accepted" for status in statuses.values())
                )
                state = store.passive_scheduler_state(CAMPAIGN_ID)
                self.assertIsNotNone(state)
                self.assertEqual(state["state_version"], 1)
                self.assertGreater(state["rng_counter"], 0)
                self.assertEqual(
                    store.connection.execute(
                        "SELECT count(*) FROM app_server_turns"
                    ).fetchone()[0],
                    0,
                )
                batch = store.connection.execute(
                    """
                    SELECT turn_record_id, scheduler_decision_id
                    FROM director_action_batches
                    """
                ).fetchone()
                self.assertIsNone(batch["turn_record_id"])
                self.assertEqual(
                    batch["scheduler_decision_id"],
                    evidence.source_record_id,
                )
                resumed = PassiveScheduler(
                    store=store,
                    campaign_id=CAMPAIGN_ID,
                    seed=91,
                )
                asyncio.run(resumed.start())
                self.assertEqual(
                    resumed.state["rng_counter"], state["rng_counter"]
                )
                self.assertEqual(resumed.state["review_index"], 1)

    def test_commit_time_rejection_blocks_the_entire_passive_batch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with ResearchStore(Path(directory) / "results.sqlite3") as store:
                store.create_campaign(
                    campaign_id=CAMPAIGN_ID,
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="until_success",
                    deadline_at=None,
                    director_mode="passive",
                )
                store.record_snapshot(
                    snapshot_id="snapshot-passive",
                    campaign_id=CAMPAIGN_ID,
                    campaign_state_version=0,
                    high_water={},
                    artifact_ref="snapshots/passive.json",
                    artifact_sha256="b" * 64,
                    payload_bytes=100,
                )
                store.record_trigger(
                    trigger_id="trigger-passive",
                    campaign_id=CAMPAIGN_ID,
                    campaign_state_version=0,
                    reasons=["bootstrap"],
                    first_event_at="2026-07-28T00:00:00Z",
                    snapshot_id="snapshot-passive",
                )
                scheduler = PassiveScheduler(
                    store=store,
                    campaign_id=CAMPAIGN_ID,
                    seed=91,
                )
                asyncio.run(scheduler.start())
                evidence = asyncio.run(
                    scheduler.decide(
                        snapshot=_snapshot(),
                        trigger_id="trigger-passive",
                        context=_context(),
                    )
                )
                stale = evidence.decision["actions"][-1]
                stale["type"] = "restart_lane"
                stale["lane_id"] = "lane-disappeared"
                stale["expected_lane_version"] = 1
                stale["restart_spec"] = {
                    "source": "new_seed",
                    "seed": 1,
                }
                stale.pop("spec")
                statuses = store.commit_decision_batch(
                    decision_batch_id="decision-batch-passive",
                    campaign_id=CAMPAIGN_ID,
                    snapshot_id="snapshot-passive",
                    trigger_id="trigger-passive",
                    turn_record_id=None,
                    decision=evidence.decision,
                    scheduler_decision_id=evidence.source_record_id,
                    scheduler_metadata=evidence.source_metadata,
                )
                self.assertIn("rejected_stale_state", statuses.values())
                self.assertIn("blocked_scheduler_batch", statuses.values())
                self.assertNotIn("accepted", statuses.values())
                self.assertIsNone(
                    store.passive_scheduler_state(CAMPAIGN_ID)
                )
                decision = store.connection.execute(
                    """
                    SELECT validation_status, resulting_changes_json
                    FROM passive_scheduler_decisions
                    """
                ).fetchone()
                self.assertEqual(
                    decision["validation_status"], "rejected_batch"
                )
                self.assertEqual(
                    json.loads(decision["resulting_changes_json"])[
                        "action_statuses"
                    ],
                    statuses,
                )

    def test_stagnation_prefers_a_persisted_checkpoint_restart(self) -> None:
        lane = {
            "lane_id": "lane-passive",
            "lane_version": 3,
            "state": "running",
            "algorithm": "simulated_annealing",
            "checkpoint_id": "checkpoint-passive",
            "resource_share": 1.0,
            "metrics": {
                "end_high_water": 8_000,
                "best_scalar": 5.0,
                "operator_yield": 0.0,
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            with ResearchStore(Path(directory) / "results.sqlite3") as store:
                store.create_campaign(
                    campaign_id=CAMPAIGN_ID,
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="until_success",
                    deadline_at=None,
                    director_mode="passive",
                )
                scheduler = PassiveScheduler(
                    store=store,
                    campaign_id=CAMPAIGN_ID,
                    seed=91,
                )
                asyncio.run(scheduler.start())
                scheduler.state["best_scalar_by_lane"] = {
                    "lane-passive": 5.0
                }
                scheduler.state["stagnation_windows_by_lane"] = {
                    "lane-passive": 1
                }
                evidence = asyncio.run(
                    scheduler.decide(
                        snapshot=_snapshot(lanes=[lane]),
                        trigger_id="trigger-passive",
                        context=_context(lanes=[lane], maximum=1),
                    )
                )
                self.assertTrue(
                    evidence.validation.accepted,
                    evidence.validation.issues,
                )
                action = evidence.decision["actions"][0]
                self.assertEqual(action["type"], "restart_lane")
                self.assertEqual(
                    action["restart_spec"]["source"], "checkpoint"
                )
                self.assertEqual(
                    action["restart_spec"]["checkpoint_id"],
                    "checkpoint-passive",
                )
                self.assertIn(
                    "promising_checkpoint_restart",
                    evidence.source_metadata["reason_codes"],
                )

    def test_review_trigger_uses_evaluation_boundaries_only(self) -> None:
        trigger = DeterministicReviewTrigger(
            last_review_evaluations=1_000,
            candidate_delta=500,
        )
        self.assertFalse(trigger.due(total_candidates=1_499, now=10**9))
        self.assertTrue(trigger.due(total_candidates=1_500, now=0))
        batch = trigger.consume(total_candidates=1_500, now=0)
        self.assertEqual(batch.reasons, ("candidate_delta_reached",))
        self.assertEqual(trigger.last_review_evaluations, 1_500)


class PassiveCampaignIntegrationTests(unittest.TestCase):
    def test_no_credential_campaign_pauses_resumes_and_stops(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = self._start_runner(root, campaign_id=None)
            with patch(
                "sglab.research.campaign.generate_protocol_preflight",
                side_effect=AssertionError("App Server preflight was called"),
            ):
                first.start()
                observed = self._wait_for_progress(root, first)
                request_campaign_control(root, "PAUSE")
                first.join(timeout=5)
            self.assertFalse(first.is_alive())
            result_kind, result = self.results.get_nowait()
            if result_kind == "error":
                raise result
            campaign_id = str(result["campaign_id"])
            paused = campaign_status(root, campaign_id)
            self.assertEqual(paused["state"], "paused_by_operator")
            self.assertEqual(paused["director_mode"], "passive")
            self.assertGreaterEqual(
                paused["cumulative_counters"]["scheduler_decisions"], 1
            )
            self.assertEqual(paused["cumulative_counters"]["director_turns"], 0)
            self.assertEqual(paused["cumulative_counters"]["server_tokens"], 0)
            self.assertFalse(
                (
                    root
                    / ".sglab"
                    / "research-campaigns"
                    / campaign_id
                    / "attempts"
                    / paused["execution_attempts"][0]["attempt_id"]
                    / "application-data"
                ).exists()
            )
            self.assertTrue(
                all(lane["checkpoint_ref"] for lane in paused["lanes"])
            )

            previous_evaluations = int(
                paused["cumulative_counters"]["evaluations"]
            )
            second = self._start_runner(root, campaign_id=campaign_id)
            with patch(
                "sglab.research.campaign.generate_protocol_preflight",
                side_effect=AssertionError("App Server preflight was called"),
            ):
                second.start()
                self._wait_for_progress(
                    root,
                    second,
                    minimum_evaluations=previous_evaluations + 1,
                )
                request_campaign_control(root, "STOP")
                second.join(timeout=5)
            self.assertFalse(second.is_alive())
            result_kind, result = self.results.get_nowait()
            if result_kind == "error":
                raise result
            final = campaign_status(root, campaign_id)
            self.assertEqual(final["state"], "stopped_by_operator")
            self.assertEqual(len(final["execution_attempts"]), 2)
            self.assertTrue(
                all(
                    attempt["director_mode"] == "passive"
                    for attempt in final["execution_attempts"]
                )
            )
            self.assertEqual(final["cumulative_counters"]["director_turns"], 0)
            self.assertGreater(
                int(final["cumulative_counters"]["evaluations"]),
                int(observed["cumulative_counters"]["evaluations"]),
            )

    def setUp(self) -> None:
        self.results: Queue[tuple[str, object]] = Queue()

    def _start_runner(
        self, root: Path, *, campaign_id: str | None
    ) -> threading.Thread:
        def run() -> None:
            try:
                result = ResearchCampaignRunner(
                    workspace=root,
                    stop_mode="until_success",
                    campaign_id=campaign_id,
                    target="erdos_gyarfas",
                    director_mode="passive",
                    passive_seed=37,
                    poll_seconds=0.01,
                ).run()
            except BaseException as error:
                self.results.put(("error", error))
            else:
                self.results.put(("ok", result))

        return threading.Thread(target=run, daemon=True)

    @staticmethod
    def _wait_for_progress(
        root: Path,
        worker: threading.Thread,
        *,
        minimum_evaluations: int = 1,
    ) -> dict:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            status = campaign_status(root)
            if (
                int(
                    status.get("cumulative_counters", {}).get(
                        "evaluations", 0
                    )
                )
                >= minimum_evaluations
                and int(
                    status.get("cumulative_counters", {}).get(
                        "scheduler_decisions", 0
                    )
                )
                >= 1
            ):
                return status
            if not worker.is_alive():
                break
            time.sleep(0.02)
        raise AssertionError("passive campaign did not publish progress")


if __name__ == "__main__":
    unittest.main()
