from __future__ import annotations

from pathlib import Path
from typing import Any
import asyncio
import hashlib
import json
import re

from ..state import atomic_write_json, utc_now
from .app_server_client import AppServerClient, AppServerConfig
from .app_server_protocol import generate_protocol_preflight
from .auth import auth_is_imported
from .context import (
    CLIENT_ESTIMATED_TOKENS_MAX,
    DIRECTOR_STATE_MAX_BYTES,
    DirectorContextMode,
    complete_context_size_report,
    evidence_registry_ids,
    prepare_director_state_v2,
)
from .director import ActiveDirector, base_instructions
from .protocol import (
    canonical_json,
    director_decision_schema,
    hypothesis_update_contract,
)
from .store import ResearchStore
from .validation import DecisionContext, validate_decision


SCREEN_MODEL = "gpt-5.6-luna"
SCREEN_EFFORT = "xhigh"
SCREEN_TURN_TIMEOUT_SECONDS = 300.0
SCREEN_SLOTS = (
    ("S2", DirectorContextMode.STATELESS_TURNS, "A4"),
    ("P1", DirectorContextMode.PERSISTENT_THREAD, "A1"),
    ("P2", DirectorContextMode.PERSISTENT_THREAD, "A4"),
)
SAFE_ITEM_TYPES = {"userMessage", "reasoning", "agentMessage"}


def build_context_screen_prompt(snapshot: dict[str, Any]) -> str:
    prepared = prepare_director_state_v2(snapshot)
    state = prepared.state
    applicable = state["allowed_action_space"]
    hypothesis_ids = evidence_registry_ids(
        prepared.evidence_registry,
        kinds=frozenset({"hypothesis"}),
    )
    payload = {
        "objective": (
            "Return one structured scientific recommendation grounded only in "
            "the supplied DirectorStateV2."
        ),
        "measurement_contract": {
            "measurement_only": True,
            "decision_will_not_be_executed": True,
            "search_batches": 0,
            "maximum_active_lanes": 1,
            "prohibited": [
                "tools",
                "code",
                "shell commands",
                "file operations",
                "new algorithms",
                "counterexample claims without exact certification",
            ],
            "scientific_rules": [
                "Use only the implemented action and parameter catalog.",
                "Respect remaining campaign budgets.",
                "Treat witness-cap-truncated counts as heuristic, not exact.",
                "M4 remains the only certification authority.",
                "Do not claim statistical superiority from this single pair.",
            ],
        },
        "applicable_action_description": {
            "actions": applicable["actions"],
            "why_applicable": applicable["action_applicability"],
            "active_executable_lane_ids": applicable[
                "active_executable_lane_ids"
            ],
            "historical_lane_ids_are_evidence_not_execution_targets": (
                applicable["historical_lane_ids"]
            ),
        },
        "hypothesis_update_contract": hypothesis_update_contract(
            hypothesis_ids
        ),
        "director_state_v2": state,
        "required_response": (
            "Return only the existing Director decision schema. The action is "
            "a recommendation for comparison and will remain measurement_only."
        ),
    }
    return canonical_json(payload, max_bytes=256 * 1024).decode("ascii")


def prepare_context_screen_phase_a(
    workspace: Path,
    *,
    source_workspace: Path,
) -> dict[str, Any]:
    root = workspace.resolve()
    source = source_workspace.resolve()
    if root == source:
        raise ValueError("screen workspace must differ from preserved source")
    states, source_evidence = load_preserved_screen_states(source)
    base = base_instructions()
    base_bytes = base.encode("utf-8")
    requests = []
    for label, mode, state_label in SCREEN_SLOTS:
        snapshot = states[state_label]
        prepared = prepare_director_state_v2(snapshot)
        schema = director_decision_schema(
            prepared.state["allowed_action_space"],
            existing_hypothesis_ids=evidence_registry_ids(
                prepared.evidence_registry,
                kinds=frozenset({"hypothesis"}),
            ),
        )
        schema_bytes = canonical_json(schema, max_bytes=1024 * 1024)
        prompt = build_context_screen_prompt(snapshot)
        size = complete_context_size_report(
            prepared,
            prompt=prompt,
            base_instructions=base,
            output_schema=schema,
            mode=mode,
        )
        state_bytes = canonical_json(
            prepared.state, max_bytes=DIRECTOR_STATE_MAX_BYTES
        )
        registry_bytes = canonical_json(
            prepared.evidence_registry, max_bytes=128 * 1024
        )
        envelope = {
            "thread_id": "<runtime-thread-id>",
            "snapshot_id": snapshot["snapshot_id"],
            "trigger_id": "<runtime-trigger-id>",
            "prompt": prompt,
            "output_schema": schema,
            "evidence_registry_artifact_ref": (
                "<runtime-evidence-registry-artifact>"
            ),
            "evidence_registry_sha256": (
                prepared.evidence_registry_sha256
            ),
            "advisory_target_registry_artifact_ref": (
                "<runtime-advisory-target-registry-artifact>"
            ),
            "advisory_target_registry_sha256": (
                prepared.advisory_target_registry_sha256
            ),
            "executable_target_registry_artifact_ref": (
                "<runtime-executable-target-registry-artifact>"
            ),
            "executable_target_registry_sha256": (
                prepared.executable_target_registry_sha256
            ),
            "applicable_action_space_artifact_ref": (
                "<runtime-applicable-action-space-artifact>"
            ),
            "applicable_action_space_sha256": (
                prepared.applicable_action_space_sha256
            ),
            "measurement_only": True,
            "executed": False,
        }
        envelope_bytes = canonical_json(envelope, max_bytes=1024 * 1024)
        request = {
            "slot": label,
            "mode": mode.value,
            "source_state": state_label,
            "snapshot_id": snapshot["snapshot_id"],
            "director_state_bytes": len(state_bytes),
            "director_state_sha256": hashlib.sha256(
                state_bytes
            ).hexdigest(),
            "ancestry_bytes": size["post_compaction"]["ancestry_bytes"],
            "historical_outcomes_bytes": size["post_compaction"][
                "historical_outcomes_bytes"
            ],
            "base_instructions_bytes": len(base_bytes),
            "prompt_bytes": len(prompt.encode("utf-8")),
            "prompt_sha256": hashlib.sha256(
                prompt.encode("ascii")
            ).hexdigest(),
            "output_schema_bytes": len(schema_bytes),
            "output_schema_sha256": hashlib.sha256(
                schema_bytes
            ).hexdigest(),
            "evidence_registry_sha256": (
                prepared.evidence_registry_sha256
            ),
            "evidence_registry": prepared.evidence_registry,
            "advisory_target_registry_sha256": (
                prepared.advisory_target_registry_sha256
            ),
            "advisory_target_registry": (
                prepared.advisory_target_registry
            ),
            "executable_target_registry_sha256": (
                prepared.executable_target_registry_sha256
            ),
            "executable_target_registry": (
                prepared.executable_target_registry
            ),
            "applicable_action_space": prepared.state[
                "allowed_action_space"
            ],
            "allowed_action_space_sha256": _value_sha256(
                prepared.state["allowed_action_space"]
            ),
            "target_metadata_sha256": _value_sha256(
                prepared.state["target"]
            ),
            "campaign_budget_sha256": _value_sha256(
                prepared.state["campaign_budget"]
            ),
            "artifact_references_sha256": _value_sha256(
                prepared.state["artifact_references"]
            ),
            "complete_client_request_bytes": len(envelope_bytes),
            "complete_client_request_sha256": hashlib.sha256(
                envelope_bytes
            ).hexdigest(),
            "client_owned_estimated_tokens": size[
                "client_owned_estimated_tokens"
            ],
            "within_state_limits": size["within_state_limits"],
            "within_client_token_limit": size[
                "within_client_token_limit"
            ],
            "measurement_only": True,
            "executed": False,
            "dispatch_scheduled": False,
            "search_components_present": False,
        }
        requests.append(request)
        root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            root / "request-templates" / f"{label}.json",
            {
                **envelope,
            },
        )
    by_slot = {value["slot"]: value for value in requests}
    equivalence_fields = (
        "director_state_sha256",
        "prompt_sha256",
        "output_schema_sha256",
        "evidence_registry_sha256",
        "advisory_target_registry_sha256",
        "executable_target_registry_sha256",
        "allowed_action_space_sha256",
        "target_metadata_sha256",
        "campaign_budget_sha256",
        "artifact_references_sha256",
        "complete_client_request_sha256",
    )
    s2_p2_equivalence = {
        field: by_slot["S2"][field] == by_slot["P2"][field]
        for field in equivalence_fields
    }
    runtime_contract = {
        "model": SCREEN_MODEL,
        "reasoning_effort": SCREEN_EFFORT,
        "expected_model": SCREEN_MODEL,
        "expected_reasoning_effort": SCREEN_EFFORT,
        "base_instructions_sha256": hashlib.sha256(
            base_bytes
        ).hexdigest(),
        "base_instructions_bytes": len(base_bytes),
        "developer_instructions": "",
        "personality": "none",
        "output_schema_contract": "generated_per_submitted_action_space",
        "sandbox": "read-only",
        "approval_policy": "never",
        "environments": [],
        "dynamic_tools": [],
        "selected_capability_roots": [],
        "runtime_workspace_roots": [],
        "compaction": False,
        "turn_timeout_seconds": SCREEN_TURN_TIMEOUT_SECONDS,
        "historical_failed_thread_reuse": False,
        "thread_plan": {
            "S2": "fresh_stateless_thread",
            "P1": "fresh_persistent_thread",
            "P2": "same_thread_as_P1",
        },
        "excluded_runtime_components": [
            "LaneManager",
            "search kernel",
            "candidate evaluator",
            "action dispatcher",
            "graph verifier",
            "graph-search worker",
            "batch executor",
        ],
    }
    equivalence_report = {
        "schema_version": "1.0",
        "slots": ["S2", "P1", "P2"],
        "primary_comparison": ["S2", "P2"],
        "equalities": s2_p2_equivalence,
        "all_equal": all(s2_p2_equivalence.values()),
        "only_intended_difference": (
            "P2 retains the P1 persistent-thread conversation history"
        ),
        "s2": {
            key: by_slot["S2"][key] for key in equivalence_fields
        },
        "p2": {
            key: by_slot["P2"][key] for key in equivalence_fields
        },
    }
    atomic_write_json(root / "context-screen-equivalence.json", equivalence_report)
    report = {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "phase": "deterministic_context_screen_preparation",
        "source": source_evidence,
        "runtime_contract": runtime_contract,
        "inference_slots": [value[0] for value in SCREEN_SLOTS],
        "inference_slot_count": len(SCREEN_SLOTS),
        "fourth_inference_slot_exists": False,
        "search_batch_slots": 0,
        "lane_creation_slots": 0,
        "action_dispatch_slots": 0,
        "candidate_evaluation_slots": 0,
        "compaction_operations_scheduled": 0,
        "requests": requests,
        "applicable_actions_by_source_state": {
            state_label: {
                "actions": by_slot[label]["applicable_action_space"][
                    "actions"
                ],
                "why_applicable": by_slot[label][
                    "applicable_action_space"
                ]["action_applicability"],
                "active_executable_lane_ids": by_slot[label][
                    "applicable_action_space"
                ]["active_executable_lane_ids"],
                "historical_lane_ids": by_slot[label][
                    "applicable_action_space"
                ]["historical_lane_ids"],
            }
            for label, state_label in (("P1", "A1"), ("S2", "A4"))
        },
        "s2_p2_equivalence": equivalence_report,
        "all_states_under_32_kib": all(
            int(value["director_state_bytes"]) <= DIRECTOR_STATE_MAX_BYTES
            for value in requests
        ),
        "all_inputs_under_12000_estimated_tokens": all(
            int(value["client_owned_estimated_tokens"])
            <= CLIENT_ESTIMATED_TOKENS_MAX
            for value in requests
        ),
        "all_decisions_measurement_only": all(
            value["measurement_only"]
            and not value["executed"]
            and not value["dispatch_scheduled"]
            and not value["search_components_present"]
            for value in requests
        ),
        "installed_app_server_started": False,
        "live_compliance_audit_deliberately_omitted": True,
    }
    report["ok"] = bool(
        report["inference_slots"] == ["S2", "P1", "P2"]
        and report["inference_slot_count"] == 3
        and not report["fourth_inference_slot_exists"]
        and report["search_batch_slots"] == 0
        and report["lane_creation_slots"] == 0
        and report["action_dispatch_slots"] == 0
        and report["candidate_evaluation_slots"] == 0
        and report["compaction_operations_scheduled"] == 0
        and report["all_states_under_32_kib"]
        and report["all_inputs_under_12000_estimated_tokens"]
        and report["all_decisions_measurement_only"]
        and equivalence_report["all_equal"]
        and all(
            value["within_state_limits"]
            and value["within_client_token_limit"]
            for value in requests
        )
    )
    root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(root / "context-screen-phase-a.json", report)
    return report


def run_authenticated_context_screen(
    workspace: Path,
    *,
    source_workspace: Path,
    codex: str = "codex",
    turn_timeout_seconds: float = SCREEN_TURN_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    if not 1.0 <= turn_timeout_seconds <= SCREEN_TURN_TIMEOUT_SECONDS:
        raise ValueError(
            "context-screen turn timeout must be between 1 and 300 seconds"
        )
    return asyncio.run(
        _run_authenticated_context_screen(
            workspace.resolve(),
            source_workspace=source_workspace.resolve(),
            codex=codex,
            turn_timeout_seconds=turn_timeout_seconds,
        )
    )


async def _run_authenticated_context_screen(
    root: Path,
    *,
    source_workspace: Path,
    codex: str | tuple[str, ...],
    turn_timeout_seconds: float,
) -> dict[str, Any]:
    phase_a_path = root / "context-screen-phase-a.json"
    if not phase_a_path.is_file():
        raise RuntimeError("context screen requires a passing Phase-A report")
    phase_a = json.loads(phase_a_path.read_text(encoding="utf-8"))
    if phase_a.get("ok") is not True:
        raise RuntimeError("context screen Phase-A report is not passing")
    states, source_evidence = load_preserved_screen_states(source_workspace)
    expected = _phase_a_plan_fingerprint(phase_a)
    current = _phase_a_plan_fingerprint(
        prepare_context_screen_phase_a(
            root / ".plan-recheck",
            source_workspace=source_workspace,
        )
    )
    if current != expected:
        raise RuntimeError("context screen plan changed after Phase A")
    arm_roots = {
        "persistent_thread": root / "arms" / "persistent",
        "stateless_turns": root / "arms" / "stateless",
    }
    if len({path.resolve() for path in arm_roots.values()}) != 2:
        raise RuntimeError("context screen arms must use independent roots")
    for path in arm_roots.values():
        if not auth_is_imported(path / ".sglab"):
            raise RuntimeError(
                f"authorized auth is not imported in arm: {path.name}"
            )
        if (path / "results.sqlite3").exists():
            raise RuntimeError("context screen arm database already exists")
    preflight = generate_protocol_preflight(codex)
    protocol_hash = hashlib.sha256(
        json.dumps(
            preflight["canonical_schema_hashes"],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    stateless, persistent = await _run_screen_arms(
        arm_roots=arm_roots,
        states=states,
        codex=codex,
        preflight=preflight,
        protocol_hash=protocol_hash,
        turn_timeout_seconds=turn_timeout_seconds,
    )
    turns = [*stateless["turns"], *persistent["turns"]]
    by_slot = {
        str(turn["slot"]): turn for turn in turns
    }
    s2 = by_slot.get("S2")
    p1 = by_slot.get("P1")
    p2 = by_slot.get("P2")
    usage_complete = bool(
        s2 is not None
        and p2 is not None
        and s2["usage"]["server_reported_total_tokens"] is not None
        and p2["usage"]["server_reported_total_tokens"] is not None
    )
    comparable = bool(
        s2 is not None
        and p2 is not None
        and s2["schema_validity"]
        and p2["schema_validity"]
        and s2["local_semantic_validity"]
        and p2["local_semantic_validity"]
        and s2["usage"]["input_tokens"] is not None
        and p2["usage"]["input_tokens"] is not None
        and s2["usage"]["server_reported_total_tokens"] is not None
        and p2["usage"]["server_reported_total_tokens"] is not None
    )
    input_reduction = None
    total_reduction = None
    if comparable:
        p2_input = int(p2["usage"]["input_tokens"])
        s2_input = int(s2["usage"]["input_tokens"])
        p2_total = int(p2["usage"]["server_reported_total_tokens"])
        s2_total = int(s2["usage"]["server_reported_total_tokens"])
        if p2_input > 0:
            input_reduction = 100.0 * (p2_input - s2_input) / p2_input
        if p2_total > 0:
            total_reduction = 100.0 * (p2_total - s2_total) / p2_total
    stateless_valid = bool(
        s2 is not None
        and s2["schema_validity"]
        and s2["local_semantic_validity"]
    )
    persistent_valid = bool(
        p2 is not None
        and p2["schema_validity"]
        and p2["local_semantic_validity"]
    )
    recommendation = "inconclusive"
    if (
        comparable
        and input_reduction is not None
        and input_reduction >= 20.0
        and stateless_valid
        and persistent_valid
        and stateless["completed"]
        and persistent["completed"]
    ):
        recommendation = "stateless_turns"
    report = {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "source": source_evidence,
        "codex_version": preflight["codex_version_output"],
        "runtime_contract": phase_a["runtime_contract"],
        "deterministic_preparation": {
            "inference_slots": phase_a["inference_slots"],
            "s2_p2_equivalence": phase_a["s2_p2_equivalence"],
            "context_budgets": phase_a["requests"],
            "plan_fingerprint": expected,
        },
        "arms": {
            "stateless_turns": stateless,
            "persistent_thread": persistent,
        },
        "usage_totals": {
            "persistent_thread": _sum_usage(persistent["turns"]),
            "stateless_turns": _sum_usage(stateless["turns"]),
        },
        "s2_vs_p2": _comparison_payload(
            s2,
            p2,
            input_reduction=input_reduction,
            total_reduction=total_reduction,
            comparable=comparable,
        ),
        "successful_completed_turns": sum(
            turn["lifecycle_status"] == "completed"
            and turn["final_answer_presence"]
            for turn in turns
        ),
        "inference_starts_reaching_model": sum(
            turn["request_id"] is not None for turn in turns
        ),
        "timed_out_or_aborted_turns": sum(
            turn["lifecycle_status"] in {"timed_out", "aborted"}
            for turn in turns
        ),
        "search_batches": sum(
            int(arm["search_batches"])
            for arm in (persistent, stateless)
        ),
        "search_lanes": sum(
            int(arm["search_lanes"])
            for arm in (persistent, stateless)
        ),
        "action_dispatches": sum(
            int(arm["action_dispatches"])
            for arm in (persistent, stateless)
        ),
        "candidate_evaluations": sum(
            int(arm["candidate_evaluations"])
            for arm in (persistent, stateless)
        ),
        "compaction_operations": sum(
            int(arm["compaction_operations"])
            for arm in (persistent, stateless)
        ),
        "tool_calls": sum(int(turn["tool_call_count"]) for turn in turns),
        "retries_reaching_inference": sum(
            int(turn["retry_count_reaching_inference"]) for turn in turns
        ),
        "status": {
            "canonical_evidence_registry": True,
            "incomplete_turn_persistence": True,
            "director_state_v2_bounded": all(
                turn["director_state_bytes"] <= DIRECTOR_STATE_MAX_BYTES
                for turn in turns
            ),
            "stateless_A4_completed": stateless_valid,
            "persistent_A1_completed": bool(
                p1 is not None
                and p1["schema_validity"]
                and p1["local_semantic_validity"]
            ),
            "persistent_A4_completed": persistent_valid,
            "exactly_three_or_fewer_inference_starts": (
                sum(turn["request_id"] is not None for turn in turns) <= 3
            ),
            "zero_retries_reaching_inference": (
                sum(
                    int(turn["retry_count_reaching_inference"])
                    for turn in turns
                )
                == 0
            ),
            "zero_search_batches": all(
                arm["search_batches"] == 0 and arm["search_lanes"] == 0
                for arm in (persistent, stateless)
            ),
            "zero_action_dispatches": all(
                arm["action_dispatches"] == 0
                for arm in (persistent, stateless)
            ),
            "zero_candidate_evaluations": all(
                arm["candidate_evaluations"] == 0
                for arm in (persistent, stateless)
            ),
            "zero_compaction_operations": all(
                arm["compaction_operations"] == 0
                for arm in (persistent, stateless)
            ),
            "zero_tool_calls": (
                sum(int(turn["tool_call_count"]) for turn in turns) == 0
            ),
            "usage_accounting_complete": usage_complete,
            "semantic_validity_stateless_A4": stateless_valid,
            "semantic_validity_persistent_A4": persistent_valid,
            "stateless_token_reduction_percent": input_reduction,
            "completion_reliability_comparison": (
                "both_completed"
                if stateless_valid and persistent_valid
                else "inconclusive"
            ),
            "context_mode_comparison": (
                "complete_single_pair" if comparable else "inconclusive"
            ),
            "recommended_default_context_mode": recommendation,
        },
    }
    report["ok"] = bool(
        stateless["completed"]
        and persistent["completed"]
        and report["inference_starts_reaching_model"] == 3
        and report["search_batches"] == 0
        and report["tool_calls"] == 0
        and report["retries_reaching_inference"] == 0
    )
    atomic_write_json(root / "context-screen-report.json", report)
    return report


async def _run_screen_arms(
    *,
    arm_roots: dict[str, Path],
    states: dict[str, dict[str, Any]],
    codex: str | tuple[str, ...],
    preflight: dict[str, Any],
    protocol_hash: str,
    turn_timeout_seconds: float,
    usage_wait_seconds: float = 3.0,
    timeout_drain_seconds: float = 2.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run S2 first; any failure prevents every later inference slot."""

    stateless = await _run_screen_arm(
        arm_roots["stateless_turns"],
        mode=DirectorContextMode.STATELESS_TURNS,
        slots=(("S2", "A4"),),
        states=states,
        codex=codex,
        preflight=preflight,
        protocol_hash=protocol_hash,
        turn_timeout_seconds=turn_timeout_seconds,
        usage_wait_seconds=usage_wait_seconds,
        timeout_drain_seconds=timeout_drain_seconds,
    )
    if not stateless["completed"]:
        return stateless, _not_started_arm(
            DirectorContextMode.PERSISTENT_THREAD
        )
    persistent = await _run_screen_arm(
        arm_roots["persistent_thread"],
        mode=DirectorContextMode.PERSISTENT_THREAD,
        slots=(("P1", "A1"), ("P2", "A4")),
        states=states,
        codex=codex,
        preflight=preflight,
        protocol_hash=protocol_hash,
        turn_timeout_seconds=turn_timeout_seconds,
        usage_wait_seconds=usage_wait_seconds,
        timeout_drain_seconds=timeout_drain_seconds,
    )
    return stateless, persistent


async def _run_screen_arm(
    root: Path,
    *,
    mode: DirectorContextMode,
    slots: tuple[tuple[str, str], ...],
    states: dict[str, dict[str, Any]],
    codex: str,
    preflight: dict[str, Any],
    protocol_hash: str,
    turn_timeout_seconds: float,
    usage_wait_seconds: float = 3.0,
    timeout_drain_seconds: float = 2.0,
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    campaign_id = f"context-screen-{mode.value}"
    campaign_dir = root / "context-screen" / campaign_id
    campaign_dir.mkdir(parents=True)
    store = ResearchStore(root / "results.sqlite3")
    store.create_campaign(
        campaign_id=campaign_id,
        target="erdos_gyarfas",
        target_definition_sha256=str(
            states["A1"]["target"]["immutable_definition_hash"]
        ),
        stop_mode="until_success",
        deadline_at=None,
    )
    client = AppServerClient(
        AppServerConfig(
            application_data=root / ".sglab",
            launcher=(
                (codex,) if isinstance(codex, str) else tuple(codex)
            ),
            model=SCREEN_MODEL,
            effort=SCREEN_EFFORT,
            turn_timeout_seconds=turn_timeout_seconds,
            usage_wait_seconds=usage_wait_seconds,
            timeout_drain_seconds=timeout_drain_seconds,
        )
    )
    director = ActiveDirector(
        client=client,
        store=store,
        campaign_id=campaign_id,
        campaign_dir=campaign_dir,
        codex_version=str(preflight["codex_version_output"]),
        executable_sha256=str(preflight["codex_executable_sha256"]),
        protocol_schema_sha256=protocol_hash,
        context_mode=mode,
    )
    turns: list[dict[str, Any]] = []
    failure: dict[str, Any] | None = None
    try:
        session = await director.start()
        model_contract = _model_contract(session)
        atomic_write_json(
            campaign_dir / "director" / "model-contract.json",
            model_contract,
        )
        if not model_contract["model_contract_matched"]:
            raise RuntimeError(
                "effective app-server model contract does not match "
                f"{SCREEN_MODEL}:{SCREEN_EFFORT}"
            )
        for label, state_label in slots:
            snapshot = states[state_label]
            trigger_id = _record_screen_snapshot(
                store,
                campaign_id=campaign_id,
                campaign_dir=campaign_dir,
                label=label,
                snapshot=snapshot,
            )
            prompt = build_context_screen_prompt(snapshot)
            evidence = await director.request_decision_once(
                snapshot=snapshot,
                trigger_id=trigger_id,
                context=decision_context_for_snapshot(snapshot),
                prompt=prompt,
            )
            turn = _measurement_turn(
                store,
                campaign_dir=campaign_dir,
                label=label,
                mode=mode,
                snapshot=snapshot,
                evidence=evidence,
            )
            if turn["tool_call_count"] or turn[
                "retry_count_reaching_inference"
            ]:
                raise RuntimeError(
                    f"{label} used a tool or reached an inference retry"
                )
            turns.append(turn)
            turn["model_contract"] = model_contract
            store.mark_trigger_status(trigger_id, "measurement_only")
            if not turn["schema_validity"]:
                raise RuntimeError(f"{label} response failed schema validation")
            if not turn["local_semantic_validity"]:
                raise RuntimeError(
                    f"{label} response failed local semantic validation"
                )
            if not turn["final_answer_presence"]:
                raise RuntimeError(f"{label} response omitted final answer")
        store.finish_campaign(
            campaign_id,
            terminal_kind="stopped_by_operator",
            detail="Context-mode screen completed without decision dispatch",
        )
    except BaseException as error:
        failure = {
            "kind": type(error).__name__,
            "detail": str(error)[:4000],
        }
        store.finish_campaign(
            campaign_id,
            terminal_kind="stopped_by_operator",
            detail=f"context screen stopped after failure: {error}",
        )
    finally:
        try:
            await director.close()
        except BaseException as error:
            if failure is None:
                failure = {
                    "kind": type(error).__name__,
                    "detail": f"shutdown failed: {error}"[:4000],
                }
    represented = {str(turn["turn_record_id"]) for turn in turns}
    for row in store.connection.execute(
        "SELECT * FROM app_server_turns ORDER BY started_at, rowid"
    ):
        if str(row["turn_record_id"]) in represented:
            continue
        turns.append(
            _incomplete_measurement_turn(
                store,
                campaign_dir=campaign_dir,
                row=row,
                states=states,
                mode=mode,
            )
        )
    for turn in turns:
        turn["graceful_shutdown_result"] = client.last_shutdown_mode
        measurement_path = (
            campaign_dir
            / "director"
            / "measurements"
            / f"{turn['slot']}.json"
        )
        if measurement_path.is_file():
            payload = json.loads(
                measurement_path.read_text(encoding="utf-8")
            )
            payload["graceful_shutdown_result"] = (
                client.last_shutdown_mode
            )
            atomic_write_json(measurement_path, payload)
    counts = {
        "lanes": int(
            store.connection.execute(
                "SELECT count(*) FROM research_lanes"
            ).fetchone()[0]
        ),
        "metric_windows": int(
            store.connection.execute(
                "SELECT count(*) FROM lane_metric_windows"
            ).fetchone()[0]
        ),
        "decision_batches": int(
            store.connection.execute(
                "SELECT count(*) FROM director_action_batches"
            ).fetchone()[0]
        ),
        "actions": int(
            store.connection.execute(
                "SELECT count(*) FROM director_actions"
            ).fetchone()[0]
        ),
        "candidates": int(
            store.connection.execute(
                "SELECT count(*) FROM campaign_candidates"
            ).fetchone()[0]
        ),
    }
    session_rows = [
        dict(value)
        for value in store.connection.execute(
            """
            SELECT thread_id, model_requested, effort_requested, state
            FROM app_server_sessions ORDER BY started_at, rowid
            """
        )
    ]
    integrity = str(store.connection.execute("PRAGMA integrity_check").fetchone()[0])
    store.close()
    thread_ids = [str(turn["thread_id"]) for turn in turns]
    completed = bool(
        failure is None
        and len(turns) == len(slots)
        and integrity == "ok"
        and counts == {
            "lanes": 0,
            "metric_windows": 0,
            "decision_batches": 0,
            "actions": 0,
            "candidates": 0,
        }
        and all(row["model_requested"] == SCREEN_MODEL for row in session_rows)
        and all(row["effort_requested"] == SCREEN_EFFORT for row in session_rows)
        and all(turn["item_id"] is not None for turn in turns)
        and client.unsupported_server_requests == 0
        and (
            len(set(thread_ids)) == 1
            if mode is DirectorContextMode.PERSISTENT_THREAD
            else len(set(thread_ids)) == len(slots)
        )
        and client.last_shutdown_mode == "graceful"
    )
    return {
        "mode": mode.value,
        "turns": turns,
        "thread_ids": thread_ids,
        "sessions": session_rows,
        "model_contract": (
            model_contract if "model_contract" in locals() else None
        ),
        "search_batches": counts["metric_windows"],
        "search_lanes": counts["lanes"],
        "persisted_decision_batches": counts["decision_batches"],
        "action_dispatches": counts["actions"],
        "candidate_evaluations": counts["candidates"],
        "compaction_operations": sum(
            int(turn["compaction_operation_count"]) for turn in turns
        ),
        "sqlite_integrity_check": integrity,
        "graceful_shutdown": client.last_shutdown_mode,
        "unsupported_server_requests": client.unsupported_server_requests,
        "failure": failure,
        "latency_total_seconds": sum(
            float(turn["latency_seconds"]) for turn in turns
        ),
        "completed": completed,
    }


def _record_screen_snapshot(
    store: ResearchStore,
    *,
    campaign_id: str,
    campaign_dir: Path,
    label: str,
    snapshot: dict[str, Any],
) -> str:
    relative = Path("source-states") / f"{label}.json"
    payload = canonical_json(snapshot, max_bytes=4 * 1024 * 1024)
    path = campaign_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload + b"\n")
    store.record_snapshot(
        snapshot_id=str(snapshot["snapshot_id"]),
        campaign_id=campaign_id,
        campaign_state_version=0,
        high_water={},
        artifact_ref=str(relative),
        artifact_sha256=hashlib.sha256(payload).hexdigest(),
        payload_bytes=len(payload),
    )
    trigger_id = f"context-screen-trigger-{label}"
    store.record_trigger(
        trigger_id=trigger_id,
        campaign_id=campaign_id,
        campaign_state_version=0,
        reasons=["context_mode_measurement"],
        first_event_at=utc_now(),
        snapshot_id=str(snapshot["snapshot_id"]),
    )
    return trigger_id


def _measurement_turn(
    store: ResearchStore,
    *,
    campaign_dir: Path,
    label: str,
    mode: DirectorContextMode,
    snapshot: dict[str, Any],
    evidence: Any,
) -> dict[str, Any]:
    turn_record_id = str(evidence.turn_record_ids[-1])
    row = store.connection.execute(
        "SELECT * FROM app_server_turns WHERE turn_record_id=?",
        (turn_record_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("context screen turn was not persisted")
    request_path = campaign_dir / str(row["request_artifact_ref"])
    response_path = campaign_dir / str(row["response_artifact_ref"])
    wire_path = campaign_dir / str(row["wire_log_artifact_ref"])
    raw_decision = json.loads(response_path.read_text(encoding="utf-8"))
    semantic = semantic_decision_rubric(
        raw_decision,
        snapshot=snapshot,
        context=decision_context_for_snapshot(snapshot),
    )
    wire = _wire_metrics(wire_path)
    prepared = prepare_director_state_v2(snapshot)
    state_bytes = canonical_json(
        prepared.state, max_bytes=DIRECTOR_STATE_MAX_BYTES
    )
    prompt = build_context_screen_prompt(snapshot)
    prompt_bytes = prompt.encode("ascii")
    output_schema = director_decision_schema(
        prepared.state["allowed_action_space"],
        existing_hypothesis_ids=evidence_registry_ids(
            prepared.evidence_registry,
            kinds=frozenset({"hypothesis"}),
        ),
    )
    schema_bytes = canonical_json(output_schema, max_bytes=1024 * 1024)
    action = (
        evidence.decision["actions"][0]
        if evidence.decision.get("actions")
        else {}
    )
    algorithm, parameters = _selected_algorithm_and_parameters(action)
    usage = {
        "input_tokens": _nullable_int(row["input_tokens"]),
        "cached_input_tokens": _nullable_int(
            row["cached_input_tokens"]
        ),
        "cache_write_input_tokens": _nullable_int(
            row["cache_write_input_tokens"]
        ),
        "output_tokens": _nullable_int(row["output_tokens"]),
        "reasoning_output_tokens": _nullable_int(
            row["reasoning_output_tokens"]
        ),
        "server_reported_total_tokens": _nullable_int(
            row["total_tokens"]
        ),
    }
    item_ids = json.loads(str(row["item_ids_json"] or "[]"))
    reasoning_ids = json.loads(
        str(row["reasoning_item_ids_json"] or "[]")
    )
    result = {
        "slot": label,
        "mode": mode.value,
        "measurement_only": True,
        "executed": False,
        "thread_id": str(row["thread_id"]),
        "turn_id": str(row["turn_id"]),
        "request_id": row["request_id"],
        "item_ids": item_ids,
        "reasoning_item_ids": reasoning_ids,
        "latest_event_sequence": int(row["latest_event_sequence"]),
        "lifecycle_status": str(row["lifecycle_status"]),
        "item_id": row["final_agent_item_id"],
        "turn_record_id": turn_record_id,
        "snapshot_id": snapshot["snapshot_id"],
        "source_snapshot_id": prepared.state["source_snapshot_id"],
        "request_artifact": str(row["request_artifact_ref"]),
        "request_sha256": row["request_sha256"],
        "response_artifact": str(row["response_artifact_ref"]),
        "response_sha256": row["response_sha256"],
        "wire_log_artifact": str(row["wire_log_artifact_ref"]),
        "wire_log_sha256": row["wire_log_sha256"],
        "evidence_registry_artifact": row[
            "evidence_registry_artifact_ref"
        ],
        "director_state_bytes": prepared.size_report["post_compaction"][
            "director_state_bytes"
        ],
        "director_state_sha256": hashlib.sha256(state_bytes).hexdigest(),
        "prompt_bytes": len(prompt_bytes),
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "output_schema_bytes": len(schema_bytes),
        "output_schema_sha256": hashlib.sha256(
            schema_bytes
        ).hexdigest(),
        "evidence_registry_sha256": (
            prepared.evidence_registry_sha256
        ),
        "advisory_target_registry_sha256": (
            prepared.advisory_target_registry_sha256
        ),
        "executable_target_registry_sha256": (
            prepared.executable_target_registry_sha256
        ),
        "applicable_action_space": prepared.state[
            "allowed_action_space"
        ],
        "applicable_action_space_sha256": (
            prepared.applicable_action_space_sha256
        ),
        "active_executable_targets": sorted(
            evidence_registry_ids(prepared.executable_target_registry)
        ),
        "historical_evidence_targets": prepared.state[
            "allowed_action_space"
        ]["historical_lane_ids"],
        "client_owned_estimated_tokens": complete_context_size_report(
            prepared,
            prompt=prompt,
            base_instructions=base_instructions(),
            output_schema=output_schema,
            mode=mode,
        )["client_owned_estimated_tokens"],
        "full_client_request_bytes": request_path.stat().st_size,
        "turn_start_json_rpc_bytes": wire["turn_start_json_rpc_bytes"],
        "latency_seconds": float(row["wall_seconds"]),
        "first_item_latency_seconds": (
            evidence.first_item_latency_seconds
        ),
        "final_answer_latency_seconds": (
            evidence.final_answer_latency_seconds
        ),
        "start_timestamp": row["started_at"],
        "turn_started_timestamp": row["turn_started_at"],
        "completed_timestamp": row["completed_at"],
        "final_answer_presence": row["final_agent_item_id"] is not None,
        "usage_presence": row["raw_usage_json"] is not None,
        "schema_validity": _decision_schema_shape_valid(raw_decision),
        "local_semantic_validity": evidence.validation.accepted,
        "raw_decision": raw_decision,
        "normalized_decision": (
            evidence.validation.normalized
            if evidence.validation.normalized is not None
            else evidence.decision
        ),
        "validation_issues": [
            {"path": issue.path, "message": issue.message}
            for issue in evidence.validation.issues
        ],
        "semantic_rubric": semantic,
        "selected_action": action.get("type"),
        "selected_algorithm": algorithm,
        "selected_parameters": parameters,
        "hypothesis": [
            value.get("statement")
            for value in evidence.decision.get("hypothesis_updates", [])
        ],
        "expected_signal": action.get("expected_effect"),
        "evidence_references": _decision_evidence_references(
            evidence.decision
        ),
        "tool_call_count": wire["tool_call_count"],
        "retry_count_reaching_inference": wire[
            "retry_count_reaching_inference"
        ],
        "compaction_operation_count": wire[
            "compaction_operation_count"
        ],
        "usage": usage,
    }
    relative = Path("director") / "measurements" / f"{label}.json"
    path = campaign_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        path,
        {
            **result,
            "validated_decision": evidence.decision,
        },
    )
    return result


def _incomplete_measurement_turn(
    store: ResearchStore,
    *,
    campaign_dir: Path,
    row: Any,
    states: dict[str, dict[str, Any]],
    mode: DirectorContextMode,
) -> dict[str, Any]:
    trigger_id = str(row["trigger_id"])
    label = trigger_id.rsplit("-", 1)[-1]
    state_label = "A4" if label in {"S2", "P2"} else "A1"
    snapshot = states[state_label]
    prepared = prepare_director_state_v2(snapshot)
    prompt = build_context_screen_prompt(snapshot)
    prompt_bytes = prompt.encode("ascii")
    state_bytes = canonical_json(
        prepared.state, max_bytes=DIRECTOR_STATE_MAX_BYTES
    )
    output_schema = director_decision_schema(
        prepared.state["allowed_action_space"],
        existing_hypothesis_ids=evidence_registry_ids(
            prepared.evidence_registry,
            kinds=frozenset({"hypothesis"}),
        ),
    )
    schema_bytes = canonical_json(output_schema, max_bytes=1024 * 1024)
    request_path = campaign_dir / str(row["request_artifact_ref"])
    wire_path = campaign_dir / str(row["wire_log_artifact_ref"])
    wire = (
        _wire_metrics(wire_path)
        if wire_path.is_file()
        else {
            "turn_start_json_rpc_bytes": 0,
            "tool_call_count": 0,
            "retry_count_reaching_inference": 0,
            "compaction_operation_count": 0,
        }
    )
    usage = {
        "input_tokens": _nullable_int(row["input_tokens"]),
        "cached_input_tokens": _nullable_int(
            row["cached_input_tokens"]
        ),
        "cache_write_input_tokens": _nullable_int(
            row["cache_write_input_tokens"]
        ),
        "output_tokens": _nullable_int(row["output_tokens"]),
        "reasoning_output_tokens": _nullable_int(
            row["reasoning_output_tokens"]
        ),
        "server_reported_total_tokens": _nullable_int(
            row["total_tokens"]
        ),
    }
    result = {
        "slot": label,
        "mode": mode.value,
        "measurement_only": True,
        "executed": False,
        "request_id": row["request_id"],
        "thread_id": str(row["thread_id"]),
        "turn_id": row["turn_id"],
        "item_id": row["final_agent_item_id"],
        "item_ids": json.loads(str(row["item_ids_json"] or "[]")),
        "reasoning_item_ids": json.loads(
            str(row["reasoning_item_ids_json"] or "[]")
        ),
        "latest_event_sequence": int(row["latest_event_sequence"]),
        "lifecycle_status": str(row["lifecycle_status"]),
        "turn_record_id": str(row["turn_record_id"]),
        "snapshot_id": snapshot["snapshot_id"],
        "source_snapshot_id": prepared.state["source_snapshot_id"],
        "request_artifact": str(row["request_artifact_ref"]),
        "request_sha256": row["request_sha256"],
        "response_artifact": row["response_artifact_ref"],
        "response_sha256": row["response_sha256"],
        "wire_log_artifact": str(row["wire_log_artifact_ref"]),
        "wire_log_sha256": row["wire_log_sha256"],
        "evidence_registry_artifact": row[
            "evidence_registry_artifact_ref"
        ],
        "director_state_bytes": len(state_bytes),
        "director_state_sha256": hashlib.sha256(state_bytes).hexdigest(),
        "prompt_bytes": len(prompt_bytes),
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "output_schema_bytes": len(schema_bytes),
        "output_schema_sha256": hashlib.sha256(
            schema_bytes
        ).hexdigest(),
        "evidence_registry_sha256": (
            prepared.evidence_registry_sha256
        ),
        "advisory_target_registry_sha256": (
            prepared.advisory_target_registry_sha256
        ),
        "executable_target_registry_sha256": (
            prepared.executable_target_registry_sha256
        ),
        "applicable_action_space": prepared.state[
            "allowed_action_space"
        ],
        "applicable_action_space_sha256": (
            prepared.applicable_action_space_sha256
        ),
        "active_executable_targets": sorted(
            evidence_registry_ids(prepared.executable_target_registry)
        ),
        "historical_evidence_targets": prepared.state[
            "allowed_action_space"
        ]["historical_lane_ids"],
        "client_owned_estimated_tokens": complete_context_size_report(
            prepared,
            prompt=prompt,
            base_instructions=base_instructions(),
            output_schema=output_schema,
            mode=mode,
        )["client_owned_estimated_tokens"],
        "full_client_request_bytes": (
            request_path.stat().st_size if request_path.is_file() else None
        ),
        "turn_start_json_rpc_bytes": wire[
            "turn_start_json_rpc_bytes"
        ],
        "latency_seconds": (
            float(row["wall_seconds"])
            if row["wall_seconds"] is not None
            else None
        ),
        "first_item_latency_seconds": None,
        "final_answer_latency_seconds": None,
        "start_timestamp": row["started_at"],
        "turn_started_timestamp": row["turn_started_at"],
        "completed_timestamp": row["completed_at"],
        "final_answer_presence": False,
        "usage_presence": row["raw_usage_json"] is not None,
        "schema_validity": None,
        "local_semantic_validity": None,
        "raw_decision": None,
        "normalized_decision": None,
        "validation_issues": None,
        "semantic_rubric": None,
        "selected_action": None,
        "selected_algorithm": None,
        "selected_parameters": None,
        "hypothesis": None,
        "expected_signal": None,
        "evidence_references": [],
        "tool_call_count": wire["tool_call_count"],
        "retry_count_reaching_inference": wire[
            "retry_count_reaching_inference"
        ],
        "compaction_operation_count": wire[
            "compaction_operation_count"
        ],
        "usage": usage,
        "terminal_reason": row["terminal_reason"],
        "error_kind": row["error_kind"],
        "error_detail": row["error_detail"],
    }
    relative = Path("director") / "measurements" / f"{label}.json"
    atomic_write_json(
        campaign_dir / relative,
        {
            **result,
            "validated_decision": None,
        },
    )
    return result


def semantic_decision_rubric(
    decision: dict[str, Any],
    *,
    snapshot: dict[str, Any],
    context: DecisionContext,
) -> dict[str, Any]:
    validation = validate_decision(decision, context)
    normalized = validation.normalized or decision
    prepared = prepare_director_state_v2(snapshot).state
    texts = _decision_text(normalized)
    search_actions = {
        "start_lane",
        "patch_lane",
        "fork_lane",
        "restart_lane",
        "reallocate_resources",
    }
    remaining = (
        prepared.get("campaign_budget", {})
        .get("evaluations", {})
        .get("remaining")
    )
    budget_respected = True
    if isinstance(remaining, int):
        requested = 0
        for action in normalized.get("actions", []):
            if action.get("type") not in search_actions:
                continue
            parameters = _selected_algorithm_and_parameters(action)[1]
            requested += int(parameters.get("batch_candidates", 0))
        budget_respected = requested <= max(0, remaining)
    lower = texts.lower()
    counterexample_claim = bool(
        re.search(
            r"\b(found|is|certified|proves?|demonstrates?)\s+(?:an?\s+)?"
            r"counterexample\b",
            lower,
        )
    ) and not bool(
        re.search(r"\b(no|not|isn't|is not|does not)\b.{0,24}\bcounterexample\b", lower)
    )
    prohibited_request = bool(
        re.search(
            r"\b(run|execute|invoke|use|read|write|open)\b.{0,32}"
            r"\b(tool|shell|command|code|file)\b",
            lower,
        )
        or re.search(
            r"\b(generate|create|write)\b.{0,24}\b(code|script)\b",
            lower,
        )
    )
    statistical_superiority_claim = bool(
        re.search(
            r"\b(statistically\s+superior|statistical\s+superiority|"
            r"significantly\s+better)\b",
            lower,
        )
    )
    measurement_execution_request = bool(
        re.search(
            r"\b(execute|dispatch|run)\b.{0,32}"
            r"\b(this|the|proposed|recommended)\b.{0,24}"
            r"\b(action|decision|batch|lane)\b",
            lower,
        )
    )
    truncated = any(
        bool(value.get("score_counts_truncated_by_witness_cap"))
        for value in [
            prepared.get("latest_batch_outcome"),
            *prepared.get("previous_outcomes", []),
        ]
        if isinstance(value, dict)
    )
    false_exact_claim = truncated and bool(
        re.search(
            r"\b(exact|complete)\s+(?:witness\s+)?counts?\b", lower
        )
    )
    parameter_annotations_complete = all(
        not action.get("ignored_parameters")
        and not action.get("rejected_parameters")
        for action in normalized.get("actions", [])
    )
    checks = {
        "facts_referenced_by_structured_ids_are_present": validation.accepted,
        "inside_allowed_action_space": validation.accepted,
        "implemented_parameters_only": (
            validation.accepted and parameter_annotations_complete
        ),
        "budgets_respected": budget_respected,
        "truncated_counts_not_claimed_exact": not false_exact_claim,
        "no_counterexample_claim": not counterexample_claim,
        "no_statistical_superiority_claim": (
            not statistical_superiority_claim
        ),
        "no_code_tool_file_or_shell_request": not prohibited_request,
        "no_measurement_decision_execution_request": (
            not measurement_execution_request
        ),
    }
    return {
        "scope": (
            "Deterministic structured-ID, catalog, parameter, budget and "
            "prohibited-request checks; no free-text fact entailment inference."
        ),
        "checks": checks,
        "validation_issues": [
            {"path": issue.path, "message": issue.message}
            for issue in validation.issues
        ],
        "ok": all(checks.values()),
    }


def decision_context_for_snapshot(
    snapshot: dict[str, Any],
) -> DecisionContext:
    prepared = prepare_director_state_v2(snapshot)
    registry = prepared.evidence_registry
    active = [
        value
        for value in snapshot.get("lanes", [])
        if value.get("state") in {"starting", "running", "paused", "stopping"}
    ]
    return DecisionContext(
        snapshot_id=str(prepared.state["source_snapshot_id"]),
        evidence_ids=evidence_registry_ids(registry),
        lane_versions={
            str(value["lane_id"]): int(value["lane_version"])
            for value in active
        },
        lane_algorithms={
            str(value["lane_id"]): str(value["algorithm"])
            for value in active
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


def load_preserved_screen_states(
    source_workspace: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    root = source_workspace.resolve()
    report_path = root / "ai-experiment-report.json"
    pointer_path = root / "active-research-campaign.json"
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    campaign_dir = Path(str(pointer["campaign_dir"])).resolve()
    campaign_dir.relative_to(root)
    turn_ids = list(report["turn_record_ids"])
    if len(turn_ids) != 4:
        raise RuntimeError("preserved source must contain exactly four turns")
    states = {}
    for label, index in (("A1", 0), ("A4", 3)):
        path = (
            campaign_dir
            / "director"
            / "requests"
            / f"{turn_ids[index]}.json"
        )
        request = json.loads(path.read_text(encoding="utf-8"))
        prompt = json.loads(str(request["prompt"]))
        snapshot = prompt.get("committed_research_snapshot")
        if not isinstance(snapshot, dict):
            raise RuntimeError(f"preserved {label} omitted source snapshot")
        states[label] = snapshot
    return states, {
        "campaign_id": report["campaign_id"],
        "report_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "source_model_inferences": report["model_inferences"],
        "source_search_batches": report["search_batches"],
        "source_artifacts_modified": False,
    }


def _wire_metrics(path: Path) -> dict[str, int]:
    turn_start_bytes = 0
    tool_item_ids: set[str] = set()
    retries = 0
    compactions = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            outbound = line.startswith("> ")
            inbound = line.startswith("< ")
            if not (outbound or inbound):
                continue
            payload = json.loads(line[2:])
            method = payload.get("method")
            if outbound and method == "turn/start":
                turn_start_bytes += len(line[2:].rstrip("\n").encode("utf-8"))
            if outbound and method == "thread/compact/start":
                compactions += 1
            if inbound and method == "error":
                params = payload.get("params")
                if isinstance(params, dict) and params.get("willRetry") is True:
                    retries += 1
            if inbound and method in {"item/started", "item/completed"}:
                item = payload.get("params", {}).get("item")
                item_type = item.get("type") if isinstance(item, dict) else None
                if isinstance(item_type, str) and item_type not in SAFE_ITEM_TYPES:
                    item_id = item.get("id")
                    tool_item_ids.add(
                        str(item_id)
                        if isinstance(item_id, str)
                        else f"unidentified:{item_type}"
                    )
    return {
        "turn_start_json_rpc_bytes": turn_start_bytes,
        "tool_call_count": len(tool_item_ids),
        "retry_count_reaching_inference": retries,
        "compaction_operation_count": compactions,
    }


def _decision_schema_shape_valid(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {
        "schema_version",
        "snapshot_id",
        "campaign_assessment",
        "hypothesis_updates",
        "actions",
        "next_review",
    }


def _selected_algorithm_and_parameters(
    action: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    if action.get("type") == "start_lane":
        spec = action.get("spec")
        if isinstance(spec, dict):
            return (
                str(spec.get("algorithm")) if spec.get("algorithm") else None,
                dict(
                    action.get("effective_parameters")
                    or spec.get("parameters")
                    or {}
                ),
            )
    return (
        None,
        dict(
            action.get("effective_parameters")
            or action.get("patch")
            or {}
        ),
    )


def _decision_text(value: Any) -> str:
    strings: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            strings.append(item)
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return "\n".join(strings)


def _sum_usage(turns: list[dict[str, Any]]) -> dict[str, int]:
    keys = (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "server_reported_total_tokens",
    )
    return {
        key: sum(int(turn["usage"][key] or 0) for turn in turns)
        for key in keys
    }


def _comparison_payload(
    stateless: dict[str, Any] | None,
    persistent: dict[str, Any] | None,
    *,
    input_reduction: float | None,
    total_reduction: float | None,
    comparable: bool,
) -> dict[str, Any]:
    if stateless is None or persistent is None:
        return {
            "scientific_input_equal": None,
            "evidence_registry_equal": None,
            "input_token_difference": None,
            "stateless_input_token_reduction_percent": None,
            "stateless_total_token_reduction_percent": None,
            "comparison": "inconclusive",
        }
    input_difference = None
    if (
        stateless["usage"]["input_tokens"] is not None
        and persistent["usage"]["input_tokens"] is not None
    ):
        input_difference = (
            int(persistent["usage"]["input_tokens"])
            - int(stateless["usage"]["input_tokens"])
        )
    return {
        "scientific_input_equal": (
            stateless["director_state_sha256"]
            == persistent["director_state_sha256"]
            and stateless["prompt_sha256"]
            == persistent["prompt_sha256"]
            and stateless["output_schema_sha256"]
            == persistent["output_schema_sha256"]
        ),
        "evidence_registry_equal": (
            stateless["evidence_registry_sha256"]
            == persistent["evidence_registry_sha256"]
        ),
        "input_token_difference": input_difference,
        "stateless_input_token_reduction_percent": input_reduction,
        "stateless_total_token_reduction_percent": total_reduction,
        "cache": {
            "stateless_cached_input_tokens": stateless["usage"][
                "cached_input_tokens"
            ],
            "persistent_cached_input_tokens": persistent["usage"][
                "cached_input_tokens"
            ],
            "stateless_cache_write_input_tokens": stateless["usage"][
                "cache_write_input_tokens"
            ],
            "persistent_cache_write_input_tokens": persistent["usage"][
                "cache_write_input_tokens"
            ],
        },
        "latency_seconds_difference": (
            float(persistent["latency_seconds"])
            - float(stateless["latency_seconds"])
            if persistent["latency_seconds"] is not None
            and stateless["latency_seconds"] is not None
            else None
        ),
        "decision": _compare_decisions(persistent, stateless),
        "comparison": (
            "complete_single_pair" if comparable else "inconclusive"
        ),
        "statistical_superiority_claimed": False,
    }


def _not_started_arm(mode: DirectorContextMode) -> dict[str, Any]:
    return {
        "mode": mode.value,
        "turns": [],
        "thread_ids": [],
        "sessions": [],
        "search_batches": 0,
        "search_lanes": 0,
        "persisted_decision_batches": 0,
        "action_dispatches": 0,
        "candidate_evaluations": 0,
        "compaction_operations": 0,
        "sqlite_integrity_check": None,
        "graceful_shutdown": None,
        "unsupported_server_requests": 0,
        "latency_total_seconds": 0.0,
        "failure": {"kind": "not_started", "detail": "earlier slot failed"},
        "completed": False,
    }


def _nullable_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _model_contract(session: Any) -> dict[str, Any]:
    effective_model = session.server_reported_model
    effective_effort = session.server_reported_effort
    matched = bool(
        effective_model == SCREEN_MODEL
        and effective_effort == SCREEN_EFFORT
    )
    return {
        "schema_version": "1.0",
        "checked_at": utc_now(),
        "checked_before_inference": True,
        "expected_model": SCREEN_MODEL,
        "expected_reasoning_effort": SCREEN_EFFORT,
        "effective_model": effective_model,
        "effective_reasoning_effort": effective_effort,
        "model_contract_matched": matched,
    }


def _value_sha256(value: Any) -> str:
    return hashlib.sha256(
        canonical_json(value, max_bytes=1024 * 1024)
    ).hexdigest()


def _decision_evidence_references(
    decision: dict[str, Any],
) -> list[str]:
    values: set[str] = set()
    for action in decision.get("actions", []):
        if not isinstance(action, dict):
            continue
        values.update(
            str(value)
            for value in action.get("evidence_ids", [])
            if isinstance(value, str)
        )
    for update in decision.get("hypothesis_updates", []):
        if not isinstance(update, dict):
            continue
        for key in ("evidence_for", "evidence_against"):
            values.update(
                str(value)
                for value in update.get(key, [])
                if isinstance(value, str)
            )
    return sorted(values)


def _compare_decisions(
    persistent: dict[str, Any],
    stateless: dict[str, Any],
) -> dict[str, Any]:
    return {
        "action_agreement": (
            persistent["selected_action"] == stateless["selected_action"]
        ),
        "algorithm_agreement": (
            persistent["selected_algorithm"]
            == stateless["selected_algorithm"]
        ),
        "parameter_agreement": (
            persistent["selected_parameters"]
            == stateless["selected_parameters"]
        ),
        "hypothesis_agreement": (
            persistent["hypothesis"] == stateless["hypothesis"]
        ),
        "expected_signal_agreement": (
            persistent["expected_signal"] == stateless["expected_signal"]
        ),
        "persistent": {
            "action": persistent["selected_action"],
            "algorithm": persistent["selected_algorithm"],
            "parameters": persistent["selected_parameters"],
        },
        "stateless": {
            "action": stateless["selected_action"],
            "algorithm": stateless["selected_algorithm"],
            "parameters": stateless["selected_parameters"],
        },
    }


def _phase_a_plan_fingerprint(report: dict[str, Any]) -> str:
    value = {
        "runtime_contract": report["runtime_contract"],
        "inference_slots": report["inference_slots"],
        "inference_slot_count": report["inference_slot_count"],
        "fourth_inference_slot_exists": report[
            "fourth_inference_slot_exists"
        ],
        "search_batch_slots": report["search_batch_slots"],
        "compaction_operations_scheduled": report[
            "compaction_operations_scheduled"
        ],
        "requests": [
            {
                key: request[key]
                for key in (
                    "slot",
                    "mode",
                    "source_state",
                    "snapshot_id",
                    "director_state_bytes",
                    "director_state_sha256",
                    "client_owned_estimated_tokens",
                    "prompt_sha256",
                    "output_schema_sha256",
                    "evidence_registry_sha256",
                    "advisory_target_registry_sha256",
                    "executable_target_registry_sha256",
                    "allowed_action_space_sha256",
                    "measurement_only",
                    "executed",
                    "dispatch_scheduled",
                )
            }
            for request in report["requests"]
        ],
    }
    return hashlib.sha256(
        canonical_json(value, max_bytes=1024 * 1024)
    ).hexdigest()
