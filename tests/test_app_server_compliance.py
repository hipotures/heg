from pathlib import Path
import tempfile
import unittest

from sglab.research.app_server_client import AppServerClient, AppServerConfig
from sglab.research.compliance import invalid_config_rejected


class InstalledAppServerComplianceTests(unittest.TestCase):
    def test_strict_config_rejects_unknown_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            client = AppServerClient(
                AppServerConfig(application_data=Path(directory))
            )
            self.assertTrue(invalid_config_rejected(client))
