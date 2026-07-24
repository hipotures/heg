from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

from ..state import utc_now
from .catalog import REVIEW_EVENTS


INTERNAL_REASONS = {
    "bootstrap",
    "candidate_delta_reached",
    "maximum_review_interval",
    "recovery",
    "stale_action_replan",
}
CRITICAL_REASONS = {
    "verification_result",
    "verifier_disagreement",
    "lane_failure",
    "resource_pressure",
}
IMMEDIATE_REASONS = CRITICAL_REASONS | {
    "bootstrap",
    "maximum_review_interval",
    "recovery",
}
MANDATORY_EVENTS = CRITICAL_REASONS | {"action_lease_expired"}


@dataclass(frozen=True, slots=True)
class TriggerBatch:
    reasons: tuple[str, ...]
    first_event_at: str


class TriggerEngine:
    """Bounded event coalescing with critical bypass and review limits."""

    def __init__(
        self,
        *,
        debounce_seconds: float = 1.0,
        min_review_seconds: float = 0.0,
        max_review_seconds: float = 300.0,
        candidate_delta: int = 100_000,
    ):
        if debounce_seconds < 0:
            raise ValueError("debounce_seconds cannot be negative")
        if not 0 <= min_review_seconds <= max_review_seconds:
            raise ValueError("invalid review interval")
        if candidate_delta < 1:
            raise ValueError("candidate_delta must be positive")
        self.debounce_seconds = debounce_seconds
        self.min_review_seconds = min_review_seconds
        self.max_review_seconds = max_review_seconds
        self.candidate_delta = candidate_delta
        self.enabled_events = set(REVIEW_EVENTS)
        self._pending: set[str] = set()
        self._first_event_at: str | None = None
        self._first_monotonic: float | None = None
        self._last_review_monotonic = monotonic()
        self._last_review_candidates = 0
        self._lane_summaries: dict[str, dict[str, float]] = {}

    def offer(
        self, reason: str, *, at: str | None = None, now: float | None = None
    ) -> bool:
        if reason not in set(REVIEW_EVENTS) and reason not in INTERNAL_REASONS:
            raise ValueError(f"unsupported Director trigger: {reason}")
        if reason in REVIEW_EVENTS and reason not in self.enabled_events:
            return False
        current = monotonic() if now is None else now
        if not self._pending:
            self._first_monotonic = current
            self._first_event_at = at or utc_now()
        self._pending.add(reason)
        return True

    def observe_lane_event(
        self, event: dict[str, Any], *, recent_metrics: dict[str, Any]
    ) -> None:
        kind = event.get("kind")
        if kind == "improvement":
            self.offer("new_global_best", at=str(event.get("at") or utc_now()))
        elif kind == "exit" and event.get("reason") == "failure":
            self.offer("lane_failure", at=str(event.get("at") or utc_now()))
        elif kind == "telemetry":
            metrics = event.get("metrics", {})
            lane_id = str(event.get("lane_id"))
            previous = self._lane_summaries.get(lane_id)
            current = {
                "best_scalar": float(metrics.get("best_scalar", 0)),
                "operator_yield": float(metrics.get("operator_yield", 0)),
            }
            if previous is not None:
                if current["best_scalar"] < previous["best_scalar"]:
                    self.offer(
                        "meaningful_improvement",
                        at=str(event.get("at") or utc_now()),
                    )
                yield_delta = abs(
                    current["operator_yield"] - previous["operator_yield"]
                )
                if yield_delta >= 0.01:
                    self.offer(
                        "operator_yield_shift",
                        at=str(event.get("at") or utc_now()),
                    )
            self._lane_summaries[lane_id] = current
            if float(metrics.get("duplicate_rate", 0)) >= 0.8:
                self.offer(
                    "diversity_collapse",
                    at=str(event.get("at") or utc_now()),
                )
            if (
                int(recent_metrics.get("windows", 0)) >= 6
                and float(recent_metrics.get("operator_yield", 0)) == 0
            ):
                self.offer("stagnation", at=str(event.get("at") or utc_now()))

    def configure(self, review: dict[str, Any]) -> None:
        minimum = float(review["min_wall_seconds"])
        maximum = float(review["max_wall_seconds"])
        if not 10 <= minimum <= maximum <= 7200:
            raise ValueError("review interval is outside the reviewed domain")
        candidate_delta = int(review["candidate_delta"])
        if not 1 <= candidate_delta <= 100_000_000:
            raise ValueError("candidate delta is outside the reviewed domain")
        events = set(review["events"])
        if not events <= set(REVIEW_EVENTS):
            raise ValueError("review event is outside the reviewed catalog")
        self.min_review_seconds = minimum
        self.max_review_seconds = maximum
        self.candidate_delta = candidate_delta
        self.enabled_events = events | MANDATORY_EVENTS

    def due(
        self, *, total_candidates: int, now: float | None = None
    ) -> bool:
        current = monotonic() if now is None else now
        since_review = current - self._last_review_monotonic
        if since_review >= self.max_review_seconds:
            self.offer("maximum_review_interval", now=current)
        if (
            total_candidates - self._last_review_candidates
            >= self.candidate_delta
        ):
            self.offer("candidate_delta_reached", now=current)
        if not self._pending:
            return False
        if self._pending & IMMEDIATE_REASONS:
            return True
        if since_review < self.min_review_seconds:
            return False
        assert self._first_monotonic is not None
        return current - self._first_monotonic >= self.debounce_seconds

    def consume(
        self, *, total_candidates: int, now: float | None = None
    ) -> TriggerBatch:
        current = monotonic() if now is None else now
        if not self.due(total_candidates=total_candidates, now=current):
            raise RuntimeError("Director trigger is not due")
        batch = TriggerBatch(
            reasons=tuple(sorted(self._pending)),
            first_event_at=self._first_event_at or utc_now(),
        )
        self._pending.clear()
        self._first_event_at = None
        self._first_monotonic = None
        self._last_review_monotonic = current
        self._last_review_candidates = total_candidates
        return batch

    @property
    def pending_reasons(self) -> tuple[str, ...]:
        return tuple(sorted(self._pending))
