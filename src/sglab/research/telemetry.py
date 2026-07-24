from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable
import math


@dataclass(frozen=True, slots=True)
class EffectComparison:
    score_slope_change: float
    diversity_change: float
    throughput_change: float
    duplicate_rate_change: float
    operator_yield_change: float
    expectation_met: bool | None


class TelemetrySeries:
    """Bounded per-lane micro-batch telemetry with simple robust slopes."""

    def __init__(self, maximum: int = 120):
        if maximum < 2:
            raise ValueError("telemetry maximum must be at least 2")
        self._items: deque[dict[str, Any]] = deque(maxlen=maximum)

    def append(self, item: dict[str, Any]) -> None:
        self._items.append(dict(item))

    def items(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(item) for item in self._items)

    def recent(self, count: int = 8) -> dict[str, Any]:
        items = list(self._items)[-max(1, count) :]
        if not items:
            return {
                "windows": 0,
                "score_slope": 0.0,
                "candidates_per_second": 0.0,
                "duplicate_rate": 0.0,
                "diversity": 0.0,
                "operator_yield": 0.0,
            }
        return {
            "windows": len(items),
            "score_slope": _slope(
                (
                    float(item.get("end_high_water", 0)),
                    float(item.get("best_scalar", 0)),
                )
                for item in items
            ),
            "candidates_per_second": _mean(
                float(item.get("candidates_per_second", 0)) for item in items
            ),
            "duplicate_rate": _mean(
                float(item.get("duplicate_rate", 0)) for item in items
            ),
            "diversity": _mean(
                float(item.get("diversity", 0)) for item in items
            ),
            "operator_yield": _mean(
                float(item.get("operator_yield", 0)) for item in items
            ),
            "end_high_water": int(items[-1].get("end_high_water", 0)),
            "best_score": items[-1].get("best_score"),
        }


def compare_effects(
    pre: Iterable[dict[str, Any]],
    post: Iterable[dict[str, Any]],
    *,
    expected_direction: str | None = None,
) -> EffectComparison:
    before = _summary(pre)
    after = _summary(post)
    slope_change = after["score_slope"] - before["score_slope"]
    expectation_met: bool | None
    if expected_direction == "improve_score_slope":
        expectation_met = slope_change < 0
    elif expected_direction == "increase_diversity":
        expectation_met = after["diversity"] > before["diversity"]
    elif expected_direction == "increase_throughput":
        expectation_met = after["throughput"] > before["throughput"]
    else:
        expectation_met = None
    return EffectComparison(
        score_slope_change=slope_change,
        diversity_change=after["diversity"] - before["diversity"],
        throughput_change=after["throughput"] - before["throughput"],
        duplicate_rate_change=(
            after["duplicate_rate"] - before["duplicate_rate"]
        ),
        operator_yield_change=after["operator_yield"] - before["operator_yield"],
        expectation_met=expectation_met,
    )


def _summary(items: Iterable[dict[str, Any]]) -> dict[str, float]:
    values = list(items)
    return {
        "score_slope": _slope(
            (
                float(item.get("end_high_water", 0)),
                float(item.get("best_scalar", 0)),
            )
            for item in values
        ),
        "diversity": _mean(
            float(item.get("diversity", 0)) for item in values
        ),
        "throughput": _mean(
            float(item.get("candidates_per_second", 0)) for item in values
        ),
        "duplicate_rate": _mean(
            float(item.get("duplicate_rate", 0)) for item in values
        ),
        "operator_yield": _mean(
            float(item.get("operator_yield", 0)) for item in values
        ),
    }


def _mean(values: Iterable[float]) -> float:
    items = [value for value in values if math.isfinite(value)]
    return sum(items) / len(items) if items else 0.0


def _slope(points: Iterable[tuple[float, float]]) -> float:
    values = [(x, y) for x, y in points if math.isfinite(x) and math.isfinite(y)]
    if len(values) < 2:
        return 0.0
    mean_x = _mean(x for x, _ in values)
    mean_y = _mean(y for _, y in values)
    denominator = sum((x - mean_x) ** 2 for x, _ in values)
    if denominator <= 0:
        return 0.0
    return sum((x - mean_x) * (y - mean_y) for x, y in values) / denominator
