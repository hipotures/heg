from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import os

from ..model import BitGraph
from .store import ResearchStore


class CandidateArchive:
    """Bounded retained-candidate artifacts; graph bodies never enter prompts."""

    def __init__(
        self,
        *,
        store: ResearchStore,
        campaign_id: str,
        campaign_dir: Path,
        maximum_candidates: int = 256,
    ):
        if maximum_candidates < 1:
            raise ValueError("candidate maximum must be positive")
        self.store = store
        self.campaign_id = campaign_id
        self.campaign_dir = campaign_dir.resolve()
        self.maximum_candidates = maximum_candidates
        self.artifact_dir = self.campaign_dir / "candidates"
        self.artifact_dir.mkdir(parents=True, exist_ok=True)

    def observe_improvement(self, event: dict[str, Any]) -> str:
        graph6 = str(event["graph6"])
        graph = BitGraph.from_graph6(graph6)
        if graph.to_graph6() != graph6:
            raise ValueError("candidate graph6 is not canonical")
        graph_sha256 = hashlib.sha256(graph6.encode("ascii")).hexdigest()
        candidate_id = f"candidate-{graph_sha256[:24]}"
        relative = Path("candidates") / f"{candidate_id}.graph6"
        payload = (graph6 + "\n").encode("ascii")
        artifact_sha256 = hashlib.sha256(payload).hexdigest()
        _atomic_write(self.campaign_dir / relative, payload)
        inserted = self.store.retain_campaign_candidate(
            candidate_id=candidate_id,
            campaign_id=self.campaign_id,
            lane_id=str(event["lane_id"]),
            lane_version=int(event["lane_version"]),
            checkpoint_ref=str(event.get("checkpoint_id") or "") or None,
            graph6=graph6,
            graph_sha256=graph_sha256,
            score=dict(event["score"]),
            artifact_ref=str(relative),
            artifact_sha256=artifact_sha256,
        )
        if inserted:
            self._prune()
        return candidate_id

    def _prune(self) -> None:
        for relative in self.store.prune_campaign_candidates(
            self.campaign_id, self.maximum_candidates
        ):
            path = (self.campaign_dir / relative).resolve()
            try:
                path.relative_to(self.artifact_dir)
            except ValueError:
                raise RuntimeError("candidate artifact escaped archive") from None
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
