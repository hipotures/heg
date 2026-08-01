from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from sglab.cli import build_parser, main
from sglab.research.campaign import (
    CampaignPlanError,
    campaign_status,
    load_prepared_campaign_plan,
    prepare_campaign_plan,
)
from sglab.research.catalog import (
    REVIEWED_PROPOSAL_RANKING_CATALOG_ID,
    action_catalog,
)
from sglab.research.export import export_campaign
from sglab.research.lanes import LaneManager, LaneSpec
from sglab.research.passive import PassiveScheduler
from sglab.research.store import ResearchStore
from sglab.research.validation import DecisionContext, validate_decision
from sglab.research.providers import SyntheticControlProvider
from sglab.research.resume import CampaignResumeError, campaign_plan
from sglab.web import create_server


CATALOG_ID = REVIEWED_PROPOSAL_RANKING_CATALOG_ID


def _workspace(root: Path) -> Path:
    (root / "workspace.json").write_text(
        json.dumps(
            {
                "workspace_kind": "first_real_graph_campaign",
                "synthetic_data": False,
            }
        ),
        encoding="utf-8",
    )
    with ResearchStore(root / "results.sqlite3"):
        pass
    return root


def _decision(
    *,
    algorithm: str = "simulated_annealing",
    parameters: dict | None = None,
    action_type: str = "start_lane",
) -> dict:
    if parameters is None:
        parameters = {
            "order": 20,
            "batch_candidates": 1000,
            "witness_cap": 64,
            "temperature": 1.0,
            "cooling": 0.995,
            "restart_threshold": 1000,
            "mutation_weights": {
                "uniform_two_edge_switch": 0.5,
                "forbidden_cycle_break_switch": 0.5,
            },
        }
    common = {
        "action_id": "activation-action",
        "type": action_type,
        "priority": 50,
        "hypothesis_ids": [],
        "evidence_ids": [],
        "rationale": "bounded activation test",
        "expected_effect": "one reviewed lane",
        "evaluation_window": {
            "max_wall_seconds": 30,
            "max_candidate_delta": 1000,
        },
        "idempotency_key": "activation-action-key",
        "lease_seconds": 60,
        "fallback": {"on_precondition_failure": "reject"},
    }
    if action_type == "start_lane":
        common["spec"] = {
            "algorithm": algorithm,
            "graph_family": "connected_cubic",
            "seed": 7,
            "parameters": parameters,
            "resource_share": 0.5,
        }
    else:
        common.update(
            {
                "lane_id": "lane-1",
                "expected_lane_version": 1,
                "patch": parameters,
            }
        )
    return {
        "schema_version": "1.0",
        "snapshot_id": "activation-snapshot",
        "campaign_assessment": "activation test",
        "hypothesis_updates": [],
        "actions": [common],
        "next_review": {
            "min_wall_seconds": 10,
            "max_wall_seconds": 30,
            "candidate_delta": 1000,
            "events": ["lane_failure"],
        },
    }


def _context(
    *,
    ranking: str | None = None,
    algorithm: str | None = None,
) -> DecisionContext:
    lane_versions = {"lane-1": 1} if algorithm is not None else {}
    return DecisionContext(
        snapshot_id="activation-snapshot",
        evidence_ids=frozenset(),
        lane_versions=lane_versions,
        lane_algorithms={"lane-1": algorithm} if algorithm else {},
        checkpoint_ids=frozenset(),
        candidate_ids=frozenset(),
        max_active_lanes=4,
        executable_target_ids=frozenset(lane_versions),
        proposal_ranking_catalog_id=ranking,
    )


class ProposalRankingActivationTests(unittest.TestCase):
    def test_action_catalog_keeps_random_restart_unranked(self) -> None:
        parameters = action_catalog()["algorithm_parameters"]
        self.assertNotIn("proposal_ranking", parameters["random_restart"])
        for algorithm in (
            "simulated_annealing",
            "iterated_local_search",
            "iterated_local_search_tabu",
        ):
            self.assertIn("proposal_ranking", parameters[algorithm])

    def test_dashboard_api_projects_and_forwards_reviewed_ranking(self) -> None:
        class _FakeProcess:
            pid = 4217

            def poll(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            auth = root / ".sglab" / "director" / "codex-home" / "auth.json"
            auth.parent.mkdir(parents=True)
            auth.write_text("{}\n", encoding="utf-8")
            server = create_server(root, "127.0.0.1", 0)
            payload = {
                "stop_mode": "time_limit",
                "duration": "1h",
                "director_mode": "llm",
                "passive_seed": 9,
                "proposal_ranking": CATALOG_ID,
            }
            with patch("sglab.web.Popen", return_value=_FakeProcess()) as popen:
                status, response = server.start_campaign(payload)
            self.assertEqual(status, 202)
            self.assertEqual(response["proposal_ranking"], CATALOG_ID)
            self.assertTrue(response["proposal_ranking_enabled"])
            command = popen.call_args.args[0]
            self.assertIn("--proposal-ranking", command)
            self.assertEqual(command[command.index("--proposal-ranking") + 1], CATALOG_ID)
            server.campaign_runner = None
            passive_status, passive_response = server.start_campaign(
                {**payload, "director_mode": "passive"}
            )
            self.assertEqual(passive_status, 400)
            self.assertIn("requires LLM", passive_response["error"])
            invalid_status, invalid_response = server.start_campaign(
                {**payload, "proposal_ranking": "arbitrary-source.py"}
            )
            self.assertEqual(invalid_status, 400)
            self.assertIn("reviewed catalog", invalid_response["error"])
            server.server_close()

    def test_cli_flag_plan_fingerprint_and_projections(self) -> None:
        parser = build_parser()
        parsed = parser.parse_args(
            [
                "research-campaign",
                "prepare",
                "--workspace",
                "/tmp/activation-workspace",
                "--time-limit",
                "1h",
                "--proposal-ranking",
                CATALOG_ID,
            ]
        )
        self.assertEqual(parsed.proposal_ranking, CATALOG_ID)
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "research-campaign",
                    "prepare",
                    "--workspace",
                    "/tmp/activation-workspace",
                    "--time-limit",
                    "1h",
                    "--proposal-ranking",
                    "arbitrary-policy.py",
                ]
            )
        with tempfile.TemporaryDirectory() as directory:
            root = _workspace(Path(directory))
            plan = prepare_campaign_plan(
                root,
                duration_seconds=3600,
                director_mode="llm",
                proposal_ranking=CATALOG_ID,
            )
            self.assertEqual(plan["proposal_ranking"], CATALOG_ID)
            self.assertEqual(
                load_prepared_campaign_plan(
                    root,
                    expected_fingerprint=plan["plan_fingerprint"],
                ),
                plan,
            )
            status = campaign_status(root, plan["campaign_id"])
            self.assertTrue(status["proposal_ranking_enabled"])
            self.assertEqual(status["proposal_ranking"], CATALOG_ID)
            output = root / "campaign.zip"
            with ResearchStore(root / "results.sqlite3") as store:
                manifest = export_campaign(
                    store=store,
                    campaign_id=plan["campaign_id"],
                    campaign_dir=root / "research-campaigns" / plan["campaign_id"],
                    output=output,
                )
            self.assertEqual(manifest["proposal_ranking"], CATALOG_ID)
            self.assertTrue(manifest["proposal_ranking_enabled"])
            self.assertEqual(manifest["plan_fingerprint"], plan["plan_fingerprint"])

    def test_unknown_plan_value_fails_before_campaign_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _workspace(Path(directory))
            with self.assertRaises(CampaignPlanError):
                prepare_campaign_plan(
                    root,
                    duration_seconds=3600,
                    proposal_ranking="not-a-reviewed-id",
                )
            self.assertFalse((root / "prepared-research-campaign.json").exists())
            with ResearchStore(root / "results.sqlite3") as store:
                self.assertEqual(
                    store.connection.execute(
                        "SELECT count(*) FROM research_campaigns"
                    ).fetchone()[0],
                    0,
                )

    def test_plan_fingerprint_detects_ranking_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _workspace(Path(directory))
            plan = prepare_campaign_plan(
                root,
                duration_seconds=3600,
                director_mode="llm",
                proposal_ranking=CATALOG_ID,
            )
            plan_path = root / "research-campaigns" / plan["campaign_id"] / "campaign-plan.json"
            tampered = dict(plan)
            tampered["proposal_ranking"] = None
            plan_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaises(CampaignPlanError):
                load_prepared_campaign_plan(root)
            with self.assertRaises(CampaignResumeError):
                campaign_plan(root, plan["campaign_id"])

    def test_default_plan_and_passive_portfolio_remain_unranked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _workspace(Path(directory))
            plan = prepare_campaign_plan(root, duration_seconds=3600)
            self.assertIsNone(plan["proposal_ranking"])
            status = campaign_status(root, plan["campaign_id"])
            self.assertFalse(status["proposal_ranking_enabled"])
            with ResearchStore(root / "results.sqlite3") as store:
                store.create_campaign(
                    campaign_id="passive-default",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="until_success",
                    deadline_at=None,
                    director_mode="passive",
                )
                scheduler = PassiveScheduler(
                    store=store,
                    campaign_id="passive-default",
                    seed=3,
                )
                decision, _, _, _ = scheduler._decision(
                    {
                        "snapshot_id": "activation-snapshot",
                        "campaign": {"state_version": 0},
                        "target": {"target_id": "erdos_gyarfas"},
                        "lanes": [],
                        "global_best": None,
                        "verification": {"jobs": []},
                    },
                    _context(),
                )
                self.assertTrue(
                    all(
                        "proposal_ranking"
                        not in action.get("spec", {}).get("parameters", {})
                        for action in decision["actions"]
                        if action["type"] == "start_lane"
                    )
                )

    def test_director_validation_binds_campaign_and_blocks_patch(self) -> None:
        enabled = _decision(
            parameters={
                "order": 20,
                "batch_candidates": 1000,
                "witness_cap": 64,
                "proposal_ranking": CATALOG_ID,
            }
        )
        self.assertTrue(validate_decision(enabled, _context(ranking=CATALOG_ID)).accepted)
        omitted = _decision()
        rejected = validate_decision(omitted, _context(ranking=CATALOG_ID))
        self.assertFalse(rejected.accepted)
        self.assertTrue(any("proposal_ranking" in issue.path for issue in rejected.issues))
        disabled = validate_decision(enabled, _context())
        self.assertFalse(disabled.accepted)
        random_ranked = _decision(
            algorithm="random_restart",
            parameters={
                "order": 20,
                "batch_candidates": 1000,
                "witness_cap": 64,
                "proposal_ranking": CATALOG_ID,
            },
        )
        self.assertFalse(validate_decision(random_ranked, _context(ranking=CATALOG_ID)).accepted)
        patch = _decision(
            action_type="patch_lane",
            parameters={"proposal_ranking": CATALOG_ID},
        )
        self.assertFalse(
            validate_decision(
                patch,
                _context(ranking=CATALOG_ID, algorithm="simulated_annealing"),
            ).accepted
        )

    def test_ranker_activation_requires_llm_director_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _workspace(Path(directory))
            with self.assertRaises(CampaignPlanError):
                prepare_campaign_plan(
                    root,
                    duration_seconds=3600,
                    director_mode="passive",
                    proposal_ranking=CATALOG_ID,
                )

    def test_cli_prepare_upgrades_a_fresh_workspace_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "workspace" / "ranked"
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "research-campaign",
                            "prepare",
                            "--workspace",
                            str(root),
                            "--time-limit",
                            "1h",
                            "--director-mode",
                            "llm",
                            "--proposal-ranking",
                            CATALOG_ID,
                        ]
                    ),
                    0,
                )
            marker = json.loads((root / "workspace.json").read_text())
            self.assertEqual(
                marker["workspace_kind"], "first_real_graph_campaign"
            )
            self.assertFalse(marker["synthetic_data"])
            plan = json.loads(output.getvalue())
            self.assertEqual(plan["proposal_ranking"], CATALOG_ID)

    def test_init_kind_writes_the_supported_first_real_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "workspace"
            with redirect_stdout(StringIO()):
                self.assertEqual(
                    main(
                        [
                            "init",
                            "--workspace",
                            str(root),
                            "--kind",
                            "first-real-graph-campaign",
                        ]
                    ),
                    0,
                )
            marker = json.loads((root / "workspace.json").read_text())
            self.assertEqual(
                marker["workspace_kind"], "first_real_graph_campaign"
            )
            self.assertFalse(marker["synthetic_data"])

    def test_fresh_marker_upgrade_rejects_unrelated_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "workspace"
            root.mkdir()
            (root / "operator-notes.txt").write_text("do not overwrite\n")
            with self.assertRaises(ValueError):
                main(
                    [
                        "init",
                        "--workspace",
                        str(root),
                        "--kind",
                        "first-real-graph-campaign",
                    ]
                )
            self.assertFalse((root / "workspace.json").exists())

    def test_experiment_run_one_key_creates_and_starts_default_unranked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            (home / ".codex").mkdir(parents=True)
            (home / ".codex" / "auth.json").write_text("{}\n")
            config = root / "experiment.toml"
            config.write_text(
                "[experiment]\n"
                "id = \"heg-ranked-001\"\n",
                encoding="utf-8",
            )
            output = StringIO()

            class _FakeProcess:
                pid = 987654

            with patch.dict(os.environ, {"HOME": str(home)}), patch(
                "sglab.cli.Popen", return_value=_FakeProcess()
            ) as launch, redirect_stdout(output):
                self.assertEqual(
                    main(["experiment", "run", "--config", str(config)]),
                    0,
                )
            report = json.loads(output.getvalue())
            self.assertEqual(report["experiment_id"], "heg-ranked-001")
            self.assertFalse(report["proposal_ranking_enabled"])
            self.assertIn("research-campaign", launch.call_args.args[0])
            workspace = root / "workspace" / "heg-ranked-001"
            marker = json.loads((workspace / "workspace.json").read_text())
            self.assertFalse(marker["synthetic_data"])
            state = json.loads(
                (workspace / ".sglab" / "experiment-state.json").read_text()
            )
            self.assertEqual(state["experiment_id"], "heg-ranked-001")
            self.assertIsNone(state["proposal_ranking"])

    def test_experiment_run_defaults_to_local_experiment_toml(self) -> None:
        parsed = build_parser().parse_args(["experiment", "run"])
        self.assertEqual(parsed.config, "./experiment.toml")
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            os.chdir(directory)
            try:
                with self.assertRaisesRegex(SystemExit, "experiment.toml"):
                    main(["experiment", "run"])
            finally:
                os.chdir(previous)

    def test_experiment_run_ranker_is_explicit_and_persistent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            auth_home = root / "codex"
            auth_home.mkdir()
            (auth_home / "auth.json").write_text("{}\n")
            config = root / "experiment.toml"
            config.write_text(
                "[experiment]\n"
                "id = \"heg-ranked-001\"\n"
                "[search]\n"
                f"proposal_ranking = \"{CATALOG_ID}\"\n"
                "[director]\n"
                f"codex_home = \"{auth_home}\"\n",
                encoding="utf-8",
            )

            class _FakeProcess:
                pid = 987655

            with patch("sglab.cli.Popen", return_value=_FakeProcess()):
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(
                        main(["experiment", "run", "--config", str(config)]),
                        0,
                    )
            report = json.loads(output.getvalue())
            self.assertEqual(report["proposal_ranking"], CATALOG_ID)
            self.assertTrue(report["proposal_ranking_enabled"])
            workspace = root / "workspace" / "heg-ranked-001"
            plan = load_prepared_campaign_plan(workspace)
            self.assertEqual(plan["proposal_ranking"], CATALOG_ID)

    def test_doctor_makes_one_bounded_call_and_reaps_worker(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["proposal-ranking", "doctor"]), 0)
        report = json.loads(output.getvalue())
        self.assertTrue(report["ok"])
        self.assertEqual(report["worker_after_call"]["calls"], 1)
        self.assertEqual(report["worker_after_call"]["failures"], 0)
        self.assertTrue(report["clean_shutdown"])
        self.assertTrue(report["no_orphan"])

    def test_short_cli_created_llm_campaign_starts_ranked_lane(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = _workspace(Path(directory))
            prepared_output = StringIO()
            with redirect_stdout(prepared_output):
                self.assertEqual(
                    main(
                        [
                            "research-campaign",
                            "prepare",
                            "--workspace",
                            str(root),
                            "--time-limit",
                            "1h",
                            "--director-mode",
                            "llm",
                            "--proposal-ranking",
                            CATALOG_ID,
                        ]
                    ),
                    0,
                )
            plan = json.loads(prepared_output.getvalue())
            self.assertEqual(plan["proposal_ranking"], CATALOG_ID)
            with ResearchStore(root / "results.sqlite3") as store:
                provider = SyntheticControlProvider(
                    store=store,
                    campaign_id=plan["campaign_id"],
                    proposal_ranking=CATALOG_ID,
                    mode="static",
                    seed=37,
                )
                fake_snapshot = {
                    "snapshot_id": "activation-snapshot",
                    "campaign": {"state_version": 0},
                    "target": {"target_id": "erdos_gyarfas"},
                    "lanes": [],
                    "global_best": None,
                    "verification": {"jobs": []},
                }
                fake_context = _context(ranking=CATALOG_ID)
                decision = provider._decision(fake_snapshot, fake_context)
                spec_value = next(
                    action["spec"]
                    for action in decision["actions"]
                    if action["type"] == "start_lane"
                    and action["spec"]["algorithm"] == "simulated_annealing"
                )
                spec_value = dict(spec_value)
                parameters = dict(spec_value["parameters"])
                parameters.update({"order": 6, "batch_candidates": 100})
                spec_value["parameters"] = parameters
                manager = LaneManager(
                    root / "research-campaigns" / plan["campaign_id"],
                    max_active_lanes=1,
                    telemetry_windows=4,
                    checkpoints_per_lane=2,
                    pinned_checkpoints=8,
                )
                manager.start_lane(
                    LaneSpec(
                        lane_id="e2e-ranked-lane",
                        campaign_id=plan["campaign_id"],
                        target="erdos_gyarfas",
                        algorithm="simulated_annealing",
                        graph_family=spec_value["graph_family"],
                        seed=int(spec_value["seed"]),
                        parameters=parameters,
                        resource_share=1.0,
                    )
                )
                ranked = False
                try:
                    deadline = time.monotonic() + 20
                    while time.monotonic() < deadline:
                        event = manager.poll(timeout=0.2)
                        if event is None:
                            continue
                        if event.get("kind") != "telemetry":
                            continue
                        ranking = event.get("metrics", {}).get("proposal_ranking", {})
                        if int(ranking.get("policy_call_count", 0)) > 0:
                            ranked = True
                            break
                finally:
                    manager.shutdown()
                self.assertTrue(ranked)
                baseline_parameters = {
                    key: value
                    for key, value in parameters.items()
                    if key != "proposal_ranking"
                }
                baseline_manager = LaneManager(
                    root / "research-campaigns" / plan["campaign_id"],
                    max_active_lanes=1,
                    telemetry_windows=4,
                    checkpoints_per_lane=2,
                    pinned_checkpoints=8,
                )
                baseline_manager.start_lane(
                    LaneSpec(
                        lane_id="e2e-unranked-lane",
                        campaign_id=plan["campaign_id"],
                        target="erdos_gyarfas",
                        algorithm="simulated_annealing",
                        graph_family=spec_value["graph_family"],
                        seed=int(spec_value["seed"]) + 1,
                        parameters=baseline_parameters,
                        resource_share=1.0,
                    )
                )
                baseline_metrics = None
                try:
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        event = baseline_manager.poll(timeout=0.2)
                        if event is not None and event.get("kind") == "telemetry":
                            baseline_metrics = event.get("metrics", {})
                            break
                finally:
                    baseline_manager.shutdown()
                self.assertIsNotNone(baseline_metrics)
                self.assertNotIn("proposal_ranking", baseline_metrics)


if __name__ == "__main__":
    unittest.main()
