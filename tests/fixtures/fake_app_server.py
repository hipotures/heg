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
                            "errors": [],
                            "skills": [
                                {
                                    "name": "bundled",
                                    "path": "/fake/SKILL.md",
                                    "enabled": True,
                                }
                            ],
                        }
                    ]
                },
            }
        )
    elif method == "skills/config/write":
        send({"id": request_id, "result": {"effectiveEnabled": False}})
    elif method in {"thread/start", "thread/resume"}:
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
    elif method == "turn/start":
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
        send({"id": "server-1", "method": "unknown/request", "params": {}})
        send(
            {
                "method": "item/agentMessage/delta",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
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
                        "items": [],
                    },
                },
            }
        )
        time.sleep(0.02)
        send(
            {
                "method": "thread/tokenUsage/updated",
                "params": {
                    "threadId": thread_id,
                    "turnId": turn_id,
                    "tokenUsage": {
                        "last": {
                            "inputTokens": 10,
                            "cachedInputTokens": 3,
                            "outputTokens": 5,
                            "reasoningOutputTokens": 2,
                            "totalTokens": 15,
                        },
                        "total": {
                            "inputTokens": 10,
                            "cachedInputTokens": 3,
                            "outputTokens": 5,
                            "reasoningOutputTokens": 2,
                            "totalTokens": 15,
                        },
                    },
                },
            }
        )
