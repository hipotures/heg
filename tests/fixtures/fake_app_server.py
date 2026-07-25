from __future__ import annotations

import json
import os
import sys
import time


MODE = next(
    (
        argument.split("=", 1)[1]
        for argument in sys.argv
        if argument.startswith("--fake-mode=")
    ),
    "normal",
)


def send(value: dict) -> None:
    print(json.dumps(value, separators=(",", ":")), flush=True)


P2_SHAPE = MODE in {"p2-timeout", "p2-late-abort"}
DIRECTOR_SCREEN = MODE.startswith("director-screen")


def claim_screen_process_index() -> int:
    if not DIRECTOR_SCREEN or MODE not in {
        "director-screen-schema-invalid-first",
        "director-screen-semantic-invalid-first",
        "director-screen-semantic-invalid-second",
    }:
        return 0
    marker = os.path.abspath(
        os.path.join(
            os.environ["CODEX_HOME"],
            "..",
            "..",
            "..",
            "..",
            ".fake-screen-process-count",
        )
    )
    try:
        with open(marker, encoding="ascii") as reader:
            current = int(reader.read())
    except FileNotFoundError:
        current = 0
    with open(marker, "w", encoding="ascii") as writer:
        writer.write(str(current + 1))
    return current + 1


screen_process_index = claim_screen_process_index()
thread_id = (
    "019f953e-5817-7c21-ae03-79c0ad6942eb"
    if P2_SHAPE
    else f"thread-screen-{os.getpid()}"
    if DIRECTOR_SCREEN
    else "thread-test"
)
turn_id = (
    "019f953e-e784-7241-bd0d-28b92c67570b"
    if P2_SHAPE
    else "turn-test"
)
reasoning_item_ids = (
    (
        "rs_07a914ce88aabd5b016a63a59d53a48191a3a8198fe946f174",
        "rs_07a914ce88aabd5b016a63a5a6f36c8191a70be144eec325a2",
    )
    if P2_SHAPE
    else ("reasoning-1", "reasoning-2")
)
skills_enabled = True
turn_count = 0
scratch_path = None
secondary_scratch_path = None


def create_wrapper_symlinks() -> None:
    wrapper_modes = {
        "director-screen-wrappers",
        "director-screen-wrapper-unexpected",
        "director-screen-wrapper-wrong-directory",
        "director-screen-wrapper-untrusted",
        "director-screen-wrapper-broken",
    }
    if MODE not in wrapper_modes:
        return
    home = os.environ["CODEX_HOME"]
    expected = os.path.join(
        home,
        "tmp",
        "arg0",
        f"codex-arg0-fake-{os.getpid()}",
    )
    os.makedirs(expected, mode=0o700, exist_ok=True)
    trusted_target = os.path.realpath(sys.executable)
    names = (
        "apply_patch",
        "applypatch",
        "codex-execve-wrapper",
        "codex-linux-sandbox",
    )
    if MODE == "director-screen-wrapper-unexpected":
        names = ("unexpected-wrapper",)
    if MODE == "director-screen-wrapper-wrong-directory":
        os.symlink(
            trusted_target,
            os.path.join(os.environ["CODEX_SQLITE_HOME"], "apply_patch"),
        )
        return
    if MODE == "director-screen-wrapper-untrusted":
        trusted_target = "/etc/passwd"
    if MODE == "director-screen-wrapper-broken":
        trusted_target = f"/nonexistent/sglab-wrapper-{os.getpid()}"
    for name in names:
        os.symlink(trusted_target, os.path.join(expected, name))


create_wrapper_symlinks()


def screen_snapshot_id(params: dict) -> str:
    inputs = params.get("input", [])
    if not inputs or not isinstance(inputs[0], dict):
        return "snapshot-missing"
    try:
        prompt = json.loads(str(inputs[0].get("text") or ""))
    except json.JSONDecodeError:
        return "snapshot-missing"
    state = prompt.get("director_state_v2")
    return (
        str(state.get("source_snapshot_id"))
        if isinstance(state, dict)
        else "snapshot-missing"
    )


def screen_decision(snapshot_id: str) -> dict:
    review = {
        "min_wall_seconds": 30,
        "max_wall_seconds": 120,
        "candidate_delta": 1000,
        "events": ["stagnation"],
    }
    decision = {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "campaign_assessment": (
            "The truncated heuristic evidence is not exact certification."
        ),
        "hypothesis_updates": [],
        "actions": [
            {
                "action_id": "measurement-review",
                "type": "set_review_trigger",
                "priority": 10,
                "hypothesis_ids": [],
                "evidence_ids": [snapshot_id],
                "rationale": "Retain an inert measurement recommendation.",
                "expected_effect": "No search is executed in this screen.",
                "evaluation_window": {
                    "max_wall_seconds": 120,
                    "max_candidate_delta": 1000,
                },
                "idempotency_key": "measurement-review-key",
                "lease_seconds": 300,
                "fallback": {"on_precondition_failure": "reject"},
                "review_trigger": review,
            }
        ],
        "next_review": review,
    }
    if MODE == "director-screen-schema-invalid" or (
        MODE == "director-screen-schema-invalid-first"
        and screen_process_index == 1
    ):
        decision.pop("next_review")
    if MODE == "director-screen-semantic-invalid" or (
        MODE == "director-screen-semantic-invalid-first"
        and screen_process_index == 1
    ) or (
        MODE == "director-screen-semantic-invalid-second"
        and screen_process_index == 2
    ):
        decision["actions"][0]["evidence_ids"] = ["unknown-evidence"]
    if MODE == "director-screen-large-response":
        decision["campaign_assessment"] = "x" * (2 * 1024 * 1024)
    return decision


def usage_notification(
    *,
    input_tokens: int = 10,
    cache_write_input_tokens: int = 4,
    total_tokens: int = 15,
) -> dict:
    breakdown = {
        "inputTokens": input_tokens,
        "cachedInputTokens": 3,
        "cacheWriteInputTokens": cache_write_input_tokens,
        "outputTokens": 5,
        "reasoningOutputTokens": 2,
        "totalTokens": total_tokens,
    }
    return {
        "method": "thread/tokenUsage/updated",
        "params": {
            "threadId": thread_id,
            "turnId": turn_id,
            "tokenUsage": {"last": breakdown, "total": breakdown},
        },
    }


for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    request_id = request.get("id")
    if method == "initialize":
        send(
            {
                "id": request_id,
                "result": {
                    "codexHome": "/fake",
                    "platformFamily": "unix",
                    "platformOs": "linux",
                    "userAgent": "fake",
                },
            }
        )
    elif method == "skills/list":
        send(
            {
                "id": request_id,
                "result": {
                    "data": [
                        {
                            "cwd": "/fake",
                            "errors": (
                                [{"path": "/fake/bad", "message": "bad skill"}]
                                if MODE == "skill-errors"
                                else []
                            ),
                            "skills": [
                                {
                                    "name": "bundled",
                                    "path": (
                                        "relative/SKILL.md"
                                        if MODE == "relative-skill"
                                        else "/fake/SKILL.md"
                                    ),
                                    "enabled": skills_enabled,
                                }
                            ],
                        }
                    ]
                },
            }
        )
    elif method == "skills/config/write":
        skills_enabled = False
        send({"id": request_id, "result": {"effectiveEnabled": False}})
    elif method in {"thread/start", "thread/resume"}:
        params = request.get("params", {})
        required = {"runtimeWorkspaceRoots"}
        if method == "thread/start":
            required.update(
                {
                    "environments",
                    "dynamicTools",
                    "selectedCapabilityRoots",
                }
            )
        if any(params.get(field) != [] for field in required):
            send(
                {
                    "id": request_id,
                    "error": {
                        "code": -32602,
                        "message": "missing isolation fields",
                    },
                }
            )
            continue
        send(
            {
                "id": request_id,
                "result": {
                    "model": (
                        "wrong-model"
                        if MODE == "director-screen-model-mismatch"
                        else params.get("model")
                        if DIRECTOR_SCREEN and params.get("model")
                        else "fake-model"
                    ),
                    "reasoningEffort": (
                        params.get("config", {}).get(
                            "model_reasoning_effort", "high"
                        )
                        if DIRECTOR_SCREEN
                        else "high"
                    ),
                    "thread": {
                        "id": thread_id,
                        "sessionId": "session-test",
                        "path": "/fake/rollout.jsonl",
                        **(
                            {"effectiveContextMode": "compacted_thread"}
                            if MODE == "director-screen-context-mismatch"
                            else {}
                        ),
                    },
                },
            }
        )
    elif method == "thread/compact/start":
        if request.get("params", {}).get("threadId") != thread_id:
            send(
                {
                    "id": request_id,
                    "error": {
                        "code": -32602,
                        "message": "unknown thread",
                    },
                }
            )
            continue
        send({"id": request_id, "result": {}})
    elif method == "turn/interrupt":
        if request.get("params") != {
            "threadId": thread_id,
            "turnId": turn_id,
        }:
            send(
                {
                    "id": request_id,
                    "error": {
                        "code": -32602,
                        "message": "unknown turn",
                    },
                }
            )
            continue
        send({"id": request_id, "result": {}})
        if MODE in {
            "late-abort",
            "p2-late-abort",
            "director-screen-late-abort-second",
        }:
            time.sleep(0.02)
            send(
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": thread_id,
                        "turn": {
                            "id": turn_id,
                            "status": "interrupted",
                            "items": [
                                {
                                    "id": reasoning_item_ids[0],
                                    "type": "reasoning",
                                },
                                {
                                    "id": reasoning_item_ids[1],
                                    "type": "reasoning",
                                },
                            ],
                        },
                    },
                }
            )
    elif method == "turn/start":
        turn_count += 1
        if MODE in {
            "director-screen-scratch-80m",
            "director-screen-scratch-exceed",
            "director-screen-scratch-total-exceed",
            "director-screen-wal-growth",
            "director-screen-hardlink",
        }:
            scratch_name = (
                "state_5.sqlite-wal"
                if MODE == "director-screen-wal-growth"
                else "transient-runtime.bin"
            )
            scratch_path = os.path.join(
                os.environ["CODEX_SQLITE_HOME"], scratch_name
            )
            with open(scratch_path, "wb"):
                pass
            os.truncate(
                scratch_path,
                80 * 1024 * 1024
                if MODE == "director-screen-scratch-80m"
                else 3 * 1024 * 1024
                if MODE == "director-screen-scratch-total-exceed"
                else 4 * 1024 * 1024
                if MODE == "director-screen-hardlink"
                else 8 * 1024 * 1024,
            )
            if MODE == "director-screen-hardlink":
                secondary_scratch_path = scratch_path + ".link"
                os.link(scratch_path, secondary_scratch_path)
            elif MODE == "director-screen-scratch-total-exceed":
                secondary_scratch_path = scratch_path + ".second"
                with open(secondary_scratch_path, "wb"):
                    pass
                os.truncate(secondary_scratch_path, 3 * 1024 * 1024)
        if MODE == "director-screen-symlink-escape":
            scratch_path = os.path.join(
                os.environ["CODEX_SQLITE_HOME"], "escape-link"
            )
            os.symlink("/etc/passwd", scratch_path)
        if MODE == "director-screen-log-growth":
            chunk = b"synthetic-stderr-growth\n" * 4096
            for _ in range(16):
                os.write(2, chunk)
        params = request.get("params", {})
        snapshot_id = screen_snapshot_id(params)
        if DIRECTOR_SCREEN:
            turn_id = f"turn-screen-{turn_count}"
        if params.get("environments") != [] or params.get(
            "runtimeWorkspaceRoots"
        ) != []:
            send(
                {
                    "id": request_id,
                    "error": {
                        "code": -32602,
                        "message": "missing turn isolation fields",
                    },
                }
            )
            continue
        send(
            {
                "id": request_id,
                "result": {
                    "turn": {"id": turn_id, "status": "inProgress", "items": []}
                },
            }
        )
        if MODE == "malformed":
            print("{bad", flush=True)
            continue
        if MODE == "director-screen-malformed-jsonl":
            print("{bad", flush=True)
            continue
        screen_timeout = (
            MODE == "director-screen-timeout-first"
            or MODE == "director-screen-forced-shutdown"
            or (
                MODE == "director-screen-timeout-a1"
                and snapshot_id == "snapshot-a1"
            )
            or (
                MODE
                in {
                    "director-screen-timeout-second",
                    "director-screen-late-abort-second",
                }
                and turn_count == 2
            )
        )
        if MODE in {
            "timeout",
            "late-abort",
            "p2-timeout",
            "p2-late-abort",
        } or screen_timeout:
            for item_id in reasoning_item_ids:
                send(
                    {
                        "method": "item/started",
                        "params": {
                            "threadId": thread_id,
                            "turnId": turn_id,
                            "startedAtMs": 1,
                            "item": {
                                "id": item_id,
                                "type": "reasoning",
                            },
                        },
                    }
                )
            continue
        if MODE == "partial-final-usage":
            send(
                usage_notification(
                    input_tokens=1,
                    cache_write_input_tokens=0,
                    total_tokens=1,
                )
            )
        if MODE == "director-screen-unsupported-request":
            send(
                {
                    "id": "server-comparison-1",
                    "method": "unknown/request",
                    "params": {},
                }
            )
        if MODE == "director-screen-retrying-error":
            send(
                {
                    "method": "error",
                    "params": {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "willRetry": True,
                        "error": {"message": "synthetic retry"},
                    },
                }
            )
        if not DIRECTOR_SCREEN:
            send({"id": "server-1", "method": "unknown/request", "params": {}})
        final_text = json.dumps(
            (
                screen_decision(snapshot_id)
                if DIRECTOR_SCREEN
                else {"ok": True}
            ),
            separators=(",", ":"),
        )
        item_type = (
            "dynamicToolCall"
            if MODE == "director-screen-tool-call"
            else "agentMessage"
        )
        if MODE == "director-screen-process-crash":
            raise SystemExit(17)
        send(
            {
                "method": "item/started",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "startedAtMs": 1,
                    "item": {
                        "id": "item-1",
                        "type": item_type,
                        "phase": "final_answer",
                        "text": "",
                    },
                },
            }
        )
        send(
            {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "itemId": (
                        "unknown-item"
                        if MODE == "bad-item-correlation"
                        else "item-1"
                    ),
                    "delta": final_text[: max(1, len(final_text) // 2)],
                },
            }
        )
        send(
            {
                "method": "item/completed",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "completedAtMs": 1,
                    "item": {
                        "id": "item-1",
                        "type": item_type,
                        "phase": "final_answer",
                        "text": final_text,
                    },
                },
            }
        )
        send(
            {
                "method": "turn/completed",
                "params": {
                    "threadId": thread_id,
                    "turn": {
                        "id": turn_id,
                        "status": "completed",
                        "items": [
                            {
                                "id": "item-1",
                                "type": "agentMessage",
                                "phase": "final_answer",
                                "text": '{"ok":true}',
                            }
                        ],
                    },
                },
            }
        )
        if MODE not in {"no-usage", "director-screen-no-usage"}:
            time.sleep(0.02)
            send(usage_notification())
        if MODE == "duplicate-usage":
            time.sleep(0.02)
            send(
                usage_notification(
                    input_tokens=11,
                    cache_write_input_tokens=6,
                    total_tokens=16,
                )
            )

if MODE == "director-screen-forced-shutdown":
    while True:
        time.sleep(1)
if MODE == "director-screen-scratch-on-shutdown":
    scratch_path = os.path.join(
        os.environ["CODEX_SQLITE_HOME"], "shutdown-growth.bin"
    )
    with open(scratch_path, "wb"):
        pass
    os.truncate(scratch_path, 8 * 1024 * 1024)
if scratch_path is not None and MODE != "director-screen-scratch-on-shutdown":
    try:
        os.unlink(scratch_path)
    except FileNotFoundError:
        pass
if secondary_scratch_path is not None:
    try:
        os.unlink(secondary_scratch_path)
    except FileNotFoundError:
        pass
