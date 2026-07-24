import unittest

from sglab.external import ExternalTool, NAUTY_GENG, NAUTY_LABELG


class ExternalAdapterTests(unittest.TestCase):
    def test_missing_optional_tool_is_controlled_failure(self) -> None:
        tool = ExternalTool("missing", ("sglab-definitely-missing-tool",))
        result = tool.run((), timeout_seconds=1)
        self.assertEqual(result.status, "TOOL_FAILURE")
        self.assertIsNone(result.returncode)
        self.assertEqual(NAUTY_GENG.executable_names, ("geng", "nauty-geng"))
        self.assertEqual(NAUTY_LABELG.executable_names, ("labelg", "nauty-labelg"))
