from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Sequence
import tempfile

from .model import BitGraph
from .resources import ProcessResult, run_bounded


@dataclass(frozen=True, slots=True)
class ExternalTool:
    name: str
    executable_names: tuple[str, ...]
    version_args: tuple[str, ...] = ("--version",)

    def executable(self) -> str | None:
        return next(
            (
                path
                for name in self.executable_names
                if (path := which(name)) is not None
            ),
            None,
        )

    def version(self) -> dict[str, str | None]:
        executable = self.executable()
        if executable is None:
            return {"path": None, "version": None}
        result = run_bounded(
            [executable, *self.version_args],
            timeout_seconds=5,
            output_limit_bytes=64 * 1024,
        )
        text = (result.stdout or result.stderr).decode("utf-8", errors="replace")
        return {
            "path": executable,
            "version": text.splitlines()[0] if text else result.status,
        }

    def run(
        self,
        arguments: Sequence[str],
        *,
        timeout_seconds: float,
        cwd: Path | None = None,
    ) -> ProcessResult:
        executable = self.executable()
        if executable is None:
            return ProcessResult(
                "TOOL_FAILURE", None, b"", f"{self.name} is unavailable".encode()
            )
        return run_bounded(
            [executable, *arguments],
            timeout_seconds=timeout_seconds,
            output_limit_bytes=4 * 1024 * 1024,
            cwd=cwd,
        )


NAUTY_GENG = ExternalTool("nauty-geng", ("geng",), ("-help",))
NAUTY_LABELG = ExternalTool("nauty-labelg", ("labelg",), ("-help",))
SMS = ExternalTool("sat-modulo-symmetries", ("sms",))
GLASGOW = ExternalTool(
    "glasgow-subgraph-solver",
    ("glasgow_subgraph_solver", "glasgow-subgraph-solver"),
)

TOOLS = (NAUTY_GENG, NAUTY_LABELG, SMS, GLASGOW)


def canonical_graph6(graph: BitGraph, timeout_seconds: float = 10) -> tuple[str, bool]:
    """Use nauty labelg when installed; otherwise return a non-canonical fallback."""

    if NAUTY_LABELG.executable() is None:
        return graph.to_graph6(), False
    with tempfile.TemporaryDirectory(prefix="sglab-labelg-") as directory:
        root = Path(directory)
        source = root / "input.graph6"
        destination = root / "output.graph6"
        source.write_text(graph.to_graph6() + "\n", encoding="ascii")
        result = NAUTY_LABELG.run(
            ("-q", str(source), str(destination)),
            timeout_seconds=timeout_seconds,
            cwd=root,
        )
        if (
            result.status != "OK"
            or not destination.is_file()
            or destination.stat().st_size > 1024 * 1024
        ):
            return graph.to_graph6(), False
        try:
            canonical = BitGraph.from_graph6(destination.read_text(encoding="ascii"))
        except (OSError, UnicodeDecodeError, ValueError):
            return graph.to_graph6(), False
        if (
            canonical.n != graph.n
            or canonical.size() != graph.size()
            or sorted(canonical.degree_sequence()) != sorted(graph.degree_sequence())
        ):
            return graph.to_graph6(), False
        return canonical.to_graph6(), True
