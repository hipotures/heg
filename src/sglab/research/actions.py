from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
import hashlib
import json

from .lanes import LaneManager, LaneSpec
from .store import ResearchStore


LANE_ACTION_TYPES = {
    "start_lane",
    "patch_lane",
    "fork_lane",
    "restart_lane",
    "stop_lane",
    "reallocate_resources",
}


class LaneActionDispatcher:
    """Deliver committed lane actions and persist worker-boundary outcomes."""

    def __init__(
        self,
        *,
        store: ResearchStore,
        manager: LaneManager,
        campaign_id: str,
    ):
        self.store = store
        self.manager = manager
        self.campaign_id = campaign_id
        self.inflight_actions: set[str] = set()
        self._births: dict[str, set[str]] = {}
        self._birth_action_by_lane: dict[str, str] = {}
        self._allocation_parent: dict[str, str] = {}
        self._allocation_expected: dict[str, int] = {}
        self._allocation_outcomes: dict[str, list[dict[str, Any]]] = {}
        self._allocation_counts: dict[str, int] = {}

    def dispatch_pending(self) -> list[str]:
        dispatched: list[str] = []
        for row in self.store.pending_accepted_actions(self.campaign_id):
            action_id = str(row["action_id"])
            if action_id in self.inflight_actions:
                continue
            action_type = str(row["action_type"])
            if action_type not in LANE_ACTION_TYPES:
                continue
            if _expired(str(row["lease_expires_at"])):
                self.store.record_action_outcome(
                    action_id=action_id,
                    status="rejected_lease_expired",
                    failure_kind="action_lease_expired",
                    failure_detail="action was not delivered before its lease expired",
                )
                continue
            self.inflight_actions.add(action_id)
            try:
                self._dispatch(row)
            except Exception as error:
                self.inflight_actions.discard(action_id)
                for runtime in self.manager.lanes.values():
                    if runtime.spec.created_by_action_id == action_id:
                        runtime.stop_event.set()
                self.store.mark_lane_birth_failed(action_id, str(error))
                self.store.record_action_outcome(
                    action_id=action_id,
                    status="failed",
                    failure_kind=type(error).__name__,
                    failure_detail=str(error)[:2000],
                )
                continue
            dispatched.append(action_id)
        return dispatched

    def _dispatch(self, row: dict[str, Any]) -> None:
        action_id = str(row["action_id"])
        action_type = str(row["action_type"])
        parameters = json.loads(str(row["parameters_json"]))
        if action_type == "start_lane":
            self._start(action_id, parameters["spec"], row)
        elif action_type == "patch_lane":
            self.manager.send_patch(
                str(row["target_lane_id"]),
                action_id=action_id,
                expected_lane_version=int(row["expected_lane_version"]),
                patch=parameters["patch"],
            )
        elif action_type == "fork_lane":
            self._fork(action_id, row, parameters)
        elif action_type == "restart_lane":
            restart = parameters["restart_spec"]
            if restart["source"] == "archive_elite":
                raise ValueError(
                    "archive restart requires the candidate broker"
                )
            self.manager.restart_lane(
                str(row["target_lane_id"]),
                action_id=action_id,
                expected_lane_version=int(row["expected_lane_version"]),
                seed=int(restart["seed"]),
                checkpoint_id=(
                    str(restart["checkpoint_id"])
                    if restart["source"] == "checkpoint"
                    else None
                ),
            )
        elif action_type == "stop_lane":
            self.manager.stop_lane(
                str(row["target_lane_id"]),
                action_id=action_id,
                expected_lane_version=int(row["expected_lane_version"]),
            )
        elif action_type == "reallocate_resources":
            allocations = list(parameters["allocations"])
            self._allocation_counts[action_id] = len(allocations)
            self._allocation_outcomes[action_id] = []
            for allocation in allocations:
                lane_id = str(allocation["lane_id"])
                subaction_id = f"{action_id}:{lane_id}"
                self._allocation_parent[subaction_id] = action_id
                self._allocation_expected[subaction_id] = int(
                    allocation["expected_lane_version"]
                )
                self.manager.reallocate_lane(
                    lane_id,
                    action_id=subaction_id,
                    expected_lane_version=int(
                        allocation["expected_lane_version"]
                    ),
                    resource_share=float(allocation["resource_share"]),
                )

    def _start(
        self, action_id: str, spec_value: dict[str, Any], row: dict[str, Any]
    ) -> None:
        campaign = self.store.campaign(self.campaign_id)
        lane_id = _derived_id("lane", action_id)
        spec = LaneSpec(
            lane_id=lane_id,
            campaign_id=self.campaign_id,
            target=str(campaign["target"]),
            algorithm=str(spec_value["algorithm"]),
            graph_family=str(spec_value["graph_family"]),
            seed=int(spec_value["seed"]),
            parameters=dict(spec_value["parameters"]),
            resource_share=float(spec_value["resource_share"]),
            created_by_action_id=action_id,
            seed_lineage=(int(spec_value["seed"]),),
        )
        self.store.create_lane(
            lane_id=lane_id,
            campaign_id=self.campaign_id,
            target=spec.target,
            parent_lane_id=None,
            parent_checkpoint_ref=None,
            action_id=action_id,
            algorithm=spec.algorithm,
            graph_family=spec.graph_family,
            parameters=spec.parameters,
            seed_lineage=list(spec.seed_lineage),
            resource_share=spec.resource_share,
            lease_expires_at=str(row["lease_expires_at"]),
        )
        self._register_births(action_id, [lane_id])
        self.manager.start_lane(spec)

    def _fork(
        self,
        action_id: str,
        row: dict[str, Any],
        parameters: dict[str, Any],
    ) -> None:
        parent_lane_id = str(row["target_lane_id"])
        parent = self.manager.lanes[parent_lane_id]
        checkpoint_id = str(parameters["checkpoint_id"])
        children: list[str] = []
        for index, variant in enumerate(parameters["variants"]):
            child_lane_id = _derived_id(
                "lane", f"{action_id}:{index}:{variant['name']}"
            )
            fork_seed = _derived_seed(action_id, child_lane_id)
            child_parameters = {**parent.parameters, **variant["patch"]}
            seed_lineage = (
                *parent.spec.seed_lineage,
                parent.spec.seed,
                fork_seed,
            )
            self.store.create_lane(
                lane_id=child_lane_id,
                campaign_id=self.campaign_id,
                target=parent.spec.target,
                parent_lane_id=parent_lane_id,
                parent_checkpoint_ref=checkpoint_id,
                action_id=action_id,
                algorithm=parent.spec.algorithm,
                graph_family=parent.spec.graph_family,
                parameters=child_parameters,
                seed_lineage=list(seed_lineage),
                resource_share=float(variant["resource_share"]),
                lease_expires_at=str(row["lease_expires_at"]),
            )
            children.append(child_lane_id)
            self.manager.fork_lane(
                parent_lane_id,
                child_lane_id=child_lane_id,
                action_id=action_id,
                expected_lane_version=int(row["expected_lane_version"]),
                checkpoint_id=checkpoint_id,
                patch=dict(variant["patch"]),
                resource_share=float(variant["resource_share"]),
            )
        self._register_births(action_id, children)

    def _register_births(self, action_id: str, lane_ids: list[str]) -> None:
        self._births[action_id] = set(lane_ids)
        for lane_id in lane_ids:
            self._birth_action_by_lane[lane_id] = action_id

    def poll_once(self, timeout: float = 0.1) -> dict[str, Any] | None:
        event = self.manager.poll(timeout=timeout)
        if event is not None:
            self.handle_event(event)
        return event

    def handle_event(self, event: dict[str, Any]) -> None:
        kind = str(event["kind"])
        lane_id = str(event["lane_id"])
        if kind == "checkpoint":
            checkpoint = dict(event["checkpoint"])
            self.store.record_lane_checkpoint(
                lane_id=lane_id,
                lane_version=int(checkpoint["lane_version"]),
                checkpoint_ref=self._checkpoint_ref(
                    str(checkpoint["checkpoint_id"])
                ),
                checkpoint_sha256=str(checkpoint["sha256"]),
                high_water=int(checkpoint["high_water"]),
            )
        elif kind == "telemetry":
            metrics = dict(event["metrics"])
            end = int(metrics["end_high_water"])
            start = max(0, end - int(metrics["evaluated"]))
            self.store.record_lane_metric_window(
                metric_window_id=_derived_id(
                    "metric", f"{lane_id}:{event['lane_version']}:{end}"
                ),
                lane_id=lane_id,
                campaign_id=self.campaign_id,
                lane_version=int(event["lane_version"]),
                start_high_water=start,
                end_high_water=end,
                started_at=str(event["at"]),
                ended_at=str(event["at"]),
                metrics=metrics,
                retention=self.manager.telemetry_windows,
            )
        elif kind == "ready":
            self._handle_ready(lane_id)
        elif kind == "action_outcome":
            self._handle_action_outcome(event)
        elif kind == "exit":
            self._handle_exit(event)

    def _handle_ready(self, lane_id: str) -> None:
        action_id = self._birth_action_by_lane.get(lane_id)
        if action_id is None:
            return
        pending = self._births[action_id]
        pending.discard(lane_id)
        if pending:
            return
        lane_ids = sorted(
            lane
            for lane, owner in self._birth_action_by_lane.items()
            if owner == action_id
        )
        self.store.complete_lane_births(
            action_id=action_id,
            lane_ids=lane_ids,
            observed_effect={"started_lane_ids": lane_ids},
        )
        self.inflight_actions.discard(action_id)
        self._births.pop(action_id, None)
        for child in lane_ids:
            self._birth_action_by_lane.pop(child, None)

    def _handle_action_outcome(self, event: dict[str, Any]) -> None:
        worker_action_id = str(event["action_id"])
        parent = self._allocation_parent.get(worker_action_id)
        if parent is not None:
            outcome = {
                **event,
                "expected_lane_version": self._allocation_expected[
                    worker_action_id
                ],
            }
            outcomes = self._allocation_outcomes[parent]
            outcomes.append(outcome)
            if len(outcomes) == self._allocation_counts[parent]:
                self._complete_allocation(parent, outcomes)
            return
        checkpoint_id = event.get("checkpoint_id")
        checkpoint = (
            self.manager.checkpoints.get(str(checkpoint_id))
            if checkpoint_id is not None
            else None
        )
        status = str(event["status"])
        self.store.apply_lane_action_outcome(
            action_id=worker_action_id,
            status=status,
            resulting_lane_id=str(event["lane_id"]),
            resulting_lane_version=int(event["resulting_lane_version"]),
            checkpoint_ref=(
                self._checkpoint_ref(str(checkpoint_id))
                if checkpoint is not None
                else None
            ),
            checkpoint_sha256=(
                str(checkpoint["sha256"]) if checkpoint is not None else None
            ),
            parameters=(
                dict(event["parameters"])
                if isinstance(event.get("parameters"), dict)
                else None
            ),
            resource_share=(
                float(event["resource_share"])
                if event.get("resource_share") is not None
                else None
            ),
            failure_kind=(
                "worker_action_rejected" if status != "applied" else None
            ),
            failure_detail=(
                str(event.get("failure") or status)
                if status != "applied"
                else None
            ),
        )
        self.inflight_actions.discard(worker_action_id)

    def _handle_exit(self, event: dict[str, Any]) -> None:
        lane_id = str(event["lane_id"])
        failed = event.get("reason") == "failure"
        version = int(
            event.get(
                "lane_version",
                self.manager.lanes[lane_id].lane_version,
            )
        )
        self.store.record_lane_exit(
            lane_id=lane_id,
            lane_version=version,
            failed=failed,
            detail=str(event.get("error")) if failed else None,
        )
        birth_action = self._birth_action_by_lane.pop(lane_id, None)
        if birth_action is not None and birth_action in self.inflight_actions:
            siblings = [
                child
                for child, owner in self._birth_action_by_lane.items()
                if owner == birth_action
            ]
            for sibling in siblings:
                self.manager.lanes[sibling].stop_event.set()
                self._birth_action_by_lane.pop(sibling, None)
            self.store.mark_lane_birth_failed(
                birth_action, str(event.get("error") or "lane exited before ready")
            )
            self.store.record_action_outcome(
                action_id=birth_action,
                status="failed",
                failure_kind="lane_start_failure",
                failure_detail=str(event.get("error") or "lane exited before ready"),
            )
            self.inflight_actions.discard(birth_action)
            self._births.pop(birth_action, None)

    def _complete_allocation(
        self, action_id: str, outcomes: list[dict[str, Any]]
    ) -> None:
        failures = [
            outcome for outcome in outcomes if outcome["status"] != "applied"
        ]
        if failures:
            self.store.record_action_outcome(
                action_id=action_id,
                status="failed",
                failure_kind="partial_allocation_failure",
                failure_detail=json.dumps(failures, sort_keys=True)[:2000],
            )
        else:
            revisions: list[dict[str, Any]] = []
            for outcome in outcomes:
                checkpoint_id = str(outcome["checkpoint_id"])
                checkpoint = self.manager.checkpoints[checkpoint_id]
                revisions.append(
                    {
                        "lane_id": str(outcome["lane_id"]),
                        "expected_lane_version": int(
                            outcome["expected_lane_version"]
                        ),
                        "resulting_lane_version": int(
                            outcome["resulting_lane_version"]
                        ),
                        "resource_share": float(outcome["resource_share"]),
                        "checkpoint_ref": self._checkpoint_ref(checkpoint_id),
                        "checkpoint_sha256": str(checkpoint["sha256"]),
                    }
                )
            self.store.apply_multi_lane_action_outcome(
                action_id=action_id, revisions=revisions
            )
        self.inflight_actions.discard(action_id)
        self._allocation_outcomes.pop(action_id, None)
        self._allocation_counts.pop(action_id, None)
        for worker_id, owner in list(self._allocation_parent.items()):
            if owner == action_id:
                self._allocation_parent.pop(worker_id, None)
                self._allocation_expected.pop(worker_id, None)

    def _checkpoint_ref(self, checkpoint_id: str) -> str:
        path = self.manager.checkpoint_dir / f"{checkpoint_id}.json"
        try:
            return str(path.relative_to(self.manager.campaign_dir))
        except ValueError:
            raise RuntimeError("checkpoint escaped campaign directory") from None


def _derived_id(prefix: str, value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}-{digest}"


def _derived_seed(action_id: str, lane_id: str) -> int:
    return int.from_bytes(
        hashlib.sha256(f"{action_id}:{lane_id}".encode()).digest()[:8], "big"
    ) & (2**63 - 1)


def _expired(value: str) -> bool:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(UTC) <= datetime.now(UTC)
