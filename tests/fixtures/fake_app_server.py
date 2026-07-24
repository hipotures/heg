from __future__ import annotations

import json
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


thread_id = "thread-test"
turn_id = "turn-test"
skills_enabled = True


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
                    "model": "fake-model",
                    "reasoningEffort": "high",
                    "thread": {
                        "id": thread_id,
                        "sessionId": "session-test",
                        "path": "/fake/rollout.jsonl",
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
    elif method == "turn/start":
        params = request.get("params", {})
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
        if MODE == "timeout":
            continue
        if MODE == "partial-final-usage":
            send(
                usage_notification(
                    input_tokens=1,
                    cache_write_input_tokens=0,
                    total_tokens=1,
                )
            )
        send({"id": "server-1", "method": "unknown/request", "params": {}})
        send(
            {
                "method": "item/started",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "startedAtMs": 1,
                    "item": {
                        "id": "item-1",
                        "type": "agentMessage",
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
                    "delta": '{"ok":',
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
                        "type": "agentMessage",
                        "phase": "final_answer",
                        "text": '{"ok":true}',
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
        if MODE != "no-usage":
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
