from .erdos_gyarfas import PLUGIN, forbidden_lengths, verify_reference

TARGETS = {PLUGIN.id: PLUGIN}

__all__ = ["TARGETS", "forbidden_lengths", "verify_reference"]
