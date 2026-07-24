from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any
import json
import sqlite3

from ..state import atomic_write_json, utc_now
from .auth import auth_is_imported
from .campaign import ResearchCampaignRunner


CONTROLLERS = ("static", "random", "serial_ai", "active_ai")
DEFAULT_SEEDS = (1701, 2903, 4517, 6421, 8089)


@dataclass(frozen=True, slots=True)
class ControlStudyBudget:
    wall_seconds: float = 60.0
    seeds: tuple[int, ...] = DEFAULT_SEEDS
    max_active_lanes: int = 8
    verifier_slots: int = 1
    director_turns: int = 4

    def validate(self) -> None:
        if not 10 <= self.wall_seconds <= 3600:
            raise ValueError("control-study wall budget must be 10..3600 seconds")
        if len(self.seeds) < 2 or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("control study requires at least two unique seeds")
        if (
            self.max_active_lanes != 8
            or self.verifier_slots != 1
            or self.director_turns != 4
        ):
            raise ValueError("control-study resource envelope is fixed")


class ControlStudyRunner:
    """Equal-envelope hidden-witness comparison; never a production controller."""

    def __init__(
        self,
        *,
        workspace: Path,
        output: Path,
        budget: ControlStudyBudget | None = None,
        codex: str = "codex",
    ):
        self.workspace = workspace.resolve()
        self.output = output.resolve()
        self.budget = budget or ControlStudyBudget()
        self.codex = codex

    def run(self) -> dict[str, Any]:
        self.budget.validate()
        if not auth_is_imported(self.workspace / ".sglab"):
            raise RuntimeError(
                "control study includes AI controllers and requires an explicitly "
                "authorized `sglab ai-director auth-import` first"
            )
        self.workspace.mkdir(parents=True, exist_ok=True)
        trials: list[dict[str, Any]] = []
        for seed in self.budget.seeds:
            for controller in CONTROLLERS:
                status = ResearchCampaignRunner(
                    workspace=self.workspace,
                    stop_mode="time_limit",
                    duration_seconds=self.budget.wall_seconds,
                    target="m6_hidden_witness_control_v1",
                    codex=self.codex,
                    controller_mode=controller,
                    controller_seed=seed,
                    maximum_director_turns=self.budget.director_turns,
                ).run()
                trials.append(
                    _trial_metrics(
                        self.workspace / "results.sqlite3",
                        str(status["campaign_id"]),
                        controller=controller,
                        seed=seed,
                    )
                )
        report = {
            "schema_version": "1.0",
            "created_at": utc_now(),
            "target": "m6_hidden_witness_control_v1",
            "control_only": True,
            "controllers": list(CONTROLLERS),
            "budget": {
                "wall_seconds_per_trial": self.budget.wall_seconds,
                "seeds": list(self.budget.seeds),
                "max_active_lanes": self.budget.max_active_lanes,
                "verifier_slots": self.budget.verifier_slots,
                "director_turns": self.budget.director_turns,
                "ai_model_call_budget": self.budget.director_turns,
                "action_budget": (
                    "same schema cap of 12 actions per decision and common deadline"
                ),
            },
            "trials": trials,
            "aggregate": _aggregate(trials),
            "superiority_claim": {
                "made": False,
                "reason": (
                    "The study records descriptive multi-seed controls only; no "
                    "pre-registered inferential superiority test is implemented."
                ),
            },
            "compatibility_note": (
                "The authoritative baseline had no M5 AI provider. serial_ai is "
                "the documented compatibility construction: the same app-server "
                "Director and action contract with all lanes paused during each "
                "turn."
            ),
        }
        self.output.mkdir(parents=True, exist_ok=True)
        json_path = self.output / "M6_BENCHMARK_RESULTS.json"
        markdown_path = self.output / "M6_BENCHMARK_RESULTS.md"
        atomic_write_json(json_path, report)
        _write_text(markdown_path, _markdown(report))
        return {
            **report,
            "json_report": str(json_path),
            "markdown_report": str(markdown_path),
        }


def _trial_metrics(
    database_path: Path,
    campaign_id: str,
    *,
    controller: str,
    seed: int,
) -> dict[str, Any]:
    uri = f"{database_path.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        campaign = connection.execute(
            "SELECT * FROM research_campaigns WHERE campaign_id=?",
            (campaign_id,),
        ).fetchone()
        if campaign is None:
            raise RuntimeError("control-study campaign disappeared")
        created = _time(str(campaign["created_at"]))
        updated = _time(str(campaign["updated_at"]))
        elapsed = max(0.0, (updated - created).total_seconds())
        terminal = connection.execute(
            """
            SELECT * FROM campaign_terminal_events
            WHERE campaign_id=? ORDER BY created_at LIMIT 1
            """,
            (campaign_id,),
        ).fetchone()
        certified = (
            terminal is not None
            and terminal["terminal_kind"] == "succeeded_certified_counterexample"
        )
        time_to_certified = (
            max(0.0, (_time(str(terminal["created_at"])) - created).total_seconds())
            if certified
            else None
        )
        lane_rows = connection.execute(
            """
            SELECT telemetry_high_water, resource_share
            FROM research_lanes WHERE campaign_id=?
            """,
            (campaign_id,),
        ).fetchall()
        candidates = sum(int(row["telemetry_high_water"]) for row in lane_rows)
        cpu_hours_proxy = (
            elapsed * sum(float(row["resource_share"]) for row in lane_rows) / 3600
        )
        candidate_rows = connection.execute(
            """
            SELECT created_at, score_json FROM campaign_candidates
            WHERE campaign_id=? ORDER BY created_at, rowid
            """,
            (campaign_id,),
        ).fetchall()
        best_scalar, score_auc = _score_metrics(
            candidate_rows, created, updated
        )
        actions = connection.execute(
            """
            SELECT a.validation_status, a.action_type,
                   o.application_status, o.expectation_met, o.evaluated_at
            FROM director_actions a
            LEFT JOIN director_action_outcomes o ON o.action_id=a.action_id
            WHERE a.campaign_id=?
            """,
            (campaign_id,),
        ).fetchall()
        evaluated = [row for row in actions if row["evaluated_at"] is not None]
        verified = connection.execute(
            """
            SELECT count(*) AS total,
                   SUM(CASE WHEN certification_status='COUNTEREXAMPLE_VERIFIED'
                            THEN 1 ELSE 0 END) AS certified
            FROM campaign_verification_jobs WHERE campaign_id=?
            """,
            (campaign_id,),
        ).fetchone()
        usage = connection.execute(
            """
            SELECT COALESCE(SUM(input_tokens), 0) AS input_tokens,
                   COALESCE(SUM(cached_input_tokens), 0) AS cached_input_tokens,
                   COALESCE(SUM(cache_write_input_tokens), 0)
                       AS cache_write_input_tokens,
                   COALESCE(SUM(output_tokens), 0) AS output_tokens,
                   COALESCE(SUM(reasoning_output_tokens), 0) AS reasoning_tokens,
                   COALESCE(SUM(total_tokens), 0) AS total_tokens,
                   COALESCE(SUM(wall_seconds), 0) AS wall_seconds,
                   count(*) AS turns
            FROM app_server_turns WHERE campaign_id=?
            """,
            (campaign_id,),
        ).fetchone()
        return {
            "campaign_id": campaign_id,
            "controller": controller,
            "seed": seed,
            "terminal_state": campaign["state"],
            "elapsed_seconds": elapsed,
            "certified_witness": certified,
            "time_to_certified_seconds": time_to_certified,
            "candidate_evaluations": candidates,
            "unique_structures_found": len(candidate_rows),
            "best_score_scalar": best_scalar,
            "best_score_area_under_time_curve": score_auc,
            "candidate_evaluations_per_cpu_hour_proxy": (
                candidates / cpu_hours_proxy if cpu_hours_proxy > 0 else 0.0
            ),
            "verified_finalist_yield": {
                "submitted": int(verified["total"] or 0),
                "certified": int(verified["certified"] or 0),
            },
            "actions": {
                "total": len(actions),
                "applied": sum(
                    row["application_status"] == "applied" for row in actions
                ),
                "stale_or_rejected": sum(
                    str(row["validation_status"]).startswith("rejected")
                    or (
                        row["application_status"] is not None
                        and row["application_status"] != "applied"
                    )
                    for row in actions
                ),
                "interventions": sum(
                    row["action_type"]
                    in {
                        "patch_lane",
                        "fork_lane",
                        "restart_lane",
                        "reallocate_resources",
                        "stop_lane",
                        "start_lane",
                    }
                    for row in actions
                ),
                "evaluated": len(evaluated),
                "intervention_uplift_rate": (
                    sum(row["expectation_met"] == 1 for row in evaluated)
                    / len(evaluated)
                    if evaluated
                    else None
                ),
                "action_regret_rate": (
                    sum(row["expectation_met"] == 0 for row in evaluated)
                    / len(evaluated)
                    if evaluated
                    else None
                ),
            },
            "provider": dict(usage),
            "resource_efficiency_note": (
                "CPU-hours are a deterministic share-time proxy because the "
                "portable worker runtime does not expose per-process CPU clocks."
            ),
        }
    finally:
        connection.close()


def _score_metrics(
    rows: list[sqlite3.Row],
    created: datetime,
    ended: datetime,
) -> tuple[float | None, float | None]:
    points: list[tuple[float, float]] = []
    best: float | None = None
    for row in rows:
        score = json.loads(str(row["score_json"]))
        scalar = _score_scalar(score.get("ordering_key", []))
        best = scalar if best is None else min(best, scalar)
        elapsed = max(
            0.0, (_time(str(row["created_at"])) - created).total_seconds()
        )
        points.append((elapsed, best))
    if not points or best is None:
        return None, None
    duration = max(0.0, (ended - created).total_seconds())
    area = 0.0
    for index, (at, value) in enumerate(points):
        next_at = points[index + 1][0] if index + 1 < len(points) else duration
        area += value * max(0.0, next_at - at)
    return best, area


def _score_scalar(ordering: list[Any]) -> float:
    if len(ordering) != 5:
        return float("inf")
    invalid, total, weighted, novelty, simplicity = map(float, ordering)
    return (
        invalid * 2_000_000
        + total
        + weighted / 2_000_000
        + novelty / 4_000_000_000_000
        + simplicity / 80_000_000_000_000_000
    )


def _aggregate(trials: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for controller in CONTROLLERS:
        group = [trial for trial in trials if trial["controller"] == controller]
        successes = [trial for trial in group if trial["certified_witness"]]
        result[controller] = {
            "trials": len(group),
            "successes": len(successes),
            "success_rate": len(successes) / len(group) if group else 0.0,
            "mean_time_to_certified_seconds": (
                mean(
                    float(trial["time_to_certified_seconds"])
                    for trial in successes
                )
                if successes
                else None
            ),
            "mean_candidate_evaluations": (
                mean(float(trial["candidate_evaluations"]) for trial in group)
                if group
                else 0.0
            ),
            "mean_provider_total_tokens": (
                mean(float(trial["provider"]["total_tokens"]) for trial in group)
                if group
                else 0.0
            ),
        }
    return result


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# M6 Active Director Control Study",
        "",
        f"Generated: `{report['created_at']}`",
        "",
        "This is a control-only hidden-witness study, not a mathematical result.",
        "",
        "| Controller | Trials | Successes | Success rate | Mean time to M4 |",
        "|---|---:|---:|---:|---:|",
    ]
    for controller in CONTROLLERS:
        row = report["aggregate"][controller]
        time_value = row["mean_time_to_certified_seconds"]
        lines.append(
            f"| `{controller}` | {row['trials']} | {row['successes']} | "
            f"{row['success_rate']:.3f} | "
            f"{time_value:.3f}s |"
            if time_value is not None
            else (
                f"| `{controller}` | {row['trials']} | {row['successes']} | "
                f"{row['success_rate']:.3f} | n/a |"
            )
        )
    lines.extend(
        [
            "",
            "No AI-superiority claim is made. The JSON companion retains every "
            "trial, failure, action, token, timing, verification, and efficiency "
            "summary.",
            "",
            "The `serial_ai` arm is a compatibility construction because the "
            "authoritative pre-M6 repository contained no M5 AI provider: it "
            "uses the same app-server Director while pausing all search lanes "
            "during inference.",
            "",
        ]
    )
    return "\n".join(lines)


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _write_text(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)
