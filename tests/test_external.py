import unittest

from sglab.external import ExternalTool


class ExternalAdapterTests(unittest.TestCase):
    def test_missing_optional_tool_is_controlled_failure(self) -> None:
        tool = ExternalTool("missing", ("sglab-definitely-missing-tool",))
        result = tool.run((), timeout_seconds=1)
        self.assertEqual(result.status, "TOOL_FAILURE")
        self.assertIsNone(result.returncode)
