from __future__ import annotations

from pathlib import Path
import tomllib


def load_toml(path: str | Path) -> dict:
    file_path = Path(path)
    with file_path.open("rb") as handle:
        return tomllib.load(handle)
