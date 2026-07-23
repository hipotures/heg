from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class Witness:
    kind: str
    vertices: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class VerifyResult:
    status: Literal["VERIFIED", "REJECTED", "UNKNOWN", "INVALID"]
    complete: bool
    message: str
    witnesses: tuple[Witness, ...] = ()
