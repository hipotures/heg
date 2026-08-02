from __future__ import annotations

import hashlib
import json
import re
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from sglab.db import connect
from sglab.research.artifacts import (
    migrate_workspace_artifacts,
    verify_import_manifest,
)
from sglab.research.export import export_campaign
from sglab.research.store import ResearchStore
from sglab.ui_fixture import create_ui_fixture


class MutationForgeArchiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[1]
        self.archive = self.root / "artifacts/proposal-ranking/mutation_forge_stage4r_v1"

    def test_archive_manifest_and_champion_are_exact(self) -> None:
        report = verify_import_manifest(self.archive)
        self.assertTrue(report["ok"], report)
        manifest = json.loads((self.archive / "import-manifest.json").read_text())
        self.assertEqual(manifest["imported_file_count"], 288)
        self.assertEqual(manifest["imported_bytes"], 10_574_800)
        champion = manifest["champion"]
        source = self.archive / champion["source_path"]
        policy = self.root / "src/sglab/research/assets/mutation_policy_stage4r_v1.py"
        self.assertEqual(source.read_bytes(), policy.read_bytes())
        self.assertEqual(
            (self.archive / "champion/source.py").read_bytes(),
            policy.read_bytes(),
        )
        self.assertEqual(
            hashlib.sha256(source.read_bytes()).hexdigest(),
            "e444562c1b308e3b23cb732be5f769ea1923ac1809501cea8571318c4aff0a7b",
        )
        self.assertEqual(
            champion["normalized_ast_sha256"],
            "2243214df58c805e9a9343dc31ed082279e1c2ac31b21243bf889dbc9a19e165",
        )
        self.assertEqual(
            champion["behavior_sha256"],
            "8c2bdaa213f11b253d3ffcae1653bd01536879bb5c254a1586ded9ae522a868e",
        )
        names = {entry["path"] for entry in manifest["files"]}
        self.assertIn("recovery/sources/program-d5ad1c8203e0d9f25f03aabd.py", names)
        self.assertIn("recovery/records/slot-00.json", names)
        self.assertIn("recovery/slots/slot-00.json", names)
        self.assertIn("appserver/s4-stage4r-issue-11-0-slot-01-repair-4298f6f93f1cb703.repair.request.md", names)

    def test_manifest_reports_missing_changed_duplicate_and_extra_paths(self) -> None:
        manifest = json.loads((self.archive / "import-manifest.json").read_text())
        first = manifest["files"][0]["path"]
        with tempfile.TemporaryDirectory() as directory:
            cases = {
                "missing": lambda path: (path / first).unlink(),
                "changed": lambda path: (path / first).write_bytes(b"changed"),
                "extra": lambda path: (path / "unexpected.bin").write_bytes(b"extra"),
                "duplicate": lambda path: json.loads(
                    (path / "import-manifest.json").read_text()
                ),
            }
            for kind, mutate in cases.items():
                target = Path(directory) / kind
                shutil.copytree(self.archive, target)
                if kind == "duplicate":
                    value = mutate(target)
                    value["files"].append(dict(value["files"][0]))
                    (target / "import-manifest.json").write_text(
                        json.dumps(value, indent=2, sort_keys=True) + "\n"
                    )
                else:
                    mutate(target)
                report = verify_import_manifest(target)
                self.assertFalse(report["ok"], report)
                self.assertTrue(
                    any(error["kind"] == kind for error in report["errors"]),
                    report,
                )

    def test_archive_has_no_credential_payloads(self) -> None:
        forbidden = (
            re.compile(rb"sk-[A-Za-z0-9]{20,}"),
            re.compile(rb"rk-[A-Za-z0-9]{20,}"),
            re.compile(rb"pk-[A-Za-z0-9]{20,}"),
            re.compile(rb"-----BEGIN PRIVATE KEY-----"),
            re.compile(rb"Authorization:\s*Bearer\s+[A-Za-z0-9._-]{20,}"),
        )
        for path in self.archive.rglob("*"):
            if not path.is_file():
                continue
            payload = path.read_bytes()
            self.assertFalse(
                any(token.search(payload) for token in forbidden),
                path,
            )


class DirectorCapsuleTests(unittest.TestCase):
    def test_campaign_export_includes_readable_artifact_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ResearchStore(root / "results.sqlite3")
            try:
                store.create_campaign(
                    campaign_id="campaign-1",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="until_success",
                    deadline_at=None,
                )
                campaign_dir = root / "research-campaigns/campaign-1"
                campaign_dir.mkdir(parents=True)
                output = root / "export.zip"
                report = export_campaign(
                    store=store,
                    campaign_id="campaign-1",
                    campaign_dir=campaign_dir,
                    output=output,
                )
                self.assertEqual(report["artifact_index"], "artifacts/README.md")
                with zipfile.ZipFile(output) as archive:
                    names = set(archive.namelist())
                    self.assertIn("artifacts/README.md", names)
                    manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["artifact_index"], "artifacts/README.md")
            finally:
                store.close()

    def test_fixture_migration_is_non_destructive_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "heg-ranked-001"
            create_ui_fixture(workspace)
            campaign = workspace / "research-campaigns/campaign-demo-running"
            (campaign / "audit").mkdir(parents=True)
            (campaign / "wire").mkdir(parents=True)
            request = {
                "prompt": json.dumps(
                    {
                        "objective": "test scientific objective",
                        "immutable_target": {"statement": "target statement"},
                        "applicable_action_description": {
                            "actions": [{"type": "start_lane"}]
                        },
                        "director_state_v2": {
                            "schema_version": "2.0",
                            "active_lane_count": 0,
                            "available_lane_slots": 2,
                        },
                        "proposal_ranking_contract": {"enabled": False},
                    },
                    sort_keys=True,
                ),
                "executable_target_registry_artifact_ref": "audit/targets.json",
            }
            response = {
                "campaign_assessment": "assessment",
                "hypothesis_updates": ["hypothesis"],
                "actions": [
                    {
                        "type": "start_lane",
                        "target_lane_id": "lane-1",
                        "parameters": {"order": 12},
                        "rationale": "rationale",
                    }
                ],
                "next_review": {"candidate_delta": 10},
            }
            (campaign / "audit/request-00.json").write_text(json.dumps(request))
            (campaign / "audit/response-00.json").write_text(json.dumps(response))
            (campaign / "audit/targets.json").write_text("targets")
            (campaign / "audit/evidence-00.json").write_text("evidence")
            (campaign / "wire/turn-00.jsonl").write_text(
                '{"type":"response.completed","timestamp":"2026-01-01T00:00:00Z"}\n'
            )
            database = workspace / "results.sqlite3"
            before = database.read_bytes()
            connection = connect(database)
            try:
                connection.execute(
                    """
                    UPDATE app_server_turns
                    SET validation_issues_json=?, validation_issue_count=?
                    WHERE turn_record_id='turn-record-demo-00'
                    """,
                    (json.dumps([{"path": "$.actions[0]", "message": "bad action"}]), 1),
                )
                connection.commit()
            finally:
                connection.close()
            before = database.read_bytes()
            first = migrate_workspace_artifacts(workspace)
            self.assertEqual(first["turn_count"], 12)
            self.assertTrue((workspace / "artifacts/README.md").is_file())
            capsule = workspace / "artifacts/director-turns/turn-0001"
            readme = (capsule / "README.md").read_text()
            self.assertIn("test scientific objective", readme)
            self.assertIn("start_lane", readme)
            self.assertIn("test scientific objective", (capsule / "request.md").read_text())
            self.assertIn("lane-1", (capsule / "response.md").read_text())
            validation = json.loads((capsule / "validation.json").read_text())
            self.assertEqual(validation["issues"], [{"path": "$.actions[0]", "message": "bad action"}])
            statuses = {
                json.loads(path.read_text())["lifecycle_status"]
                for path in workspace.glob("artifacts/director-turns/turn-*/validation.json")
            }
            self.assertTrue({"completed", "timed_out", "aborted", "in_progress"}.issubset(statuses))
            self.assertEqual(database.read_bytes(), before)
            snapshot = {
                path.relative_to(workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (workspace / "artifacts").rglob("*")
                if path.is_file()
            }
            second = migrate_workspace_artifacts(workspace)
            self.assertEqual(second["turn_count"], first["turn_count"])
            self.assertEqual(
                snapshot,
                {
                    path.relative_to(workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (workspace / "artifacts").rglob("*")
                    if path.is_file()
                },
            )


if __name__ == "__main__":
    unittest.main()
