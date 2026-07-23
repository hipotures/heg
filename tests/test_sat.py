import unittest

from unittest.mock import patch

from sglab.sat import EdgeVariables, cycle_clause, nauty_ground_truth, tiny_cegar
from sglab.resources import ProcessResult


class SatGroundTruthTests(unittest.TestCase):
    def test_tiny_cegar_proves_n4_ground_truth(self) -> None:
        result = tiny_cegar(4)
        self.assertEqual(result["outcome"], "UNSAT_GROUND_TRUTH")
        self.assertEqual(result["learned"][0]["kind"], "cycle")

    def test_cycle_clause_is_witness_backed(self) -> None:
        variables = EdgeVariables(4)
        clause = cycle_clause(variables, (0, 1, 2, 3))
        expected = {
            -variables.variable(0, 1),
            -variables.variable(1, 2),
            -variables.variable(2, 3),
            -variables.variable(3, 0),
        }
        self.assertEqual(set(clause), expected)

    def test_nauty_ground_truth_adapter_preserves_tool_failure(self) -> None:
        with patch(
            "sglab.external.ExternalTool.run",
            return_value=ProcessResult("TOOL_FAILURE", None, b"", b"missing"),
        ):
            result = nauty_ground_truth(4)
        self.assertEqual(result["status"], "TOOL_FAILURE")
