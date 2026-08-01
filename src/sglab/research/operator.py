"""Operator-facing configuration for durable research experiments.

The high-level ``sglab experiment run`` command deliberately exposes one
stable public identity: ``[experiment] id``.  Operational defaults remain the
reviewed first-real-graph campaign contract.  Optional keys are accepted for
backwards-compatible automation, but they cannot alter the Director model or
the reviewed target contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re
import tomllib

from .catalog import normalize_proposal_ranking_catalog_id
from .campaign import PRODUCTION_DIRECTOR_EFFORT, PRODUCTION_DIRECTOR_MODEL


class ExperimentConfigError(ValueError):
    """Raised when an operator configuration is not safe to execute."""


_EXPERIMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    config_path: Path
    experiment_id: str
    workspace: Path
    target: str
    time_limit: str
    director_mode: str
    director_mode_explicit: bool
    proposal_ranking: str | None
    proposal_ranking_explicit: bool
    codex_home: Path


def _table(payload: dict[str, Any], name: str) -> dict[str, Any]:
    value = payload.get(name, {})
    if not isinstance(value, dict):
        raise ExperimentConfigError(f"[{name}] must be a TOML table")
    return value


def _optional_string(
    values: dict[str, Any], key: str, *, default: str | None = None
) -> str | None:
    value = values.get(key, default)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ExperimentConfigError(f"{key} must be a non-empty string")
    return value.strip()


def load_experiment_config(path: str | Path) -> ExperimentConfig:
    config_path = Path(path).expanduser().resolve()
    try:
        with config_path.open("rb") as handle:
            payload = tomllib.load(handle)
    except OSError as error:
        raise ExperimentConfigError(
            "experiment configuration is unavailable; expected file: "
            f"{config_path}"
        ) from error
    except tomllib.TOMLDecodeError as error:
        raise ExperimentConfigError(
            f"experiment configuration is invalid: {config_path}"
        ) from error
    if not isinstance(payload, dict):
        raise ExperimentConfigError("experiment configuration must be a TOML table")
    experiment = _table(payload, "experiment")
    director = _table(payload, "director")
    search = _table(payload, "search")
    allowed_top = {"experiment", "director", "search"}
    unexpected_top = set(payload) - allowed_top
    if unexpected_top:
        raise ExperimentConfigError(
            "unsupported top-level experiment configuration keys: "
            + ", ".join(sorted(str(key) for key in unexpected_top))
        )
    experiment_id = _optional_string(experiment, "id")
    if experiment_id is None or not _EXPERIMENT_ID.fullmatch(experiment_id):
        raise ExperimentConfigError(
            "[experiment].id must match [A-Za-z0-9][A-Za-z0-9._-]{0,119}"
        )

    workspace_value = _optional_string(experiment, "workspace")
    if workspace_value is None:
        workspace = config_path.parent / "workspace" / experiment_id
    else:
        workspace = Path(workspace_value).expanduser()
        if not workspace.is_absolute():
            workspace = config_path.parent / workspace
    workspace = workspace.resolve()
    if workspace in {Path("/"), Path.home().resolve()}:
        raise ExperimentConfigError("experiment workspace is too broad")

    target = _optional_string(
        experiment,
        "target",
        default="erdos_gyarfas",
    )
    assert target is not None
    if target != "erdos_gyarfas":
        raise ExperimentConfigError(
            "the first real graph experiment contract fixes target to erdos_gyarfas"
        )

    time_limit = _optional_string(experiment, "time_limit", default="1h")
    assert time_limit is not None
    director_mode_explicit = "director_mode" in experiment
    if "mode" in director:
        if director_mode_explicit:
            raise ExperimentConfigError(
                "Director mode must be specified in one configuration section"
            )
        director_mode_explicit = True
    director_mode = _optional_string(
        experiment if "director_mode" in experiment else director,
        "director_mode" if "director_mode" in experiment else "mode",
        default="llm",
    )
    assert director_mode is not None
    if director_mode not in {"llm", "passive"}:
        raise ExperimentConfigError("director_mode must be llm or passive")

    proposal_ranking_explicit = (
        "proposal_ranking" in search or "proposal_ranking" in experiment
    )
    ranking_value = _optional_string(
        search,
        "proposal_ranking",
        default=_optional_string(experiment, "proposal_ranking"),
    )
    try:
        proposal_ranking = normalize_proposal_ranking_catalog_id(ranking_value)
    except ValueError as error:
        raise ExperimentConfigError(str(error)) from error
    if proposal_ranking is not None and director_mode != "llm":
        raise ExperimentConfigError(
            "proposal-ranking activation requires LLM Director mode"
        )

    configured_model = _optional_string(director, "model")
    if configured_model is not None and configured_model != PRODUCTION_DIRECTOR_MODEL:
        raise ExperimentConfigError(
            "the experiment contract fixes the reviewed Director model"
        )
    configured_effort = _optional_string(director, "reasoning_effort")
    if configured_effort is not None and configured_effort != PRODUCTION_DIRECTOR_EFFORT:
        raise ExperimentConfigError(
            "the experiment contract fixes the reviewed Director effort"
        )
    codex_home_value = _optional_string(
        director,
        "codex_home",
        default=_optional_string(experiment, "codex_home", default="~/.codex"),
    )
    assert codex_home_value is not None
    codex_home = Path(codex_home_value).expanduser().resolve()

    allowed_experiment = {
        "id",
        "workspace",
        "target",
        "time_limit",
        "director_mode",
        "proposal_ranking",
        "codex_home",
    }
    unknown_experiment = set(experiment) - allowed_experiment
    if unknown_experiment:
        raise ExperimentConfigError(
            "unsupported [experiment] keys: "
            + ", ".join(sorted(str(key) for key in unknown_experiment))
        )
    unknown_director = set(director) - {
        "mode",
        "model",
        "reasoning_effort",
        "effort",
        "codex_home",
    }
    if unknown_director:
        raise ExperimentConfigError(
            "unsupported [director] keys: "
            + ", ".join(sorted(str(key) for key in unknown_director))
        )
    configured_alias_effort = _optional_string(director, "effort")
    if (
        configured_alias_effort is not None
        and configured_effort is not None
        and configured_alias_effort != configured_effort
    ):
        raise ExperimentConfigError(
            "Director effort must be specified in one configuration field"
        )
    if configured_alias_effort is not None:
        if configured_alias_effort != PRODUCTION_DIRECTOR_EFFORT:
            raise ExperimentConfigError(
                "the experiment contract fixes the reviewed Director effort"
            )
    unknown_search = set(search) - {"proposal_ranking"}
    if unknown_search:
        raise ExperimentConfigError(
            "unsupported [search] keys: "
            + ", ".join(sorted(str(key) for key in unknown_search))
        )
    return ExperimentConfig(
        config_path=config_path,
        experiment_id=experiment_id,
        workspace=workspace,
        target=target,
        time_limit=time_limit,
        director_mode=director_mode,
        director_mode_explicit=director_mode_explicit,
        proposal_ranking=proposal_ranking,
        proposal_ranking_explicit=proposal_ranking_explicit,
        codex_home=codex_home,
    )
