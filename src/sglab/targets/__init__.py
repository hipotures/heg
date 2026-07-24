from typing import Any

from .erdos_gyarfas import PLUGIN as ERDOS_GYARFAS
from .erdos_gyarfas import forbidden_lengths, verify_reference
from .hidden_witness_control import PLUGIN as HIDDEN_WITNESS

TARGETS = {
    ERDOS_GYARFAS.id: ERDOS_GYARFAS,
    HIDDEN_WITNESS.id: HIDDEN_WITNESS,
}


def target_summary(target: str) -> dict[str, Any]:
    plugin = TARGETS[target]
    return {
        "target_id": plugin.id,
        "statement": plugin.statement,
        "control_only": plugin.control_only,
        "success_authority": "M4_independent_verifier",
    }

__all__ = [
    "TARGETS",
    "ERDOS_GYARFAS",
    "HIDDEN_WITNESS",
    "forbidden_lengths",
    "target_summary",
    "verify_reference",
]
