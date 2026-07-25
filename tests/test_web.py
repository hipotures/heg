import unittest
import json
import tempfile
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from sglab.research.store import ResearchStore
from sglab.state import atomic_write_json
from sglab.web import create_server


class WebAssetsTests(unittest.TestCase):
    def test_index_exists(self) -> None:
        root = Path(__file__).resolve().parents[1]
        page = root / "web" / "index.html"
        self.assertTrue(page.is_file())
        self.assertIn("Structural Graph Lab", page.read_text(encoding="utf-8"))

    def test_http_api_smoke_and_control_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            atomic_write_json(workspace / "state.json", {"status": "IDLE"})
            server = create_server(workspace, "127.0.0.1", 0)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = HTTPConnection(*server.server_address, timeout=2)
            connection.request("GET", "/")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertIn(
                f"{workspace.parent.name}/{workspace.name}".encode(),
                response.read(),
            )
            connection.request("GET", "/api/status")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["status"], "IDLE")
            connection.request(
                "POST",
                "/api/control",
                body=json.dumps({"action": "SHELL"}),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            response.read()
            connection.request(
                "POST",
                "/api/runs",
                body=json.dumps(
                    {
                        "target": "erdos_gyarfas",
                        "order": 8,
                        "mode": "cubic_first",
                        "algorithm": "simulated_annealing",
                        "workers": 1,
                        "seed": 1,
                        "wall_seconds": 1,
                        "memory_high_bytes": 2,
                        "memory_limit_bytes": 1,
                    }
                ),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            self.assertIn(b"memory high", response.read())
            invalid = {
                "target": "erdos_gyarfas",
                "order": 8.5,
                "mode": "cubic_first",
                "algorithm": "simulated_annealing",
                "workers": 1,
                "seed": 1,
                "wall_seconds": 1,
                "memory_high_bytes": 0,
                "memory_limit_bytes": 0,
            }
            connection.request(
                "POST",
                "/api/runs",
                body=json.dumps(invalid),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            self.assertIn(b"must be an integer", response.read())
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_bearer_token_protects_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = create_server(Path(directory), "127.0.0.1", 0, token="secret")
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = HTTPConnection(*server.server_address, timeout=2)
            connection.request("GET", "/api/status")
            response = connection.getresponse()
            self.assertEqual(response.status, 401)
            response.read()
            connection.request(
                "POST",
                "/api/control",
                body='{"action":"STOP"}',
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 401)
            response.read()
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_dashboard_token_environment_alias_is_protected(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.dict(
                "os.environ",
                {"SGLAB_DASHBOARD_TOKEN": "dashboard-secret"},
                clear=False,
            ),
        ):
            server = create_server(Path(directory), "127.0.0.1", 0)
            self.assertEqual(server.token, "dashboard-secret")
            server.server_close()

    def test_dashboard_stores_fragment_token_only_for_browser_session(self) -> None:
        dashboard = (Path(__file__).parents[1] / "web" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("sessionStorage.setItem('sglab-dashboard-token'", dashboard)
        self.assertIn("history.replaceState", dashboard)

    def test_campaign_api_has_only_stop_contract_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            auth = workspace / ".sglab" / "director" / "codex-home" / "auth.json"
            auth.parent.mkdir(parents=True)
            auth.write_text("{}\n", encoding="utf-8")
            server = create_server(workspace, "127.0.0.1", 0)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = HTTPConnection(*server.server_address, timeout=2)
            connection.request("GET", "/api/research-campaign")
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(response.read())["state"], "IDLE")
            connection.request(
                "POST",
                "/api/research-campaign",
                body=json.dumps(
                    {
                        "stop_mode": "time_limit",
                        "duration": "1h",
                        "workers": 8,
                    }
                ),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            self.assertIn(b"unsupported campaign input", response.read())
            connection.request(
                "POST",
                "/api/research-campaign",
                body=json.dumps(
                    {"stop_mode": "until_success", "duration": "1h"}
                ),
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            self.assertIn(b"does not accept a duration", response.read())
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_campaign_turn_communication_is_lazy_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            campaign_dir = workspace / "research-campaigns" / "campaign-1"
            request_ref = "director/requests/turn-record-1.json"
            response_ref = "director/responses/turn-record-1.json"
            atomic_write_json(
                campaign_dir / request_ref,
                {"prompt": "full scientific request", "output_schema": {"type": "object"}},
            )
            atomic_write_json(
                campaign_dir / response_ref,
                {"campaign_assessment": "full Director response", "actions": []},
            )
            with ResearchStore(workspace / "results.sqlite3") as store:
                store.create_campaign(
                    campaign_id="campaign-1",
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="until_success",
                    deadline_at=None,
                )
                store.record_session(
                    record_id="session-record-1",
                    campaign_id="campaign-1",
                    thread_id="thread-1",
                    session_id="session-1",
                    thread_path=None,
                    parent_thread_id=None,
                    model="gpt-5.6-luna",
                    effort="high",
                    codex_version="test",
                    executable_sha256="b" * 64,
                    protocol_schema_sha256="c" * 64,
                    context_mode="stateless_turns",
                )
                store.record_snapshot(
                    snapshot_id="snapshot-1",
                    campaign_id="campaign-1",
                    campaign_state_version=0,
                    high_water={},
                    artifact_ref="snapshots/snapshot-1.json",
                    artifact_sha256="f" * 64,
                    payload_bytes=2,
                )
                store.record_trigger(
                    trigger_id="trigger-1",
                    campaign_id="campaign-1",
                    campaign_state_version=0,
                    reasons=["test"],
                    first_event_at="2026-07-25T00:00:00Z",
                    snapshot_id="snapshot-1",
                )
                store.begin_turn(
                    turn_record_id="turn-record-1",
                    session_record_id="session-record-1",
                    campaign_id="campaign-1",
                    thread_id="thread-1",
                    snapshot_id="snapshot-1",
                    trigger_id="trigger-1",
                    request_artifact_ref=request_ref,
                    request_sha256="d" * 64,
                    wire_artifact_ref="director/wire/turn-record-1.jsonl",
                )
                store.complete_turn(
                    "turn-record-1",
                    turn_id="turn-1",
                    status="completed_valid",
                    response_artifact_ref=response_ref,
                    response_sha256="e" * 64,
                    wire_sha256="f" * 64,
                    usage={
                        "input_tokens": 10,
                        "cached_input_tokens": 0,
                        "cache_write_input_tokens": 0,
                        "output_tokens": 5,
                        "reasoning_output_tokens": 2,
                        "total_tokens": 15,
                        "raw": {"totalTokens": 15},
                    },
                    wall_seconds=1.0,
                )
            server = create_server(workspace, "127.0.0.1", 0)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = HTTPConnection(*server.server_address, timeout=2)
            connection.request(
                "GET",
                "/api/research-campaign/turn/turn-record-1/communication",
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            payload = json.loads(response.read())
            self.assertEqual(
                payload["request"]["prompt"],
                "full scientific request",
            )
            self.assertEqual(
                payload["response"]["campaign_assessment"],
                "full Director response",
            )
            self.assertNotIn("artifact_ref", payload)
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_campaign_resume_preview_is_protected_continuity_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            campaign_id = "campaign-resume-ui"
            campaign_dir = workspace / "research-campaigns" / campaign_id
            atomic_write_json(
                campaign_dir / "campaign-plan.json",
                {
                    "campaign_id": campaign_id,
                    "director": {
                        "model": "gpt-5.6-luna",
                        "reasoning_effort": "high",
                        "context_mode": "stateless_turns",
                    },
                    "search_limits": {
                        "cpu_workers": 2,
                        "maximum_active_lanes": 2,
                        "lane_memory_limit_bytes": 268_435_456,
                    },
                    "verification_limits": {
                        "maximum_concurrent_jobs": 1,
                        "verifier_memory_limit_bytes": 268_435_456,
                        "maximum_queue_depth": 16,
                    },
                    "scientific_memory": {
                        "scientific_state_soft_limit_bytes": 24_576,
                        "scientific_state_hard_limit_bytes": 32_768,
                        "scientific_snapshot_interval_cycles": 5,
                    },
                },
            )
            with ResearchStore(workspace / "results.sqlite3") as store:
                store.create_campaign(
                    campaign_id=campaign_id,
                    target="erdos_gyarfas",
                    target_definition_sha256="a" * 64,
                    stop_mode="time_limit",
                    deadline_at="2026-07-25T00:01:00Z",
                )
                store.set_campaign_coordination_state(
                    campaign_id,
                    expected_version=0,
                    state="paused_fault",
                    fault_kind="InfrastructureFault",
                    fault_detail="preserved fault",
                )
            atomic_write_json(
                workspace / "active-research-campaign.json",
                {"campaign_id": campaign_id, "pid": 0},
            )
            server = create_server(
                workspace, "127.0.0.1", 0, token="resume-secret"
            )
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = HTTPConnection(*server.server_address, timeout=2)
            body = json.dumps(
                {
                    "campaign_id": campaign_id,
                    "additional_time": "2h",
                    "cpu_workers": 16,
                    "maximum_active_lanes": 8,
                    "lane_memory_bytes": 536_870_912,
                    "verifier_concurrency": 2,
                    "repair_acknowledgement": "repaired in offline commit",
                }
            )
            connection.request(
                "POST",
                "/api/research-campaign/resume-preview",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 401)
            response.read()
            connection.request(
                "POST",
                "/api/research-campaign/resume-preview",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer resume-secret",
                },
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            preview = json.loads(response.read())
            self.assertEqual(preview["campaign_id"], campaign_id)
            self.assertEqual(preview["proposed_attempt_index"], 1)
            self.assertEqual(
                preview["requested_resources"]["maximum_active_lanes"], 8
            )
            self.assertEqual(
                preview["effective_resources"]["maximum_active_lanes"], 8
            )
            self.assertEqual(
                preview["effective_resources"]["cpu_workers"], 16
            )
            self.assertEqual(preview["side_effects"]["model_inferences"], 0)
            self.assertEqual(preview["side_effects"]["auth_accesses"], 0)
            with ResearchStore(workspace / "results.sqlite3") as store:
                self.assertEqual(
                    store.campaign(campaign_id)["state"], "paused_fault"
                )
                self.assertEqual(store.execution_attempts(campaign_id), [])
            auth = (
                workspace
                / ".sglab"
                / "research-campaigns"
                / campaign_id
                / "runtime-groups"
                / "director"
                / "director"
                / "codex-home"
                / "auth.json"
            )
            auth.parent.mkdir(parents=True)
            auth.write_text("{}\n", encoding="utf-8")
            with patch("sglab.web.Popen") as launch:
                launch.return_value.pid = 4312
                launch.return_value.poll.return_value = None
                status, started = server.resume_campaign(
                    json.loads(body)
                )
                self.assertEqual(status, 202)
                self.assertEqual(started["campaign_id"], campaign_id)
                command = launch.call_args.args[0]
                self.assertIn("resume", command)
                self.assertIn("--additional-time", command)
                self.assertIn("2h", command)
                self.assertIn("--cpu-workers", command)
                self.assertIn("16", command)
                self.assertIn("--max-active-lanes", command)
                self.assertIn("8", command)
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
