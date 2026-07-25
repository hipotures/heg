#!/usr/bin/env python3
"""Short model-free two-attempt campaign continuity demonstration."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
import json

from sglab.research.campaign import ResearchCampaignRunner
from sglab.research.store import ResearchStore


def _snapshot(workspace: Path, campaign_id: str) -> dict:
    with ResearchStore(workspace / "results.sqlite3") as store:
        counters = store.cumulative_campaign_counters(campaign_id)
        attempts = store.execution_attempts(campaign_id)
        hypotheses = [
            dict(row)
            for row in store.connection.execute(
                """
                SELECT hypothesis_id, status, confidence
                FROM research_hypotheses_v2 WHERE campaign_id=?
                ORDER BY created_at, rowid
                """,
                (campaign_id,),
            )
        ]
        jobs = [
            dict(row)
            for row in store.connection.execute(
                """
                SELECT verification_job_id, candidate_id, state,
                       certification_status
                FROM campaign_verification_jobs WHERE campaign_id=?
                ORDER BY created_at, rowid
                """,
                (campaign_id,),
            )
        ]
        actions = [
            str(row[0])
            for row in store.connection.execute(
                """
                SELECT idempotency_key FROM director_actions
                WHERE campaign_id=? ORDER BY created_at, rowid
                """,
                (campaign_id,),
            )
        ]
        memory = store.latest_memory_snapshot(campaign_id)
        checkpoints = store.checkpoint_references(campaign_id)
        integrity = str(
            store.connection.execute("PRAGMA integrity_check").fetchone()[0]
        )
        foreign_keys = len(
            store.connection.execute("PRAGMA foreign_key_check").fetchall()
        )
    return {
        "campaign_id": campaign_id,
        "counters": counters,
        "attempts": attempts,
        "hypotheses": hypotheses,
        "verifier_jobs": jobs,
        "idempotency_keys": actions,
        "memory_snapshot": (
            {
                key: memory[key]
                for key in (
                    "memory_snapshot_id",
                    "version",
                    "sha256",
                    "byte_size",
                    "estimated_token_count",
                    "creation_trigger",
                )
            }
            if memory is not None
            else None
        ),
        "checkpoints": checkpoints,
        "integrity_check": integrity,
        "foreign_key_violations": foreign_keys,
    }


def main() -> int:
    parser = ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--first-seconds", type=float, default=65)
    parser.add_argument("--second-seconds", type=float, default=65)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    if workspace.exists() and any(workspace.iterdir()):
        raise SystemExit("demo workspace must be absent or empty")
    workspace.mkdir(parents=True, exist_ok=True)
    first = ResearchCampaignRunner(
        workspace=workspace,
        stop_mode="time_limit",
        duration_seconds=args.first_seconds,
        controller_mode="continuity_demo",
        controller_seed=20260726,
        maximum_director_turns=100,
        resume_resource_overrides={
            "cpu_workers": 2,
            "maximum_active_lanes": 2,
        },
        code_commit="continuity-demo-attempt-1",
    ).run()
    campaign_id = str(first["campaign_id"])
    before = _snapshot(workspace, campaign_id)
    second = ResearchCampaignRunner(
        workspace=workspace,
        stop_mode="time_limit",
        duration_seconds=args.second_seconds,
        campaign_id=campaign_id,
        controller_mode="continuity_demo",
        controller_seed=20260726,
        maximum_director_turns=100,
        resume_resource_overrides={
            "cpu_workers": 16,
            "maximum_active_lanes": 8,
        },
        code_commit="continuity-demo-attempt-2",
    ).run()
    after = _snapshot(workspace, campaign_id)
    attempts = after["attempts"]
    result = {
        "schema_version": "1.0",
        "model_inferences": 0,
        "auth_accesses": 0,
        "campaign_id": campaign_id,
        "same_campaign_id": second["campaign_id"] == campaign_id,
        "attempt_ids": [item["attempt_id"] for item in attempts],
        "different_attempt_ids": (
            len(attempts) == 2
            and attempts[0]["attempt_id"] != attempts[1]["attempt_id"]
        ),
        "before": before,
        "after": after,
        "evaluations_increased": (
            after["counters"]["evaluations"]
            > before["counters"]["evaluations"]
        ),
        "hypotheses_preserved": (
            before["hypotheses"]
            and before["hypotheses"] == after["hypotheses"]
        ),
        "verifier_evidence_preserved": all(
            item in after["verifier_jobs"]
            for item in before["verifier_jobs"]
        ),
        "checkpoint_reused": bool(
            json.loads(attempts[1]["starting_checkpoint_refs_json"])
        ),
        "memory_reused": (
            attempts[1]["starting_memory_snapshot_id"]
            == before["memory_snapshot"]["memory_snapshot_id"]
        ),
        "idempotency_preserved": (
            len(after["idempotency_keys"])
            == len(set(after["idempotency_keys"]))
        ),
        "resource_change": {
            "first": json.loads(attempts[0]["effective_resource_json"]),
            "second": json.loads(attempts[1]["effective_resource_json"]),
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if all(
        (
            result["same_campaign_id"],
            result["different_attempt_ids"],
            result["evaluations_increased"],
            result["hypotheses_preserved"],
            result["verifier_evidence_preserved"],
            result["checkpoint_reused"],
            result["memory_reused"],
            result["idempotency_preserved"],
            after["integrity_check"] == "ok",
            after["foreign_key_violations"] == 0,
        )
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
