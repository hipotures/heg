import asyncio
import json
import os
import shutil
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sglab.cli import build_parser
from sglab.research.campaign import (
    CampaignPlanError,
    PRODUCTION_CONTEXT_MODE,
    PRODUCTION_DIRECTOR_EFFORT,
    PRODUCTION_DIRECTOR_MODEL,
    PRODUCTION_MAXIMUM_DIRECTOR_TURNS,
    ResearchCampaignRunner,
    _score_runtime_provenance,
    campaign_attempt_application_data,
    campaign_status,
    load_prepared_campaign_plan,
    parse_duration,
    prepare_campaign_plan,
    request_campaign_control,
)
from sglab.research.store import ResearchStore
from sglab.resource_accounting import EXPECTED_APP_SERVER_WRAPPERS


class CampaignOperatorContractTests(unittest.TestCase):
    def test_score_runtime_provenance_has_one_fixed_implementation(
        self,
    ) -> None:
        provenance = _score_runtime_provenance()
        self.assertEqual(
            set(provenance),
            {
                "implementation",
                "early_exit_enabled",
                "duplicate_key_scheme",
                "score_worker",
            },
        )
        self.assertEqual(provenance["implementation"], "cpp")
        self.assertTrue(provenance["early_exit_enabled"])
        self.assertEqual(
            provenance["duplicate_key_scheme"], "delta_local_v2"
        )

    def test_prepare_persists_exact_non_auth_campaign_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "workspace.json").write_text(
                json.dumps(
                    {
                        "workspace_kind": "first_real_graph_campaign",
                        "synthetic_data": False,
                    }
                ),
                encoding="utf-8",
            )
            with ResearchStore(workspace / "results.sqlite3"):
                pass
            plan = prepare_campaign_plan(
                workspace,
                duration_seconds=3600,
            )
            self.assertEqual(
                plan["director"]["model"],
                PRODUCTION_DIRECTOR_MODEL,
            )
            self.assertEqual(
                plan["director"]["reasoning_effort"],
                PRODUCTION_DIRECTOR_EFFORT,
            )
            self.assertEqual(
                plan["director"]["context_mode"],
                PRODUCTION_CONTEXT_MODE.value,
            )
            self.assertEqual(
                plan["director"]["maximum_turns_including_replans"],
                PRODUCTION_MAXIMUM_DIRECTOR_TURNS,
            )
            self.assertEqual(
                plan["decision_policy"]["valid_actions"],
                "execute",
            )
            self.assertEqual(
                plan["search_limits"]["maximum_resource_share_per_lane"],
                1.0,
            )
            self.assertEqual(
                plan["search_limits"]["maximum_aggregate_resource_share"],
                float(plan["search_limits"]["maximum_active_lanes"]),
            )
            self.assertFalse(
                plan["scientific_contract"]["fixed_experiment_sequence"]
            )
            loaded = load_prepared_campaign_plan(
                workspace,
                campaign_id=plan["campaign_id"],
                expected_fingerprint=plan["plan_fingerprint"],
            )
            self.assertEqual(loaded, plan)
            status = campaign_status(workspace, plan["campaign_id"])
            self.assertEqual(status["state"], "prepared")
            self.assertFalse(status["auth_imported"])
            self.assertEqual(status["turns"], [])
            self.assertEqual(status["lanes"], [])

    def test_prepared_plan_tamper_and_wrong_fingerprint_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "workspace.json").write_text(
                json.dumps(
                    {
                        "workspace_kind": "first_real_graph_campaign",
                        "synthetic_data": False,
                    }
                ),
                encoding="utf-8",
            )
            with ResearchStore(workspace / "results.sqlite3"):
                pass
            plan = prepare_campaign_plan(
                workspace,
                duration_seconds=3600,
            )
            with self.assertRaisesRegex(
                CampaignPlanError,
                "authorized fingerprint",
            ):
                load_prepared_campaign_plan(
                    workspace,
                    expected_fingerprint="0" * 64,
                )
            plan_path = (
                workspace
                / "research-campaigns"
                / plan["campaign_id"]
                / "campaign-plan.json"
            )
            changed = json.loads(plan_path.read_text(encoding="utf-8"))
            changed["director"]["model"] = "different"
            plan_path.write_text(
                json.dumps(changed),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                CampaignPlanError,
                "fingerprint mismatch",
            ):
                load_prepared_campaign_plan(workspace)

    def test_prepared_campaign_requires_auth_before_state_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "workspace.json").write_text(
                json.dumps(
                    {
                        "workspace_kind": "first_real_graph_campaign",
                        "synthetic_data": False,
                    }
                ),
                encoding="utf-8",
            )
            with ResearchStore(workspace / "results.sqlite3"):
                pass
            plan = prepare_campaign_plan(
                workspace,
                duration_seconds=3600,
            )
            with self.assertRaisesRegex(
                RuntimeError,
                "authentication is not imported",
            ):
                ResearchCampaignRunner(
                    workspace=workspace,
                    stop_mode="time_limit",
                    duration_seconds=3600,
                    campaign_id=plan["campaign_id"],
                    maximum_director_turns=plan["director"][
                        "maximum_cycles"
                    ],
                    context_mode=plan["director"]["context_mode"],
                    prepared_plan=plan,
                ).run()
            with ResearchStore(workspace / "results.sqlite3") as store:
                self.assertEqual(
                    store.campaign(plan["campaign_id"])["state"],
                    "prepared",
                )
                self.assertEqual(
                    store.connection.execute(
                        "SELECT count(*) FROM app_server_turns"
                    ).fetchone()[0],
                    0,
                )

    def test_campaign_runtime_accepts_expected_wrapper_symlinks(self) -> None:
        codex = shutil.which("codex")
        if codex is None:
            self.skipTest("installed codex is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "workspace.json").write_text(
                json.dumps(
                    {
                        "workspace_kind": "first_real_graph_campaign",
                        "synthetic_data": False,
                    }
                ),
                encoding="utf-8",
            )
            with ResearchStore(workspace / "results.sqlite3"):
                pass
            plan = prepare_campaign_plan(
                workspace,
                duration_seconds=3600,
            )
            arg0 = (
                workspace
                / ".sglab"
                / "research-campaigns"
                / plan["campaign_id"]
                / "runtime-groups"
                / "director"
                / "director"
                / "codex-home"
                / "tmp"
                / "arg0"
                / "codex-arg0-test"
            )
            arg0.mkdir(parents=True)
            target = Path(codex).resolve()
            for name in EXPECTED_APP_SERVER_WRAPPERS:
                os.symlink(target, arg0 / name)
            runner = ResearchCampaignRunner(
                workspace=workspace,
                stop_mode="time_limit",
                duration_seconds=3600,
                campaign_id=plan["campaign_id"],
                maximum_director_turns=plan["director"][
                    "maximum_cycles"
                ],
                context_mode=plan["director"]["context_mode"],
                prepared_plan=plan,
            )
            campaign_dir = (
                workspace
                / "research-campaigns"
                / plan["campaign_id"]
            )
            runner._sample_runtime_resources(
                plan["campaign_id"],
                campaign_dir,
                stage="test",
                force=True,
            )
            telemetry = json.loads(
                (
                    campaign_dir
                    / "director"
                    / "runtime-resource-telemetry.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(telemetry["enforcement"], "continue")
            self.assertEqual(
                {
                    row["classification"]
                    for row in telemetry["symlinks"]
                },
                {"expected_runtime_wrapper"},
            )

    def test_resumed_attempt_accepts_expected_wrapper_symlinks(self) -> None:
        codex = shutil.which("codex")
        if codex is None:
            self.skipTest("installed codex is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "workspace.json").write_text(
                json.dumps(
                    {
                        "workspace_kind": "first_real_graph_campaign",
                        "synthetic_data": False,
                    }
                ),
                encoding="utf-8",
            )
            with ResearchStore(workspace / "results.sqlite3"):
                pass
            plan = prepare_campaign_plan(
                workspace,
                duration_seconds=3600,
            )
            attempt_id = "execution-attempt-wrapper-test"
            application_data = campaign_attempt_application_data(
                workspace,
                plan["campaign_id"],
                attempt_id,
            )
            arg0 = (
                application_data
                / "director"
                / "codex-home"
                / "tmp"
                / "arg0"
                / "codex-arg0-test"
            )
            arg0.mkdir(parents=True)
            target = Path(codex).resolve()
            for name in EXPECTED_APP_SERVER_WRAPPERS:
                os.symlink(target, arg0 / name)
            runner = ResearchCampaignRunner(
                workspace=workspace,
                stop_mode="time_limit",
                duration_seconds=3600,
                campaign_id=plan["campaign_id"],
                maximum_director_turns=plan["director"][
                    "maximum_cycles"
                ],
                context_mode=plan["director"]["context_mode"],
                prepared_plan=plan,
            )
            runner._attempt_private_root = application_data.parent
            runner._sample_runtime_resources(
                plan["campaign_id"],
                workspace
                / "research-campaigns"
                / plan["campaign_id"],
                stage="test",
                force=True,
            )
            telemetry = json.loads(
                (
                    workspace
                    / "research-campaigns"
                    / plan["campaign_id"]
                    / "director"
                    / "runtime-resource-telemetry.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(telemetry["enforcement"], "continue")
            self.assertEqual(
                {
                    row["classification"]
                    for row in telemetry["symlinks"]
                },
                {"expected_runtime_wrapper"},
            )

    def test_normal_start_accepts_exactly_one_stop_mode_and_no_tuning(self) -> None:
        parser = build_parser()
        time_args = parser.parse_args(
            [
                "research-campaign",
                "start",
                "--workspace",
                "/tmp/example",
                "--time-limit",
                "24h",
            ]
        )
        self.assertEqual(time_args.time_limit, "24h")
        success_args = parser.parse_args(
            [
                "research-campaign",
                "start",
                "--workspace",
                "/tmp/example",
                "--until-success",
            ]
        )
        self.assertTrue(success_args.until_success)
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "research-campaign",
                    "start",
                    "--workspace",
                    "/tmp/example",
                    "--time-limit",
                    "1h",
                    "--until-success",
                ]
            )
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "research-campaign",
                    "start",
                    "--workspace",
                    "/tmp/example",
                    "--time-limit",
                    "1h",
                    "--workers",
                    "8",
                ]
            )

    def test_duration_and_control_contracts_are_bounded(self) -> None:
        self.assertEqual(parse_duration("2h"), 7200)
        self.assertEqual(parse_duration("1d"), 86400)
        for invalid in ("", "0s", "366d", "many"):
            with self.assertRaises(ValueError):
                parse_duration(invalid)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            first = request_campaign_control(workspace, "PAUSE")
            self.assertEqual(first["version"], 1)
            with self.assertRaises(ValueError):
                request_campaign_control(workspace, "RESUME")
            with self.assertRaises(ValueError):
                request_campaign_control(workspace, "SHELL")

    def test_missing_explicit_auth_fails_before_campaign_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            with self.assertRaisesRegex(RuntimeError, "authentication is not imported"):
                ResearchCampaignRunner(
                    workspace=workspace,
                    stop_mode="time_limit",
                    duration_seconds=1,
                ).run()
            self.assertFalse((workspace / "results.sqlite3").exists())


class CampaignStateTests(unittest.TestCase):
    def test_operational_terminal_states_cannot_claim_m4_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            with ResearchStore(workspace / "results.sqlite3") as store:
                store.create_campaign(
                    campaign_id="deadline",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="time_limit",
                    deadline_at="2026-07-24T12:00:00Z",
                )
                self.assertTrue(
                    store.finish_campaign(
                        "deadline",
                        terminal_kind="completed_deadline_reached",
                    )
                )
                self.assertFalse(
                    store.finish_campaign(
                        "deadline",
                        terminal_kind="stopped_by_operator",
                    )
                )
                store.create_campaign(
                    campaign_id="until-success",
                    target="erdos_gyarfas",
                    target_definition_sha256="b" * 64,
                    stop_mode="until_success",
                    deadline_at=None,
                )
                store.create_lane(
                    lane_id="lane-1",
                    campaign_id="until-success",
                    target="erdos_gyarfas",
                    parent_lane_id=None,
                    parent_checkpoint_ref=None,
                    action_id="bootstrap",
                    algorithm="simulated_annealing",
                    graph_family="connected_cubic",
                    parameters={"order": 8},
                    seed_lineage=[1],
                    resource_share=1.0,
                    lease_expires_at=None,
                )
                store.mark_lane_running("lane-1")
                version = store.set_campaign_coordination_state(
                    "until-success",
                    expected_version=0,
                    state="paused_by_operator",
                )
                lane_state = store.connection.execute(
                    "SELECT state FROM research_lanes WHERE lane_id='lane-1'"
                ).fetchone()[0]
                self.assertEqual(lane_state, "paused")
                store.set_campaign_coordination_state(
                    "until-success",
                    expected_version=version,
                    state="running",
                )
                with self.assertRaises(RuntimeError):
                    store.finish_campaign(
                        "until-success",
                        terminal_kind="completed_deadline_reached",
                    )
                with self.assertRaises(ValueError):
                    store.finish_campaign(
                        "until-success",
                        terminal_kind="succeeded_certified_counterexample",
                    )
            status = campaign_status(workspace, "deadline")
            self.assertEqual(status["state"], "completed_deadline_reached")
            self.assertEqual(status["target"], "erdos_gyarfas")
            self.assertEqual(status["verification"]["certified"], 0)


class _FakeDirector:
    def __init__(self, *, fail: bool = False, delay: float = 0):
        self.fail = fail
        self.delay = delay
        self.closed = False
        self.resume_thread_id = None

    async def start(self, *, resume_thread_id=None, parent_thread_id=None):
        self.resume_thread_id = resume_thread_id
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("simulated provider outage")
        return object()

    async def close(self):
        self.closed = True


class _Pump:
    def __init__(self):
        self.calls = 0

    def pump_events(self):
        self.calls += 1


class ProviderRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_bounded_recovery_retries_without_controller_takeover(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            store.create_campaign(
                campaign_id="campaign-1",
                target="erdos_gyarfas",
                target_definition_sha256="a" * 64,
                stop_mode="until_success",
                deadline_at=None,
            )
            current = _FakeDirector()
            attempts = iter((True, True, False))
            created = []

            def factory():
                director = _FakeDirector(fail=next(attempts))
                created.append(director)
                return director

            pump = _Pump()
            runner = ResearchCampaignRunner(
                workspace=root,
                stop_mode="until_success",
                poll_seconds=0.001,
            )
            recovered = await runner._recover_director(
                current=current,  # type: ignore[arg-type]
                factory=factory,  # type: ignore[arg-type]
                store=store,
                campaign_id="campaign-1",
                orchestrator=pump,  # type: ignore[arg-type]
                retry_backoff_seconds=0.001,
            )
            self.assertIs(recovered, created[-1])
            self.assertTrue(current.closed)
            self.assertTrue(all(item.closed for item in created[:-1]))
            self.assertFalse(created[-1].closed)
            self.assertGreater(pump.calls, 0)
            store.close()

    async def test_expired_lane_lease_aborts_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "campaign.sqlite3")
            store.create_campaign(
                campaign_id="campaign-1",
                target="erdos_gyarfas",
                target_definition_sha256="a" * 64,
                stop_mode="until_success",
                deadline_at=None,
            )
            expired = (
                datetime.now(UTC) - timedelta(seconds=1)
            ).isoformat(timespec="seconds").replace("+00:00", "Z")
            store.create_lane(
                lane_id="lane-1",
                campaign_id="campaign-1",
                target="erdos_gyarfas",
                parent_lane_id=None,
                parent_checkpoint_ref=None,
                action_id="bootstrap",
                algorithm="simulated_annealing",
                graph_family="connected_cubic",
                parameters={"order": 8},
                seed_lineage=[1],
                resource_share=1,
                lease_expires_at=expired,
            )
            store.mark_lane_running("lane-1")
            runner = ResearchCampaignRunner(
                workspace=root,
                stop_mode="until_success",
                poll_seconds=0.001,
            )
            with self.assertRaisesRegex(RuntimeError, "policy lease expired"):
                await runner._recover_director(
                    current=_FakeDirector(),  # type: ignore[arg-type]
                    factory=lambda: _FakeDirector(delay=0.05),  # type: ignore[arg-type]
                    store=store,
                    campaign_id="campaign-1",
                    orchestrator=_Pump(),  # type: ignore[arg-type]
                    retry_backoff_seconds=0.001,
                )
            store.close()


if __name__ == "__main__":
    unittest.main()
