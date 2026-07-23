from __future__ import annotations

from pathlib import Path
from copy import deepcopy
import tomllib
from typing import Any


def load_toml(path: str | Path) -> dict:
    file_path = Path(path)
    with file_path.open("rb") as handle:
        return tomllib.load(handle)


def merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge configuration dictionaries without mutating inputs."""

    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_config(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_config(
    default_path: str | Path,
    target_path: str | Path | None = None,
    override_path: str | Path | None = None,
) -> dict[str, Any]:
    config = load_toml(default_path)
    for path in (target_path, override_path):
        if path is not None:
            config = merge_config(config, load_toml(path))
    return config
