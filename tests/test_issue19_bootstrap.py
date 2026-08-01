from __future__ import annotations

import asyncio
import json
import time
import unittest
from pathlib import Path
import tempfile

from sglab.research.actions import LaneActionDispatcher
from sglab.research.director import DirectorEvidence
from sglab.research.lanes import LaneManager
from sglab.research.orchestrator import ActiveResearchOrchestrator
from sglab.research.snapshot import SnapshotBuilder
from sglab.research.store import ResearchStore
from sglab.research.triggers import TriggerEngine
from sglab.research.validation import DecisionContext, validate_decision


RANKING_ID = "mutation_forge_stage4r_v1"


def _common(action_id: str) -> dict:
    return {
        "action_id": action_id,
        "type": "start_lane",
        "priority": 100,
        "hypothesis_ids": [],
        "evidence_ids": [],
        "rationale": "Deterministic issue-19 bootstrap lane.",
        "expected_effect": "Reach a positive evaluation count.",
        "evaluation_window": {
            "max_wall_seconds": 30,
            "max_candidate_delta": 100,
        },
        "idempotency_key": "issue-19-bootstrap-start",
        "lease_seconds": 120,
        "fallback": {"on_precondition_failure": "reject"},
    }


class BootstrapProvider:
    source_kind = "deterministic_bootstrap_fixture"

    def __init__(self, store: ResearchStore, campaign_id: str):
        self.store = store
        self.campaign_id = campaign_id
        self._session_recorded = False

    async def decide(
        self,
        *,
        snapshot: dict,
        trigger_id: str,
        context: DecisionContext,
    ) -> DirectorEvidence:
        decision = {
            "schema_version": "1.0",
            "snapshot_id": snapshot["snapshot_id"],
            "campaign_assessment": "Bootstrap the first lane from zero state.",
            "hypothesis_updates": [],
            "actions": [
                {
                    **_common("issue-19-bootstrap-start"),
                    "spec": {
                        "algorithm": "simulated_annealing",
                        "graph_family": "connected_cubic",
                        "seed": 19,
                        "parameters": {
                            "order": 8,
                            "batch_candidates": 100,
                            "witness_cap": 4,
                            "proposal_ranking": RANKING_ID,
                        },
                        "resource_share": 1.0,
                    },
                }
            ],
            "next_review": {
                "min_wall_seconds": 30,
                "max_wall_seconds": 60,
                "candidate_delta": 100_000,
                "events": ["lane_failure", "new_global_best"],
            },
        }
        validation = validate_decision(decision, context)
        if not validation.accepted:
            raise AssertionError(validation.issues)
        if not self._session_recorded:
            self.store.record_session(
                record_id="issue-19-session",
                campaign_id=self.campaign_id,
                thread_id="issue-19-thread",
                session_id=None,
                thread_path=None,
                parent_thread_id=None,
                model="deterministic-bootstrap",
                effort="none",
                codex_version="issue-19-test",
                executable_sha256="issue-19-test",
                protocol_schema_sha256="issue-19-test",
            )
            self._session_recorded = True
        turn_record_id = f"issue-19-turn-{snapshot['snapshot_id']}"
        self.store.begin_turn(
            turn_record_id=turn_record_id,
            session_record_id="issue-19-session",
            campaign_id=self.campaign_id,
            thread_id="issue-19-thread",
            snapshot_id=snapshot["snapshot_id"],
            trigger_id=trigger_id,
            request_artifact_ref="issue-19/request.json",
            request_sha256="issue-19",
            wire_artifact_ref="issue-19/wire.jsonl",
        )
        self.store.complete_turn(
            turn_record_id,
            turn_id=turn_record_id,
            status="completed_valid",
            wall_seconds=0.0,
        )
        return DirectorEvidence(
            decision=decision,
            validation=validation,
            session_record_id="issue-19-session",
            turn_record_ids=(turn_record_id,),
            thread_id="issue-19-thread",
            turn_id=turn_record_id,
        )


class Issue19BootstrapIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_zero_lane_ranked_campaign_starts_lane_and_evaluates(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            campaign_id = "heg-ranked-001"
            store = ResearchStore(root / "results.sqlite3")
            manager = LaneManager(
                root,
                max_active_lanes=1,
                telemetry_windows=8,
                checkpoints_per_lane=2,
            )
            store.create_campaign(
                campaign_id=campaign_id,
                target="erdos_gyarfas",
                target_definition_sha256="a" * 64,
                stop_mode="until_success",
                deadline_at=None,
            )
            dispatcher = LaneActionDispatcher(
                store=store,
                manager=manager,
                campaign_id=campaign_id,
            )
            provider = BootstrapProvider(store, campaign_id)
            orchestrator = ActiveResearchOrchestrator(
                store=store,
                manager=manager,
                dispatcher=dispatcher,
                snapshots=SnapshotBuilder(
                    store=store,
                    manager=manager,
                    campaign_id=campaign_id,
                    campaign_dir=root,
                    proposal_ranking_catalog_id=RANKING_ID,
                ),
                provider=provider,
                triggers=TriggerEngine(debounce_seconds=0),
                campaign_id=campaign_id,
                inference_poll_seconds=0.005,
            )
            try:
                orchestrator.bootstrap()
                result = await orchestrator.run_due_cycle()
                self.assertEqual(
                    set(result.action_statuses.values()), {"accepted"}
                )
                self.assertEqual(len(manager.lanes), 1)
                deadline = time.monotonic() + 8.0
                while (
                    manager.total_candidates() <= 0
                    and time.monotonic() < deadline
                ):
                    orchestrator.pump_events()
                    await asyncio.sleep(0.02)
                self.assertGreater(manager.total_candidates(), 0)
                metric_rows = store.connection.execute(
                    "SELECT metrics_json FROM lane_metric_windows "
                    "WHERE campaign_id=?",
                    (campaign_id,),
                ).fetchall()
                evaluated = sum(
                    int(json.loads(row[0]).get("evaluated", 0))
                    for row in metric_rows
                )
                self.assertGreater(evaluated, 0)
                lane = next(iter(manager.lanes.values()))
                self.assertEqual(
                    lane.parameters["proposal_ranking"], RANKING_ID
                )
            finally:
                manager.shutdown()
                store.close()


if __name__ == "__main__":
    unittest.main()
