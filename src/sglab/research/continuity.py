from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from pathlib import Path
from typing import Any
import hashlib
import json
import os
import subprocess

from .protocol import canonical_json


DEFAULT_SCIENTIFIC_STATE_SOFT_BYTES = 24_576
DEFAULT_SCIENTIFIC_STATE_HARD_BYTES = 32_768
DEFAULT_SCIENTIFIC_SNAPSHOT_INTERVAL = 5
CONTINUITY_LEDGER_LIMITS = {
    "hypothesis_ledger": 64,
    "exact_verifier_outcomes": 32,
    "candidate_ledger": 64,
    "lane_and_checkpoint_ledger": 64,
    "validation_feedback": 4,
}
RESUMABLE_CAMPAIGN_STATES = frozenset(
    {
        "paused_by_operator",
        "stopped_by_operator",
        "completed_deadline_reached",
        "deadline_reached",
        "budget_exhausted",
        "paused_fault",
        "interrupted",
        "infrastructure_failure",
    }
)
NON_RESUMABLE_CAMPAIGN_STATES = frozenset(
    {"running", "succeeded_certified_counterexample", "certified_success",
     "scientifically_invalidated"}
)


class ScientificStateOverflow(RuntimeError):
    pass


class CampaignResumeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ScientificMemoryPolicy:
    soft_limit_bytes: int = DEFAULT_SCIENTIFIC_STATE_SOFT_BYTES
    hard_limit_bytes: int = DEFAULT_SCIENTIFIC_STATE_HARD_BYTES
    snapshot_interval_cycles: int = DEFAULT_SCIENTIFIC_SNAPSHOT_INTERVAL

    def __post_init__(self) -> None:
        if not 1024 <= self.soft_limit_bytes <= self.hard_limit_bytes:
            raise ValueError("scientific-state soft limit is invalid")
        if not self.hard_limit_bytes <= 256 * 1024:
            raise ValueError("scientific-state hard limit is invalid")
        if not 1 <= self.snapshot_interval_cycles <= 1000:
            raise ValueError("scientific snapshot interval is invalid")


@dataclass(frozen=True, slots=True)
class CampaignResources:
    cpu_workers: int
    maximum_active_lanes: int
    maximum_aggregate_resource_share: float
    lane_memory_bytes: int
    verifier_concurrency: int
    verifier_memory_bytes: int
    verification_queue_depth: int

    def __post_init__(self) -> None:
        if not 1 <= self.cpu_workers <= 1024:
            raise ValueError("CPU worker limit must be between 1 and 1024")
        if not 1 <= self.maximum_active_lanes <= 1024:
            raise ValueError("active lane limit must be between 1 and 1024")
        if not 0 < self.maximum_aggregate_resource_share <= 1024:
            raise ValueError("aggregate lane resource share is invalid")
        if self.lane_memory_bytes < 16 * 1024 * 1024:
            raise ValueError("lane memory limit is too small")
        if not 1 <= self.verifier_concurrency <= 128:
            raise ValueError("verifier concurrency is invalid")
        if self.verifier_memory_bytes < 16 * 1024 * 1024:
            raise ValueError("verifier memory limit is too small")
        if not 1 <= self.verification_queue_depth <= 100_000:
            raise ValueError("verification queue limit is invalid")

    @classmethod
    def from_plan(
        cls,
        plan: dict[str, Any] | None,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> CampaignResources:
        source = plan or {}
        search = source.get("search_limits") or {}
        verify = source.get("verification_limits") or {}
        override = overrides or {}
        cpu_workers = int(
            override.get(
                "cpu_workers",
                search.get(
                    "cpu_workers",
                    search.get(
                        "maximum_active_lanes",
                        max(1, min(8, os.cpu_count() or 1)),
                    ),
                ),
            )
        )
        requested_lanes = int(
            override.get(
                "maximum_active_lanes",
                search.get("maximum_active_lanes", cpu_workers),
            )
        )
        # One search lane is one application-owned worker process. This is a
        # concurrency limit, not OS CPU isolation.
        effective_lanes = min(requested_lanes, cpu_workers)
        return cls(
            cpu_workers=cpu_workers,
            maximum_active_lanes=effective_lanes,
            maximum_aggregate_resource_share=float(
                override.get(
                    "maximum_aggregate_resource_share",
                    search.get(
                        "maximum_aggregate_resource_share",
                        effective_lanes,
                    ),
                )
            ),
            lane_memory_bytes=int(
                override.get(
                    "lane_memory_bytes",
                    search.get("lane_memory_limit_bytes", 512 * 1024 * 1024),
                )
            ),
            verifier_concurrency=int(
                override.get(
                    "verifier_concurrency",
                    verify.get("maximum_concurrent_jobs", 1),
                )
            ),
            verifier_memory_bytes=int(
                override.get(
                    "verifier_memory_bytes",
                    verify.get(
                        "verifier_memory_limit_bytes",
                        512 * 1024 * 1024,
                    ),
                )
            ),
            verification_queue_depth=int(
                override.get(
                    "verification_queue_depth",
                    verify.get("maximum_queue_depth", 32),
                )
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "cpu_workers": self.cpu_workers,
            "cpu_worker_enforcement": "application_worker_slots",
            "maximum_active_lanes": self.maximum_active_lanes,
            "maximum_aggregate_resource_share": (
                self.maximum_aggregate_resource_share
            ),
            "lane_memory_bytes": self.lane_memory_bytes,
            "verifier_concurrency": self.verifier_concurrency,
            "verifier_memory_bytes": self.verifier_memory_bytes,
            "verification_queue_depth": self.verification_queue_depth,
        }


class ScientificMemoryCompactor:
    """Deterministic, bounded projection; source rows remain untouched."""

    def __init__(self, policy: ScientificMemoryPolicy):
        self.policy = policy

    def project(
        self,
        current: dict[str, Any],
        *,
        previous: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        value = json.loads(json.dumps(current, sort_keys=True))
        if previous:
            for key in ("best_ever_result", "exact_verifier"):
                if value.get(key) is None and previous.get(key) is not None:
                    value[key] = previous[key]
            prior = [
                item
                for item in previous.get("previous_outcomes", [])
                if item not in value.get("previous_outcomes", [])
            ]
            value["previous_outcomes"] = (
                list(value.get("previous_outcomes", [])) + prior
            )
            self._merge_continuity(value, previous)
        self._secondary_bound(value)
        payload = self.encode(value)
        if len(payload) > self.policy.hard_limit_bytes:
            raise ScientificStateOverflow(
                "scientific_state_overflow: deterministic projection remains "
                f"{len(payload)} bytes with a "
                f"{self.policy.hard_limit_bytes}-byte hard limit"
            )
        return value

    @staticmethod
    def _merge_continuity(
        value: dict[str, Any], previous: dict[str, Any]
    ) -> None:
        current = value.setdefault("continuity", {})
        prior = previous.get("continuity")
        if not isinstance(current, dict) or not isinstance(prior, dict):
            return
        for key in (
            "latest_valid_assessment",
            "infrastructure_fault",
        ):
            if current.get(key) is None and prior.get(key) is not None:
                current[key] = prior[key]
        for key, identifier in (
            ("hypothesis_ledger", "hypothesis_id"),
            ("exact_verifier_outcomes", "candidate_id"),
            ("candidate_ledger", "candidate_id"),
            ("lane_and_checkpoint_ledger", "lane_id"),
            ("validation_feedback", "action_id"),
        ):
            merged: list[dict[str, Any]] = []
            seen: set[str] = set()
            for item in [
                *current.get(key, []),
                *prior.get(key, []),
            ]:
                if not isinstance(item, dict):
                    continue
                identity = str(item.get(identifier, ""))
                if identity and identity not in seen:
                    seen.add(identity)
                    merged.append(item)
            current[key] = merged[:CONTINUITY_LEDGER_LIMITS[key]]
        current["current_executable_candidate_ids"] = sorted(
            {
                str(item)
                for item in current.get(
                    "current_executable_candidate_ids", []
                )
                if isinstance(item, str)
            }
        )

    def encode(self, value: dict[str, Any]) -> bytes:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")

    def _secondary_bound(self, value: dict[str, Any]) -> None:
        while len(self.encode(value)) > self.policy.hard_limit_bytes:
            outcomes = value.get("previous_outcomes")
            ancestry = value.get("ancestry")
            if isinstance(outcomes, list) and outcomes:
                outcomes.pop()
                continue
            if isinstance(ancestry, dict):
                ancestors = ancestry.get("final_best_accepted_ancestors")
                records = ancestry.get("global_record_summaries")
                if isinstance(ancestors, list) and ancestors:
                    ancestors.pop(0)
                    continue
                if isinstance(records, list) and records:
                    records.pop(0)
                    continue
            artifacts = value.get("artifact_references")
            if isinstance(artifacts, list):
                removable = next(
                    (
                        index
                        for index, item in enumerate(artifacts)
                        if isinstance(item, dict)
                        and item.get("kind")
                        not in {"verification", "exact_verifier"}
                    ),
                    None,
                )
                if removable is not None:
                    artifacts.pop(removable)
                    continue
            continuity = value.get("continuity")
            if isinstance(continuity, dict):
                reduced = False
                for key in (
                    "validation_feedback",
                    "explored_regions",
                    "unresolved_scientific_questions",
                ):
                    items = continuity.get(key)
                    if isinstance(items, list) and items:
                        items.pop()
                        reduced = True
                        break
                if reduced:
                    continue
                candidates = continuity.get("candidate_ledger")
                if isinstance(candidates, list):
                    rich_candidate = next(
                        (
                            item
                            for item in reversed(candidates)
                            if isinstance(item, dict)
                            and (
                                "score" in item
                                or "checkpoint_ref" in item
                                or "lane_id" in item
                            )
                        ),
                        None,
                    )
                    if rich_candidate is not None:
                        for key in ("score", "checkpoint_ref", "lane_id"):
                            rich_candidate.pop(key, None)
                        continue
                lanes = continuity.get("lane_and_checkpoint_ledger")
                if isinstance(lanes, list):
                    rich_lane = next(
                        (
                            item
                            for item in reversed(lanes)
                            if isinstance(item, dict)
                            and "parameters" in item
                        ),
                        None,
                    )
                    if rich_lane is not None:
                        parameters = rich_lane.pop("parameters")
                        rich_lane["parameters_sha256"] = hashlib.sha256(
                            json.dumps(
                                parameters,
                                sort_keys=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        ).hexdigest()
                        continue
                hypotheses = continuity.get("hypothesis_ledger")
                if isinstance(hypotheses, list):
                    rich = next(
                        (
                            item
                            for item in reversed(hypotheses)
                            if isinstance(item, dict)
                            and item.get("statement")
                        ),
                        None,
                    )
                    if rich is not None:
                        rich["statement_sha256"] = hashlib.sha256(
                            str(rich["statement"]).encode("utf-8")
                        ).hexdigest()
                        rich["statement"] = ""
                        continue
            break


def memory_snapshot_record(
    *,
    memory_snapshot_id: str,
    campaign_id: str,
    version: int,
    parent_snapshot_id: str | None,
    director_snapshot_id: str | None,
    projection: dict[str, Any],
    source_high_water: dict[str, Any],
    source_record_counts: dict[str, int],
    creation_trigger: str,
    hard_limit_bytes: int,
) -> dict[str, Any]:
    payload = canonical_json(projection, max_bytes=hard_limit_bytes)
    return {
        "memory_snapshot_id": memory_snapshot_id,
        "campaign_id": campaign_id,
        "version": version,
        "parent_snapshot_id": parent_snapshot_id,
        "director_snapshot_id": director_snapshot_id,
        "source_high_water": source_high_water,
        "canonical_json": payload.decode("ascii"),
        "byte_size": len(payload),
        "estimated_token_count": ceil(len(payload) / 4),
        "source_record_counts": source_record_counts,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "creation_trigger": creation_trigger,
    }


def repository_commit(repository: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    )
    return result.stdout.strip()
