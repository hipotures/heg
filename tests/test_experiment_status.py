from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest

from sglab.cli import _write_experiment_state, build_parser, main
from sglab.research.campaign import prepare_campaign_plan
from sglab.research.operator import load_experiment_config
from sglab.research.store import ResearchStore


def _create_workspace(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "workspace.json").write_text(
        json.dumps(
            {
                "workspace_kind": "first_real_graph_campaign",
                "synthetic_data": False,
                "marker_schema_version": 1,
            }
        ),
        encoding="utf-8",
    )
    with ResearchStore(root / "results.sqlite3"):
        pass


def _configured_campaign(
    root: Path,
    *,
    experiment_id: str = "status-test",
    config_relative_path: str = "experiment.toml",
) -> tuple[Path, Path, dict[str, object]]:
    config_path = root / config_relative_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "[experiment]\n" f'id = "{experiment_id}"\n',
        encoding="utf-8",
    )
    config = load_experiment_config(config_path)
    _create_workspace(config.workspace)
    plan = prepare_campaign_plan(
        config.workspace,
        duration_seconds=3600,
        director_mode="llm",
    )
    _write_experiment_state(
        config.workspace,
        config=config,
        campaign_id=str(plan["campaign_id"]),
        plan_fingerprint=str(plan["plan_fingerprint"]),
        proposal_ranking=None,
        state="prepared",
        director_mode="llm",
    )
    return config_path, config.workspace, plan


class ExperimentStatusTests(unittest.TestCase):
    def test_default_config_resolves_current_experiment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, workspace, plan = _configured_campaign(root)
            previous = Path.cwd()
            output = StringIO()
            os.chdir(root)
            try:
                with redirect_stdout(output):
                    self.assertEqual(
                        main(["research-campaign", "status"]), 0
                    )
            finally:
                os.chdir(previous)
            report = json.loads(output.getvalue())
            self.assertEqual(report["experiment_id"], "status-test")
            self.assertEqual(report["campaign_id"], plan["campaign_id"])
            self.assertEqual(report["workspace"], str(workspace))
            self.assertEqual(report["state"], "prepared")
            self.assertEqual(config_path, root / "experiment.toml")

    def test_explicit_config_resolves_another_experiment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, _, plan = _configured_campaign(
                root,
                experiment_id="alternate-status",
                config_relative_path="configs/alternate.toml",
            )
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "research-campaign",
                            "status",
                            "--config",
                            str(config_path),
                        ]
                    ),
                    0,
                )
            report = json.loads(output.getvalue())
            self.assertEqual(report["experiment_id"], "alternate-status")
            self.assertEqual(report["campaign_id"], plan["campaign_id"])

    def test_explicit_workspace_remains_backward_compatible(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, workspace, plan = _configured_campaign(root)
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    main(
                        [
                            "research-campaign",
                            "status",
                            "--workspace",
                            str(workspace),
                        ]
                    ),
                    0,
                )
            report = json.loads(output.getvalue())
            self.assertNotIn("experiment_id", report)
            self.assertEqual(report["campaign_id"], plan["campaign_id"])

    def test_missing_default_config_is_concise(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            previous = Path.cwd()
            os.chdir(directory)
            try:
                with self.assertRaisesRegex(
                    SystemExit, r"expected file: \.\/experiment\.toml"
                ):
                    main(["research-campaign", "status"])
            finally:
                os.chdir(previous)

    def test_unknown_experiment_id_does_not_select_another_campaign(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path = root / "experiment.toml"
            config_path.write_text(
                '[experiment]\nid = "unknown-status"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                SystemExit, "experiment 'unknown-status'.*no bound"
            ):
                main(
                    [
                        "research-campaign",
                        "status",
                        "--config",
                        str(config_path),
                    ]
                )

    def test_incompatible_state_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config_path, workspace, _ = _configured_campaign(root)
            marker = json.loads((workspace / "workspace.json").read_text())
            marker["synthetic_data"] = True
            (workspace / "workspace.json").write_text(
                json.dumps(marker), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                SystemExit, "experiment 'status-test'.*incompatible workspace"
            ):
                main(
                    [
                        "research-campaign",
                        "status",
                        "--config",
                        str(config_path),
                    ]
                )

    def test_workspace_and_config_are_mutually_exclusive(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                [
                    "research-campaign",
                    "status",
                    "--workspace",
                    "workspace",
                    "--config",
                    "experiment.toml",
                ]
            )


if __name__ == "__main__":
    unittest.main()
