from .erdos_gyarfas import forbidden_lengths, verify_reference

__all__ = ["forbidden_lengths", "verify_reference"]
from .erdos_gyarfas import PLUGIN

TARGETS = {PLUGIN.id: PLUGIN}

__all__ = ["TARGETS"]
