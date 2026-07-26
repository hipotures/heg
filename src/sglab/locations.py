from __future__ import annotations

from pathlib import Path
from shutil import which
import sys


def source_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[2]
    return candidate if (candidate / "pyproject.toml").is_file() else None


def asset_path(*parts: str) -> Path:
    root = source_root()
    candidates = []
    if root is not None:
        candidates.append(root.joinpath(*parts))
    candidates.append(
        Path(sys.prefix) / "share" / "structural-graph-lab" / Path(*parts)
    )
    return next((path for path in candidates if path.exists()), candidates[-1])


def cyclecheck_path() -> Path:
    root = source_root()
    if root is not None:
        source_binary = root / "_build" / "sglab-cyclecheck"
        if source_binary.is_file():
            return source_binary
    installed = which("sglab-cyclecheck")
    return Path(installed) if installed is not None else Path("sglab-cyclecheck")


def score_worker_path() -> Path:
    root = source_root()
    if root is not None:
        source_binary = root / "_build" / "sglab-score-worker"
        if source_binary.is_file():
            return source_binary
    installed = which("sglab-score-worker")
    return (
        Path(installed)
        if installed is not None
        else Path("sglab-score-worker")
    )
