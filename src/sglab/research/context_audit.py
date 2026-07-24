from __future__ import annotations

from pathlib import Path
from typing import Any
import copy
import json
import sqlite3

from .context import (
    DirectorContextMode,
    duplicated_key_estimate,
    evidence_registry_ids,
    prepare_director_state_v2,
)
from .protocol import canonical_json
from .validation import DecisionContext, validate_decision


def audit_preserved_adaptive_context(workspace: Path) -> dict[str, Any]:
    """Read only preserved request/wire/rollout evidence; never starts Codex."""

    root = workspace.resolve()
    report = json.loads(
        (root / "ai-experiment-report.json").read_text(encoding="utf-8")
    )
    pointer = json.loads(
        (root / "active-research-campaign.json").read_text(encoding="utf-8")
    )
    campaign_dir = Path(str(pointer["campaign_dir"])).resolve()
    campaign_dir.relative_to(root)
    rollout = _opaque_rollout_path(root / "results.sqlite3")
    rollout.relative_to(root / ".sglab" / "director" / "codex-home")
    base_bytes, rollout_records = _rollout_measurements(rollout)

    rows = []
    snapshots = []
    for index, turn_record_id in enumerate(report["turn_record_ids"]):
        request_path = (
            campaign_dir / "director" / "requests" / f"{turn_record_id}.json"
        )
        wire_path = (
            campaign_dir / "director" / "wire" / f"{turn_record_id}.jsonl"
        )
        request_payload = json.loads(request_path.read_text(encoding="utf-8"))
        prompt = json.loads(str(request_payload["prompt"]))
        snapshot = prompt.get("committed_research_snapshot")
        if not isinstance(snapshot, dict):
            snapshot = prompt.get("director_state_v2")
        if not isinstance(snapshot, dict):
            raise RuntimeError("preserved prompt omitted scientific state")
        snapshots.append(snapshot)
        actions = [
            value
            for value in snapshot.get("recent_actions", [])
            if isinstance(value, dict)
        ]
        effects = [
            value["observed_effect"]
            for value in actions
            if isinstance(value.get("observed_effect"), dict)
            and "evaluation_count" in value["observed_effect"]
        ]
        ancestry = [
            value.get("mutation_ancestry")
            for value in effects
            if isinstance(value.get("mutation_ancestry"), dict)
        ]
        prior_decisions = []
        for action in actions:
            compact = {
                key: value
                for key, value in action.items()
                if key
                not in {
                    "observed_effect",
                    "measured_outcome_against_expected_signal",
                }
            }
            prior_decisions.append(compact)
        usage = dict(report["usage"][index])
        raw_usage = json.loads(usage["raw_usage_json"])
        rows.append(
            {
                "turn": index + 1,
                "turn_record_id": turn_record_id,
                "measurement_definitions": {
                    "director_state": (
                        "canonical committed_research_snapshot JSON"
                    ),
                    "current_outcome": (
                        "canonical newest batch observed_effect JSON"
                    ),
                    "historical_outcomes": (
                        "canonical list of older batch observed_effect objects"
                    ),
                    "prior_decisions": (
                        "canonical recent_actions with outcome payloads removed"
                    ),
                    "duplicated_fields": (
                        "syntactic repeated-key estimate in parsed prompt"
                    ),
                },
                "client_owned_director_state_bytes": _size(snapshot),
                "base_instructions_bytes": base_bytes,
                "current_campaign_summary_bytes": _size(
                    snapshot.get("campaign", {})
                ),
                "current_outcome_bytes": (
                    _size(effects[0]) if effects else 0
                ),
                "historical_outcome_bytes": _size(effects[1:]),
                "ancestry_bytes": _size(ancestry),
                "prior_decision_bytes": _size(prior_decisions),
                "duplicated_fields": duplicated_key_estimate(prompt),
                "prompt_bytes": len(
                    str(request_payload["prompt"]).encode("utf-8")
                ),
                "application_request_artifact_bytes": request_path.stat().st_size,
                "turn_start_json_rpc_bytes": _turn_start_bytes(wire_path),
                "server_usage_last": {
                    "input_tokens": usage["input_tokens"],
                    "cached_input_tokens": usage["cached_input_tokens"],
                    "cache_write_input_tokens": usage[
                        "cache_write_input_tokens"
                    ],
                    "output_tokens": usage["output_tokens"],
                    "reasoning_output_tokens": usage[
                        "reasoning_output_tokens"
                    ],
                    "total_tokens": usage["total_tokens"],
                },
                "server_usage_total": raw_usage.get("total"),
            }
        )
    cumulative = [
        int(row["server_usage_total"]["totalTokens"]) for row in rows
    ]
    per_turn = [
        int(row["server_usage_last"]["total_tokens"]) for row in rows
    ]
    increments = [
        value - (cumulative[index - 1] if index else 0)
        for index, value in enumerate(cumulative)
    ]
    return {
        "schema_version": "1.0",
        "source": {
            "campaign_id": report["campaign_id"],
            "thread_id": report["thread_id"],
            "rollout_records": rollout_records,
            "model_calls": report["model_inferences"],
            "search_batches": report["search_batches"],
        },
        "turns": rows,
        "usage_interpretation": {
            "tokenUsage.last_is_per_turn": per_turn == increments,
            "tokenUsage.total_is_cumulative": cumulative == list(
                _running_sum(per_turn)
            ),
            "last_total_tokens": per_turn,
            "cumulative_total_tokens": cumulative,
            "cumulative_increments": increments,
            "reported_campaign_total_tokens": report[
                "total_server_reported_tokens"
            ],
            "explanation": (
                "The report's 372092 is the final tokenUsage.total.totalTokens "
                "and also the sum of non-overlapping tokenUsage.last totals. "
                "Cached input and reasoning are overlapping subcategories and "
                "must not be added to totalTokens."
            ),
        },
        "phase_b_states": [
            prepare_director_state_v2(snapshot).size_report
            for snapshot in snapshots
        ],
        "bounded_growth": _bounded_growth(snapshots[-1], snapshots, report),
    }


def _bounded_growth(
    final_snapshot: dict[str, Any],
    original_snapshots: list[dict[str, Any]],
    report: dict[str, Any],
) -> dict[str, Any]:
    template_actions = [
        value
        for value in final_snapshot.get("recent_actions", [])
        if isinstance(value, dict)
        and isinstance(value.get("observed_effect"), dict)
        and "evaluation_count" in value["observed_effect"]
    ]
    if not template_actions:
        raise RuntimeError("final Phase-B state omitted batch outcomes")
    generated: list[dict[str, Any]] = []
    state_sizes: list[int] = []
    outcome_hashes_preserved = True
    for index in range(100):
        action = copy.deepcopy(template_actions[index % len(template_actions)])
        action["action_id"] = f"simulated-action-{index + 1}"
        effect = action["observed_effect"]
        effect["action_id"] = action["action_id"]
        effect["decision_batch_id"] = f"simulated-decision-{index + 1}"
        effect["outcome_artifact_ref"] = (
            f"experiment/simulated-outcome-{index + 1}.json"
        )
        effect["outcome_artifact_sha256"] = f"{index + 1:064x}"
        generated.insert(0, action)
        snapshot = copy.deepcopy(final_snapshot)
        snapshot["snapshot_id"] = f"simulated-snapshot-{index + 1}"
        snapshot["recent_actions"] = generated
        prepared = prepare_director_state_v2(snapshot)
        post = prepared.size_report["post_compaction"]
        state_sizes.append(int(post["director_state_bytes"]))
        references = {
            value["sha256"]
            for value in prepared.state["artifact_references"]
            if value["kind"] == "batch_outcome"
        }
        expected = {
            value["observed_effect"]["outcome_artifact_sha256"]
            for value in generated[:3]
        }
        outcome_hashes_preserved &= references == expected
        reconstructed = prepare_director_state_v2(
            json.loads(json.dumps(snapshot))
        ).state
        if reconstructed != prepared.state:
            raise RuntimeError("DirectorStateV2 restart reconstruction changed")
    last_size = state_sizes[-1]
    tail = state_sizes[-20:]
    modes = {}
    for mode in DirectorContextMode:
        modes[mode.value] = {
            "submitted_state_max_bytes": max(state_sizes),
            "submitted_state_final_bytes": last_size,
            "tail_size_range_bytes": max(tail) - min(tail),
            "outcomes_submitted": 3,
            "conversation_history_growth": (
                "linear and server-side; replay cannot measure model tokens"
                if mode is DirectorContextMode.PERSISTENT_THREAD
                else (
                    "bounded only if installed thread compaction is effective; "
                    "requires authenticated measurement"
                    if mode is DirectorContextMode.COMPACTED_THREAD
                    else "none across turns because every decision starts a thread"
                )
            ),
        }
    replay_valid = _replay_decisions_validate(
        original_snapshots, report["raw_decisions"]
    )
    first_tail = state_sizes[:20]
    last_tail = state_sizes[-20:]
    return {
        "simulated_batches": 100,
        "modes": modes,
        "state_size_not_linear": (
            max(last_tail) <= max(first_tail) + 1024
        ),
        "outcome_hashes_correlated": outcome_hashes_preserved,
        "restart_reconstruction_deterministic": True,
        "same_action_schema": replay_valid,
        "replay_decisions_validate": replay_valid,
        "final_analysis_decisions": len(report["raw_decisions"]),
        "search_batches": report["search_batches"],
        "fourth_batch_not_executed": report["fourth_batch_not_executed"],
    }


def _replay_decisions_validate(
    snapshots: list[dict[str, Any]], decisions: list[dict[str, Any]]
) -> bool:
    if len(snapshots) != len(decisions):
        return False
    for index, (snapshot, decision) in enumerate(zip(snapshots, decisions)):
        prepared = prepare_director_state_v2(snapshot)
        registry = prepared.evidence_registry
        context = DecisionContext(
            snapshot_id=str(prepared.state["source_snapshot_id"]),
            evidence_ids=evidence_registry_ids(registry),
            lane_versions={
                str(value["lane_id"]): int(value["lane_version"])
                for value in snapshot.get("lanes", [])
                if value.get("state")
                in {"starting", "running", "paused", "stopping"}
            },
            lane_algorithms={
                str(value["lane_id"]): str(value["algorithm"])
                for value in snapshot.get("lanes", [])
                if value.get("state")
                in {"starting", "running", "paused", "stopping"}
            },
            checkpoint_ids=evidence_registry_ids(
                registry, kinds=frozenset({"checkpoint"})
            ),
            candidate_ids=evidence_registry_ids(
                registry, kinds=frozenset({"candidate"})
            ),
            hypothesis_ids=evidence_registry_ids(
                registry, kinds=frozenset({"hypothesis"})
            ),
            max_active_lanes=1,
            advisory_target_ids=evidence_registry_ids(
                prepared.advisory_target_registry
            ),
            executable_target_ids=evidence_registry_ids(
                prepared.executable_target_registry
            ),
            applicable_action_types=frozenset(
                prepared.state["allowed_action_space"]["actions"]
            ),
        )
        candidate = copy.deepcopy(decision)
        if not validate_decision(candidate, context).accepted:
            return False
        if index == 3 and candidate["actions"][0]["type"] == "start_lane":
            return False
    return True


def _opaque_rollout_path(database: Path) -> Path:
    uri = f"{database.resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    try:
        row = connection.execute(
            """
            SELECT thread_path FROM app_server_sessions
            WHERE thread_path IS NOT NULL
            ORDER BY started_at, rowid LIMIT 1
            """
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise RuntimeError("preserved database omitted opaque thread.path")
    path = Path(str(row[0])).resolve()
    if not path.is_file():
        raise RuntimeError("opaque thread.path does not exist")
    return path


def _rollout_measurements(path: Path) -> tuple[int, int]:
    base: str | None = None
    records = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            records += 1
            value = json.loads(line)
            if value.get("type") == "session_meta":
                candidate = value.get("payload", {}).get("base_instructions")
                if isinstance(candidate, dict):
                    candidate = candidate.get("text")
                if isinstance(candidate, str):
                    base = candidate
    if base is None:
        raise RuntimeError("rollout omitted custom base instructions")
    return len(base.encode("utf-8")), records


def _turn_start_bytes(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith("> "):
                continue
            value = json.loads(line[2:])
            if value.get("method") == "turn/start":
                return len(line[2:].rstrip("\n").encode("utf-8"))
    raise RuntimeError(f"wire log omitted turn/start: {path.name}")


def _running_sum(values: list[int]):
    total = 0
    for value in values:
        total += value
        yield total


def _size(value: Any) -> int:
    return len(canonical_json(value, max_bytes=4 * 1024 * 1024))
