from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any
import json

from .store import ResearchStore
from .telemetry import compare_effects


class EffectEvaluator:
    """Attach measured pre/post lane windows to completed interventions."""

    def __init__(self, store: ResearchStore, campaign_id: str):
        self.store = store
        self.campaign_id = campaign_id

    def evaluate_ready(self) -> list[dict[str, Any]]:
        rows = self.store.connection.execute(
            """
            SELECT a.action_id, a.action_type, a.target_lane_id,
                   a.expected_lane_version, a.expected_effect,
                   a.evaluation_window_json, o.resulting_lane_version,
                   o.applied_at
            FROM director_actions a
            JOIN director_action_outcomes o ON o.action_id=a.action_id
            WHERE a.campaign_id=? AND o.application_status='applied'
              AND o.evaluated_at IS NULL AND a.target_lane_id IS NOT NULL
              AND a.action_type IN ('patch_lane', 'restart_lane')
            ORDER BY o.applied_at, a.action_id
            """,
            (self.campaign_id,),
        ).fetchall()
        evaluated: list[dict[str, Any]] = []
        for row in rows:
            result = self._evaluate(dict(row))
            if result is not None:
                evaluated.append(result)
        return evaluated

    def _evaluate(self, action: dict[str, Any]) -> dict[str, Any] | None:
        pre = self._windows(
            str(action["target_lane_id"]),
            int(action["expected_lane_version"]),
            descending=True,
        )
        post = self._windows(
            str(action["target_lane_id"]),
            int(action["resulting_lane_version"]),
            descending=False,
        )
        window = json.loads(str(action["evaluation_window_json"]))
        elapsed = (
            datetime.now(UTC) - _parse_time(str(action["applied_at"]))
        ).total_seconds()
        candidate_delta = (
            int(post[-1]["end_high_water"])
            - int(post[0]["start_high_water"])
            if post
            else 0
        )
        ready = (
            len(pre) >= 2
            and len(post) >= 2
            and (
                candidate_delta >= int(window["max_candidate_delta"])
                or elapsed >= int(window["max_wall_seconds"])
                or len(post) >= 4
            )
        )
        if not ready:
            return None
        pre = list(reversed(pre[:8]))
        post = post[:8]
        direction = _expected_direction(str(action["expected_effect"]))
        comparison = compare_effects(
            [json.loads(item["metrics_json"]) for item in pre],
            [json.loads(item["metrics_json"]) for item in post],
            expected_direction=direction,
        )
        effect = {
            **asdict(comparison),
            "expected_direction": direction,
            "pre_lane_version": int(action["expected_lane_version"]),
            "post_lane_version": int(action["resulting_lane_version"]),
            "pre_window_count": len(pre),
            "post_window_count": len(post),
            "candidate_delta": candidate_delta,
            "wall_seconds": elapsed,
        }
        committed = self.store.complete_action_evaluation(
            action_id=str(action["action_id"]),
            pre_window_id=str(pre[-1]["metric_window_id"]),
            post_window_id=str(post[-1]["metric_window_id"]),
            observed_effect=effect,
            expectation_met=comparison.expectation_met,
        )
        return (
            {
                "action_id": action["action_id"],
                "expectation_met": comparison.expectation_met,
                "observed_effect": effect,
            }
            if committed
            else None
        )

    def _windows(
        self, lane_id: str, lane_version: int, *, descending: bool
    ) -> list[dict[str, Any]]:
        order = "DESC" if descending else "ASC"
        rows = self.store.connection.execute(
            f"""
            SELECT * FROM lane_metric_windows
            WHERE lane_id=? AND lane_version=?
            ORDER BY end_high_water {order} LIMIT 8
            """,
            (lane_id, lane_version),
        ).fetchall()
        return [dict(row) for row in rows]


def _expected_direction(value: str) -> str | None:
    lowered = value.lower()
    if "divers" in lowered or "unique" in lowered:
        return "increase_diversity"
    if "throughput" in lowered or "speed" in lowered:
        return "increase_throughput"
    if any(word in lowered for word in ("score", "penalty", "witness")):
        return "improve_score_slope"
    return None


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
