from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from multiprocessing import get_context
from pathlib import Path
from queue import Empty
from typing import Any, Iterable, Iterator
import hashlib
import json
import math
import platform
import time

from . import __version__
from .model import BitGraph
from .external import NAUTY_GENG
from .locations import source_root
from .resources import run_bounded, set_address_space_limit
from .state import atomic_write_json, utc_now
from .targets.erdos_gyarfas import verify_reference

MAX_SAT_CLAUSES = 1_000_000
MAX_LEARNED_BYTES = 64 * 1024 * 1024
MAX_PROOF_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class EdgeVariables:
    n: int

    def variable(self, u: int, v: int) -> int:
        if u == v:
            raise ValueError("loops have no SAT variable")
        if u > v:
            u, v = v, u
        return 1 + u * (2 * self.n - u - 1) // 2 + (v - u - 1)

    @property
    def count(self) -> int:
        return self.n * (self.n - 1) // 2

    def edge(self, variable: int) -> tuple[int, int]:
        for u in range(self.n):
            for v in range(u + 1, self.n):
                if self.variable(u, v) == variable:
                    return u, v
        raise ValueError("variable is outside edge range")


def base_cnf(n: int) -> tuple[EdgeVariables, list[list[int]]]:
    if n < 4:
        raise ValueError("minimum degree 3 requires order at least 4")
    if n > 40:
        raise ValueError("the v1 SAT path is limited to order 40")
    variables = EdgeVariables(n)
    clauses: list[list[int]] = []
    for vertex in range(n):
        incident = [
            variables.variable(vertex, other) for other in range(n) if other != vertex
        ]
        # At least three of d variables: every d-3+1 subset contains a true one.
        clauses.extend(
            list(subset) for subset in combinations(incident, len(incident) - 2)
        )
    # Sound modest symmetry break: relabel one existing edge as {0, 1}.
    clauses.append([variables.variable(0, 1)])
    return variables, clauses


def cycle_clause(variables: EdgeVariables, witness: Iterable[int]) -> list[int]:
    cycle = tuple(witness)
    if len(cycle) < 3 or len(set(cycle)) != len(cycle):
        raise ValueError("cycle witness must contain distinct vertices")
    return [
        -variables.variable(cycle[index], cycle[(index + 1) % len(cycle)])
        for index in range(len(cycle))
    ]


def _components(graph: BitGraph) -> list[set[int]]:
    remaining = set(range(graph.n))
    components: list[set[int]] = []
    while remaining:
        start = min(remaining)
        component = {start}
        frontier = [start]
        remaining.remove(start)
        while frontier:
            u = frontier.pop()
            for v in graph.neighbors(u):
                if v in remaining:
                    remaining.remove(v)
                    component.add(v)
                    frontier.append(v)
        components.append(component)
    return components


def connectedness_clause(variables: EdgeVariables, component: set[int]) -> list[int]:
    outside = set(range(variables.n)) - component
    return [
        variables.variable(u, v) for u in sorted(component) for v in sorted(outside)
    ]


def decode_model(variables: EdgeVariables, model: Iterable[int]) -> BitGraph:
    positive = {literal for literal in model if literal > 0}
    return BitGraph.from_edges(
        variables.n,
        (
            (u, v)
            for u in range(variables.n)
            for v in range(u + 1, variables.n)
            if variables.variable(u, v) in positive
        ),
    )


def solve_dpll(clauses: list[list[int]], variable_count: int) -> list[int] | None:
    """Small deterministic DPLL used only for tiny ground-truth tests."""

    def recurse(
        current: list[list[int]], assignment: dict[int, bool]
    ) -> dict[int, bool] | None:
        while True:
            if any(not clause for clause in current):
                return None
            unit = next((clause[0] for clause in current if len(clause) == 1), None)
            if unit is None:
                break
            variable, value = abs(unit), unit > 0
            if variable in assignment and assignment[variable] != value:
                return None
            assignment[variable] = value
            current = _simplify(current, variable, value)
        if not current:
            return assignment
        variable = abs(min(current, key=len)[0])
        for value in (True, False):
            candidate = recurse(
                _simplify(current, variable, value),
                {**assignment, variable: value},
            )
            if candidate is not None:
                return candidate
        return None

    solved = recurse([clause[:] for clause in clauses], {})
    if solved is None:
        return None
    return [
        variable if solved.get(variable, False) else -variable
        for variable in range(1, variable_count + 1)
    ]


def _simplify(clauses: list[list[int]], variable: int, value: bool) -> list[list[int]]:
    true_literal = variable if value else -variable
    false_literal = -true_literal
    return [
        [literal for literal in clause if literal != false_literal]
        for clause in clauses
        if true_literal not in clause
    ]


def tiny_cegar(n: int) -> dict[str, Any]:
    if n > 6:
        raise ValueError("the built-in DPLL solver is limited to order 6")
    variables, clauses = base_cnf(n)
    learned: list[dict[str, Any]] = []
    iterations = 0
    while True:
        model = solve_dpll(clauses, variables.count)
        if model is None:
            return {
                "outcome": "UNSAT_GROUND_TRUTH",
                "iterations": iterations,
                "learned": learned,
            }
        iterations += 1
        graph = decode_model(variables, model)
        components = _components(graph)
        if len(components) > 1:
            clause = connectedness_clause(variables, components[0])
            clauses.append(clause)
            learned.append({"kind": "connectedness", "clause": clause})
            continue
        result = verify_reference(graph)
        if result.status == "VERIFIED":
            return {
                "outcome": "SAT_CANDIDATE",
                "iterations": iterations,
                "graph6": graph.to_graph6(),
                "learned": learned,
            }
        witness = result.witnesses[0]
        clause = cycle_clause(variables, witness.vertices)
        clauses.append(clause)
        learned.append(
            {
                "kind": "cycle",
                "vertices": list(witness.vertices),
                "clause": clause,
            }
        )


def nauty_ground_truth(n: int, timeout_seconds: float = 30) -> dict[str, Any]:
    """Enumerate connected labelled-class representatives with geng when available."""

    result = NAUTY_GENG.run(
        ("-cq", "-d3", str(n)),
        timeout_seconds=timeout_seconds,
    )
    if result.status != "OK":
        return {
            "status": result.status,
            "counterexamples": None,
            "message": result.stderr.decode("utf-8", errors="replace"),
        }
    checked = counterexamples = 0
    for line in result.stdout.decode("ascii", errors="strict").splitlines():
        if not line or line.startswith(">"):
            continue
        graph = BitGraph.from_graph6(line)
        checked += 1
        if verify_reference(graph).status == "VERIFIED":
            counterexamples += 1
    return {
        "status": "OK",
        "checked": checked,
        "counterexamples": counterexamples,
    }


def write_dimacs(path: Path, variable_count: int, clauses: list[list[int]]) -> str:
    return _write_dimacs_stream(path, variable_count, len(clauses), clauses)


def _write_dimacs_stream(
    path: Path,
    variable_count: int,
    clause_count: int,
    clauses: Iterable[list[int]],
) -> str:
    digest = hashlib.sha256()
    with path.open("wb") as handle:
        header = f"p cnf {variable_count} {clause_count}\n".encode("ascii")
        handle.write(header)
        digest.update(header)
        for clause in clauses:
            line = (" ".join(map(str, clause)) + " 0\n").encode("ascii")
            handle.write(line)
            digest.update(line)
    return digest.hexdigest()


def _valid_learned_clauses(path: Path, variable_count: int) -> Iterator[list[int]]:
    if not path.is_file():
        return
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            clause = record.get("clause") if isinstance(record, dict) else None
            if (
                isinstance(clause, list)
                and clause
                and all(
                    isinstance(literal, int)
                    and not isinstance(literal, bool)
                    and literal != 0
                    and abs(literal) <= variable_count
                    for literal in clause
                )
            ):
                yield clause


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _hash_artifacts(output_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in output_dir.iterdir():
        if not path.is_file() or path.name == "metadata.json":
            continue
        hashes[path.name] = _hash_file(path)
    return hashes


def _sat_environment() -> dict[str, Any]:
    repository = source_root()
    git = (
        run_bounded(
            ["git", "rev-parse", "HEAD"],
            timeout_seconds=5,
            output_limit_bytes=1024,
            cwd=repository,
        )
        if repository is not None
        else None
    )
    dirty = (
        run_bounded(
            ["git", "status", "--porcelain"],
            timeout_seconds=5,
            output_limit_bytes=1024 * 1024,
            cwd=repository,
        )
        if repository is not None
        else None
    )
    return {
        "python": platform.python_version(),
        "sglab_version": __version__,
        "platform": platform.platform(),
        "git_commit": (
            git.stdout.decode("ascii", errors="replace").strip()
            if git is not None
            else None
        )
        or None,
        "git_dirty": (
            bool(dirty.stdout.strip())
            if dirty is not None and dirty.status == "OK"
            else None
        ),
    }


def _write_failure_artifacts(
    output_dir: Path,
    metadata: dict[str, Any],
    variables: EdgeVariables,
    clauses: list[list[int]],
) -> dict[str, Any]:
    metadata["cnf_sha256"] = write_dimacs(
        output_dir / "instance.cnf", variables.count, clauses
    )
    metadata["artifact_sha256"] = _hash_artifacts(output_dir)
    atomic_write_json(output_dir / "metadata.json", metadata)
    return metadata


def run_pysat_cegar(
    n: int,
    output_dir: Path,
    *,
    timeout_seconds: float,
    seed: int,
    solver_name: str = "cadical195",
    memory_limit_bytes: int = 0,
) -> dict[str, Any]:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("SAT timeout must be positive")
    if memory_limit_bytes < 0:
        raise ValueError("SAT memory limit cannot be negative")
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise ValueError("SAT output directory must be empty")
    context = get_context("spawn")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_pysat_worker,
        args=(
            n,
            output_dir,
            timeout_seconds,
            seed,
            solver_name,
            memory_limit_bytes,
            result_queue,
        ),
        name="sglab-pysat",
    )
    started = time.monotonic()
    try:
        process.start()
    except BaseException as error:
        result_queue.close()
        return _preserve_interrupted_sat(
            n,
            output_dir,
            seed=seed,
            solver_name=solver_name,
            status="TOOL_FAILURE",
            detail="SOLVER_PROCESS_START_FAILED",
            elapsed_seconds=time.monotonic() - started,
            memory_limit_bytes=memory_limit_bytes,
            error=f"{type(error).__name__}: {error}",
        )
    process.join(timeout_seconds)
    if process.is_alive():
        process.kill()
        process.join()
        result_queue.close()
        return _preserve_interrupted_sat(
            n,
            output_dir,
            seed=seed,
            solver_name=solver_name,
            status="UNKNOWN_TIMEOUT",
            detail="UNKNOWN_TIMEOUT",
            elapsed_seconds=time.monotonic() - started,
            memory_limit_bytes=memory_limit_bytes,
        )
    try:
        result = result_queue.get(timeout=1)
    except Empty:
        result = {
            "__status__": (
                "UNKNOWN_MEMORY_LIMIT"
                if memory_limit_bytes and process.exitcode not in (0, None)
                else "TOOL_FAILURE"
            ),
            "__error__": (
                f"solver process produced no result (exit code {process.exitcode})"
            ),
        }
    finally:
        result_queue.close()
    if "__error__" in result:
        status = str(result.get("__status__", "TOOL_FAILURE"))
        return _preserve_interrupted_sat(
            n,
            output_dir,
            seed=seed,
            solver_name=solver_name,
            status=status,
            detail=(
                "UNKNOWN_MEMORY_LIMIT"
                if status == "UNKNOWN_MEMORY_LIMIT"
                else "SOLVER_PROCESS_FAILED"
            ),
            elapsed_seconds=time.monotonic() - started,
            memory_limit_bytes=memory_limit_bytes,
            error=str(result["__error__"]),
        )
    return result


def _pysat_worker(
    n: int,
    output_dir: Path,
    timeout_seconds: float,
    seed: int,
    solver_name: str,
    memory_limit_bytes: int,
    result_queue: Any,
) -> None:
    try:
        set_address_space_limit(memory_limit_bytes or None)
        result = _run_pysat_cegar_inner(
            n,
            output_dir,
            timeout_seconds=timeout_seconds,
            seed=seed,
            solver_name=solver_name,
            memory_limit_bytes=memory_limit_bytes,
        )
    except MemoryError as error:
        result_queue.put(
            {
                "__status__": "UNKNOWN_MEMORY_LIMIT",
                "__error__": f"{type(error).__name__}: {error}",
            }
        )
        return
    except BaseException as error:
        result_queue.put({"__error__": f"{type(error).__name__}: {error}"})
        return
    result_queue.put(result)


def _preserve_interrupted_sat(
    n: int,
    output_dir: Path,
    *,
    seed: int,
    solver_name: str,
    status: str,
    detail: str,
    elapsed_seconds: float,
    memory_limit_bytes: int,
    error: str | None = None,
) -> dict[str, Any]:
    variables, clauses = base_cnf(n)
    learned_path = output_dir / "learned.jsonl"
    learned = sum(1 for _ in _valid_learned_clauses(learned_path, variables.count))
    metadata: dict[str, Any] = {
        "created_at": utc_now(),
        "order": n,
        "seed": seed,
        "requested_solver": solver_name,
        "solver": solver_name,
        "status_checked_at": "2026-07-23",
        "status": status,
        "detail": detail,
        "elapsed_seconds": elapsed_seconds,
        "memory_limit_bytes": memory_limit_bytes,
        "learned_clauses": learned,
        "proof_checked": False,
        "environment": _sat_environment(),
    }
    if error is not None:
        metadata["error"] = error
    metadata["cnf_sha256"] = _write_dimacs_stream(
        output_dir / "instance.cnf",
        variables.count,
        len(clauses) + learned,
        (
            clause
            for source in (
                iter(clauses),
                _valid_learned_clauses(learned_path, variables.count),
            )
            for clause in source
        ),
    )
    metadata["artifact_sha256"] = _hash_artifacts(output_dir)
    atomic_write_json(output_dir / "metadata.json", metadata)
    return metadata


def _run_pysat_cegar_inner(
    n: int,
    output_dir: Path,
    *,
    timeout_seconds: float,
    seed: int,
    solver_name: str = "cadical195",
    memory_limit_bytes: int = 0,
) -> dict[str, Any]:
    variables, clauses = base_cnf(n)
    learned_count = 0
    metadata: dict[str, Any] = {
        "created_at": utc_now(),
        "order": n,
        "seed": seed,
        "requested_solver": solver_name,
        "memory_limit_bytes": memory_limit_bytes,
        "status_checked_at": "2026-07-23",
        "environment": _sat_environment(),
    }
    try:
        from pysat import __version__ as pysat_version
        from pysat.solvers import Solver
    except ImportError as error:
        metadata.update(
            {
                "status": "TOOL_FAILURE",
                "error": str(error),
                "message": "install the optional 'sat' dependency",
            }
        )
        return _write_failure_artifacts(output_dir, metadata, variables, clauses)

    started = time.monotonic()
    outcome = "NO_RESULT_WITHIN_BUDGET"
    proof_enabled = True
    try:
        solver = Solver(
            name=solver_name,
            bootstrap_with=clauses,
            use_timer=True,
            with_proof=True,
        )
    except (NotImplementedError, TypeError):
        proof_enabled = False
        try:
            solver = Solver(
                name=solver_name,
                bootstrap_with=clauses,
                use_timer=True,
            )
        except Exception as error:
            metadata.update(
                {
                    "status": "TOOL_FAILURE",
                    "error": f"{type(error).__name__}: {error}",
                    "pysat_version": pysat_version,
                }
            )
            return _write_failure_artifacts(output_dir, metadata, variables, clauses)
    except Exception as error:
        metadata.update(
            {
                "status": "TOOL_FAILURE",
                "error": f"{type(error).__name__}: {error}",
                "pysat_version": pysat_version,
            }
        )
        return _write_failure_artifacts(output_dir, metadata, variables, clauses)
    seed_applied = False
    try:
        solver.configure({"seed": seed})
        seed_applied = True
    except (AttributeError, NotImplementedError, TypeError, ValueError):
        pass
    learned_path = output_dir / "learned.jsonl"
    learned_path.write_text("", encoding="utf-8")
    try:
        iterations = 0
        while True:
            remaining = timeout_seconds - (time.monotonic() - started)
            if remaining <= 0:
                metadata["detail"] = "UNKNOWN_TIMEOUT"
                outcome = "UNKNOWN_TIMEOUT"
                break
            solved = solver.solve()
            if not solved:
                # No certified status without an independently checked proof.
                metadata["detail"] = "UNSAT_WITHOUT_CHECKED_CERTIFICATE"
                try:
                    proof = solver.get_proof()
                except (AttributeError, NotImplementedError):
                    proof = None
                if proof:
                    proof_path = output_dir / "solver.proof"
                    proof_bytes = 0
                    proof_exceeded = False
                    with proof_path.open("wb") as handle:
                        for proof_line in proof:
                            encoded = (proof_line + "\n").encode("ascii")
                            proof_bytes += len(encoded)
                            if proof_bytes > MAX_PROOF_BYTES:
                                proof_exceeded = True
                                break
                            handle.write(encoded)
                    if proof_exceeded:
                        proof_path.unlink()
                        metadata["proof_preserved"] = False
                        metadata["proof_limit_bytes"] = MAX_PROOF_BYTES
                    else:
                        metadata["proof_preserved"] = True
                break
            iterations += 1
            graph = decode_model(variables, solver.get_model() or ())
            components = _components(graph)
            if len(components) > 1:
                clause = connectedness_clause(variables, components[0])
                record = {
                    "kind": "connectedness",
                    "component": sorted(components[0]),
                    "clause": clause,
                }
            else:
                verified = verify_reference(graph)
                if verified.status == "VERIFIED":
                    outcome = "NO_RESULT_WITHIN_BUDGET"
                    metadata["detail"] = "SAT_CANDIDATE_REQUIRES_SECOND_VERIFIER"
                    (output_dir / "candidate.graph6").write_text(
                        graph.to_graph6() + "\n", encoding="ascii"
                    )
                    break
                witness = verified.witnesses[0]
                clause = cycle_clause(variables, witness.vertices)
                record = {
                    "kind": "cycle",
                    "vertices": list(witness.vertices),
                    "clause": clause,
                }
            line = json.dumps(record, sort_keys=True) + "\n"
            if (
                len(clauses) >= MAX_SAT_CLAUSES
                or learned_path.stat().st_size + len(line.encode("utf-8"))
                > MAX_LEARNED_BYTES
            ):
                outcome = "UNKNOWN_RESOURCE_LIMIT"
                metadata["detail"] = "CEGAR_STORAGE_BOUND_REACHED"
                break
            clauses.append(clause)
            solver.add_clause(clause)
            learned_count += 1
            with learned_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
    finally:
        solver.delete()
    cnf_hash = write_dimacs(output_dir / "instance.cnf", variables.count, clauses)
    metadata.update(
        {
            "status": outcome,
            "solver": solver_name,
            "pysat_version": pysat_version,
            "seed_applied": seed_applied,
            "proof_enabled": proof_enabled,
            "solver_options": {
                "use_timer": True,
                "with_proof": proof_enabled,
            },
            "iterations": locals().get("iterations", 0),
            "learned_clauses": learned_count,
            "cnf_sha256": cnf_hash,
            "elapsed_seconds": time.monotonic() - started,
            "proof_checked": False,
        }
    )
    metadata["artifact_sha256"] = _hash_artifacts(output_dir)
    atomic_write_json(output_dir / "metadata.json", metadata)
    return metadata
