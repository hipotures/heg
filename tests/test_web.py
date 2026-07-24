import unittest
import json
import tempfile
from http.client import HTTPConnection
from pathlib import Path
from threading import Thread

from sglab.state import atomic_write_json
from sglab.web import create_server


class WebAssetsTests(unittest.TestCase):
    def test_index_exists(self) -> None:
        root = Path(__file__).resolve().parents[1]
        self.assertTrue((root / "web" / "index.html").is_file())

    def test_http_api_smoke_and_control_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            atomic_write_json(workspace / "state.json", {"status": "IDLE"})
            server = create_server(workspace, "127.0.0.1", 0)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = HTTPConnection(*server.server_address, timeout=2)
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


if __name__ == "__main__":
    unittest.main()
