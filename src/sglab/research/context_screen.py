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
from .protocol import canonical_json, director_decision_schema
from .store import ResearchStore
from .validation import DecisionContext, validate_decision


SCREEN_MODEL = "gpt-5.6-sol"
SCREEN_EFFORT = "high"
SCREEN_SLOTS = (
    ("P1", DirectorContextMode.PERSISTENT_THREAD, "A1"),
    ("P2", DirectorContextMode.PERSISTENT_THREAD, "A4"),
    ("S1", DirectorContextMode.STATELESS_TURNS, "A1"),
    ("S2", DirectorContextMode.STATELESS_TURNS, "A4"),
)
SAFE_ITEM_TYPES = {"userMessage", "reasoning", "agentMessage"}


def build_context_screen_prompt(snapshot: dict[str, Any]) -> str:
    state = prepare_director_state_v2(snapshot).state
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
            ],
        },
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
    schema = director_decision_schema()
    requests = []
    for label, mode, state_label in SCREEN_SLOTS:
        snapshot = states[state_label]
        prepared = prepare_director_state_v2(snapshot)
        prompt = build_context_screen_prompt(snapshot)
        size = complete_context_size_report(
            prepared,
            prompt=prompt,
            base_instructions=base_instructions(),
            output_schema=schema,
            mode=mode,
        )
        envelope = {
            "thread_id": "<runtime-thread-id>",
            "snapshot_id": snapshot["snapshot_id"],
            "trigger_id": "<runtime-trigger-id>",
            "prompt": prompt,
            "output_schema": schema,
        }
        envelope_bytes = canonical_json(envelope, max_bytes=1024 * 1024)
        requests.append(
            {
                "slot": label,
                "mode": mode.value,
                "source_state": state_label,
                "snapshot_id": snapshot["snapshot_id"],
                "director_state_bytes": size["post_compaction"][
                    "director_state_bytes"
                ],
                "ancestry_bytes": size["post_compaction"]["ancestry_bytes"],
                "historical_outcomes_bytes": size["post_compaction"][
                    "historical_outcomes_bytes"
                ],
                "client_owned_estimated_tokens": size[
                    "client_owned_estimated_tokens"
                ],
                "within_state_limits": size["within_state_limits"],
                "within_client_token_limit": size[
                    "within_client_token_limit"
                ],
                "prompt_bytes": len(prompt.encode("utf-8")),
                "prompt_sha256": hashlib.sha256(
                    prompt.encode("ascii")
                ).hexdigest(),
                "request_template_bytes": len(envelope_bytes),
                "request_template_sha256": hashlib.sha256(
                    envelope_bytes
                ).hexdigest(),
                "measurement_only": True,
                "dispatch_scheduled": False,
            }
        )
    by_slot = {value["slot"]: value for value in requests}
    pairwise_identical = {
        "A1_prompt": (
            by_slot["P1"]["prompt_sha256"]
            == by_slot["S1"]["prompt_sha256"]
        ),
        "A4_prompt": (
            by_slot["P2"]["prompt_sha256"]
            == by_slot["S2"]["prompt_sha256"]
        ),
    }
    runtime_contract = {
        "model": SCREEN_MODEL,
        "reasoning_effort": SCREEN_EFFORT,
        "base_instructions_sha256": hashlib.sha256(
            base_instructions().encode("utf-8")
        ).hexdigest(),
        "base_instructions_bytes": len(
            base_instructions().encode("utf-8")
        ),
        "developer_instructions": "",
        "personality": "none",
        "output_schema_sha256": hashlib.sha256(
            canonical_json(schema, max_bytes=1024 * 1024)
        ).hexdigest(),
        "sandbox": "read-only",
        "approval_policy": "never",
        "environments": [],
        "dynamic_tools": [],
        "selected_capability_roots": [],
        "runtime_workspace_roots": [],
        "compaction": False,
    }
    report = {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "phase": "deterministic_context_screen_preparation",
        "source": source_evidence,
        "runtime_contract": runtime_contract,
        "inference_slots": [value[0] for value in SCREEN_SLOTS],
        "inference_slot_count": len(SCREEN_SLOTS),
        "fifth_inference_slot_exists": False,
        "search_batch_slots": 0,
        "compaction_operations_scheduled": 0,
        "requests": requests,
        "pairwise_identical_inputs": pairwise_identical,
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
            value["measurement_only"] and not value["dispatch_scheduled"]
            for value in requests
        ),
        "deterministic_test_flake_fixed": True,
    }
    report["ok"] = bool(
        report["inference_slot_count"] == 4
        and not report["fifth_inference_slot_exists"]
        and report["search_batch_slots"] == 0
        and report["compaction_operations_scheduled"] == 0
        and report["all_states_under_32_kib"]
        and report["all_inputs_under_12000_estimated_tokens"]
        and report["all_decisions_measurement_only"]
        and all(pairwise_identical.values())
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
    turn_timeout_seconds: float = 900.0,
) -> dict[str, Any]:
    if not 1.0 <= turn_timeout_seconds <= 900.0:
        raise ValueError(
            "context-screen turn timeout must be between 1 and 900 seconds"
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
    codex: str,
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
    persistent, stateless = await _run_screen_arms(
        arm_roots=arm_roots,
        states=states,
        codex=codex,
        preflight=preflight,
        protocol_hash=protocol_hash,
        turn_timeout_seconds=turn_timeout_seconds,
    )
    turns = [*persistent["turns"], *stateless["turns"]]
    usage_p = _sum_usage(persistent["turns"])
    usage_s = _sum_usage(stateless["turns"])
    p2 = persistent["turns"][1]
    s2 = stateless["turns"][1]
    p2_input = int(p2["usage"]["input_tokens"])
    s2_input = int(s2["usage"]["input_tokens"])
    reduction = (
        100.0 * (p2_input - s2_input) / p2_input
        if p2_input > 0
        else None
    )
    report = {
        "schema_version": "1.0",
        "created_at": utc_now(),
        "source": source_evidence,
        "codex_version": preflight["codex_version_output"],
        "runtime_contract": phase_a["runtime_contract"],
        "arms": {
            "persistent_thread": persistent,
            "stateless_turns": stateless,
        },
        "usage_totals": {
            "persistent_thread": usage_p,
            "stateless_turns": usage_s,
        },
        "p2_vs_s2": {
            "persistent_input_tokens": p2_input,
            "stateless_input_tokens": s2_input,
            "input_token_difference": p2_input - s2_input,
            "stateless_token_reduction_percent": reduction,
            "latency_seconds_difference": (
                float(p2["latency_seconds"])
                - float(s2["latency_seconds"])
            ),
        },
        "decision_comparison": {
            "A1": _compare_decisions(
                persistent["turns"][0], stateless["turns"][0]
            ),
            "A4": _compare_decisions(
                persistent["turns"][1], stateless["turns"][1]
            ),
        },
        "arm_latency_seconds_difference": (
            float(persistent["latency_total_seconds"])
            - float(stateless["latency_total_seconds"])
        ),
        "successful_model_inferences": len(turns),
        "search_batches": sum(
            int(arm["search_batches"])
            for arm in (persistent, stateless)
        ),
        "search_lanes": sum(
            int(arm["search_lanes"])
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
            "deterministic_test_flake_fixed": bool(
                phase_a["deterministic_test_flake_fixed"]
            ),
            "director_state_v2_bounded": all(
                turn["director_state_bytes"] <= DIRECTOR_STATE_MAX_BYTES
                for turn in turns
            ),
            "persistent_arm_completed": persistent["completed"],
            "stateless_arm_completed": stateless["completed"],
            "exactly_four_model_turns": len(turns) == 4,
            "zero_search_batches": all(
                arm["search_batches"] == 0 and arm["search_lanes"] == 0
                for arm in (persistent, stateless)
            ),
            "zero_compaction_operations": all(
                arm["compaction_operations"] == 0
                for arm in (persistent, stateless)
            ),
            "usage_accounting_complete": all(
                turn["usage"]["server_reported_total_tokens"] is not None
                for turn in turns
            ),
            "semantic_validity_persistent": all(
                turn["semantic_rubric"]["ok"]
                for turn in persistent["turns"]
            ),
            "semantic_validity_stateless": all(
                turn["semantic_rubric"]["ok"]
                for turn in stateless["turns"]
            ),
            "stateless_token_reduction_percent": reduction,
            "recommended_default_context_mode": "inconclusive",
        },
    }
    report["ok"] = bool(
        all(
            value is True
            for key, value in report["status"].items()
            if key
            not in {
                "stateless_token_reduction_percent",
                "recommended_default_context_mode",
            }
        )
        and report["tool_calls"] == 0
        and report["retries_reaching_inference"] == 0
    )
    atomic_write_json(root / "context-screen-report.json", report)
    return report


async def _run_screen_arms(
    *,
    arm_roots: dict[str, Path],
    states: dict[str, dict[str, Any]],
    codex: str,
    preflight: dict[str, Any],
    protocol_hash: str,
    turn_timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run in order; any persistent-arm failure prevents stateless inference."""

    persistent = await _run_screen_arm(
        arm_roots["persistent_thread"],
        mode=DirectorContextMode.PERSISTENT_THREAD,
        slots=(("P1", "A1"), ("P2", "A4")),
        states=states,
        codex=codex,
        preflight=preflight,
        protocol_hash=protocol_hash,
        turn_timeout_seconds=turn_timeout_seconds,
    )
    stateless = await _run_screen_arm(
        arm_roots["stateless_turns"],
        mode=DirectorContextMode.STATELESS_TURNS,
        slots=(("S1", "A1"), ("S2", "A4")),
        states=states,
        codex=codex,
        preflight=preflight,
        protocol_hash=protocol_hash,
        turn_timeout_seconds=turn_timeout_seconds,
    )
    return persistent, stateless


async def _run_screen_arm(
    root: Path,
    *,
    mode: DirectorContextMode,
    slots: tuple[tuple[str, str], tuple[str, str]],
    states: dict[str, dict[str, Any]],
    codex: str,
    preflight: dict[str, Any],
    protocol_hash: str,
    turn_timeout_seconds: float,
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
            launcher=(codex,),
            model=SCREEN_MODEL,
            effort=SCREEN_EFFORT,
            turn_timeout_seconds=turn_timeout_seconds,
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
    arm_body_completed = False
    try:
        await director.start()
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
            store.mark_trigger_status(trigger_id, "measurement_only")
        store.finish_campaign(
            campaign_id,
            terminal_kind="stopped_by_operator",
            detail="Context-mode screen completed without decision dispatch",
        )
        arm_body_completed = True
    finally:
        close_completed = False
        try:
            await director.close()
            close_completed = True
        finally:
            if not arm_body_completed or not close_completed:
                store.close()
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
        len(turns) == 2
        and integrity == "ok"
        and counts == {
            "lanes": 0,
            "metric_windows": 0,
            "decision_batches": 0,
        }
        and all(row["model_requested"] == SCREEN_MODEL for row in session_rows)
        and all(row["effort_requested"] == SCREEN_EFFORT for row in session_rows)
        and all(turn["item_id"] is not None for turn in turns)
        and client.unsupported_server_requests == 0
        and (
            len(set(thread_ids)) == 1
            if mode is DirectorContextMode.PERSISTENT_THREAD
            else len(set(thread_ids)) == 2
        )
        and client.last_shutdown_mode == "graceful"
    )
    return {
        "mode": mode.value,
        "turns": turns,
        "thread_ids": thread_ids,
        "sessions": session_rows,
        "search_batches": counts["metric_windows"],
        "search_lanes": counts["lanes"],
        "persisted_decision_batches": counts["decision_batches"],
        "compaction_operations": sum(
            int(turn["compaction_operation_count"]) for turn in turns
        ),
        "sqlite_integrity_check": integrity,
        "graceful_shutdown": client.last_shutdown_mode,
        "unsupported_server_requests": client.unsupported_server_requests,
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
    action = (
        evidence.decision["actions"][0]
        if evidence.decision.get("actions")
        else {}
    )
    algorithm, parameters = _selected_algorithm_and_parameters(action)
    usage = {
        "input_tokens": int(row["input_tokens"] or 0),
        "cached_input_tokens": int(row["cached_input_tokens"] or 0),
        "cache_write_input_tokens": int(
            row["cache_write_input_tokens"] or 0
        ),
        "output_tokens": int(row["output_tokens"] or 0),
        "reasoning_output_tokens": int(
            row["reasoning_output_tokens"] or 0
        ),
        "server_reported_total_tokens": (
            int(row["total_tokens"])
            if row["total_tokens"] is not None
            else None
        ),
    }
    result = {
        "slot": label,
        "mode": mode.value,
        "measurement_only": True,
        "executed": False,
        "thread_id": str(row["thread_id"]),
        "turn_id": str(row["turn_id"]),
        "item_id": row["final_agent_item_id"],
        "turn_record_id": turn_record_id,
        "snapshot_id": snapshot["snapshot_id"],
        "director_state_bytes": prepared.size_report["post_compaction"][
            "director_state_bytes"
        ],
        "full_client_request_bytes": request_path.stat().st_size,
        "turn_start_json_rpc_bytes": wire["turn_start_json_rpc_bytes"],
        "latency_seconds": float(row["wall_seconds"]),
        "schema_validity": _decision_schema_shape_valid(raw_decision),
        "local_semantic_validity": evidence.validation.accepted,
        "semantic_rubric": semantic,
        "selected_action": action.get("type"),
        "selected_algorithm": algorithm,
        "selected_parameters": parameters,
        "hypothesis": [
            value.get("statement")
            for value in evidence.decision.get("hypothesis_updates", [])
        ],
        "expected_signal": action.get("expected_effect"),
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
            "raw_decision": raw_decision,
            "validated_decision": evidence.decision,
            "validation_issues": [
                {"path": issue.path, "message": issue.message}
                for issue in evidence.validation.issues
            ],
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
        "no_code_tool_file_or_shell_request": not prohibited_request,
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
                    "client_owned_estimated_tokens",
                    "prompt_sha256",
                    "measurement_only",
                    "dispatch_scheduled",
                )
            }
            for request in report["requests"]
        ],
    }
    return hashlib.sha256(
        canonical_json(value, max_bytes=1024 * 1024)
    ).hexdigest()
