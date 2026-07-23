from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from threading import Timer
from typing import Any, Iterable
import hashlib
import json
import time

from .model import BitGraph
from .external import NAUTY_GENG
from .state import atomic_write_json, utc_now
from .targets.erdos_gyarfas import verify_reference


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
    variables = EdgeVariables(n)
    clauses: list[list[int]] = []
    for vertex in range(n):
        incident = [
            variables.variable(vertex, other)
            for other in range(n)
            if other != vertex
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
        variables.variable(u, v)
        for u in sorted(component)
        for v in sorted(outside)
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

    def recurse(current: list[list[int]], assignment: dict[int, bool]) -> dict[int, bool] | None:
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


def _simplify(
    clauses: list[list[int]], variable: int, value: bool
) -> list[list[int]]:
    true_literal = variable if value else -variable
    false_literal = -true_literal
    return [
        [literal for literal in clause if literal != false_literal]
        for clause in clauses
        if true_literal not in clause
    ]


def tiny_cegar(n: int) -> dict[str, Any]:
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
    lines = [f"p cnf {variable_count} {len(clauses)}"]
    lines.extend(" ".join(map(str, clause)) + " 0" for clause in clauses)
    payload = "\n".join(lines) + "\n"
    path.write_text(payload, encoding="ascii")
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def run_pysat_cegar(
    n: int,
    output_dir: Path,
    *,
    timeout_seconds: float,
    seed: int,
    solver_name: str = "cadical195",
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    variables, clauses = base_cnf(n)
    learned: list[dict[str, Any]] = []
    metadata: dict[str, Any] = {
        "created_at": utc_now(),
        "order": n,
        "seed": seed,
        "requested_solver": solver_name,
        "status_checked_at": "2026-07-23",
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
        atomic_write_json(output_dir / "metadata.json", metadata)
        write_dimacs(output_dir / "instance.cnf", variables.count, clauses)
        return metadata

    started = time.monotonic()
    outcome = "NO_RESULT_WITHIN_BUDGET"
    solver = Solver(
        name=solver_name,
        bootstrap_with=clauses,
        use_timer=True,
        with_proof=True,
    )
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
                break
            timer = Timer(remaining, solver.interrupt)
            timer.start()
            try:
                solved = solver.solve_limited(expect_interrupt=True)
            finally:
                timer.cancel()
                solver.clear_interrupt()
            if solved is None:
                metadata["detail"] = "UNKNOWN_TIMEOUT"
                break
            if not solved:
                # No certified status without an independently checked proof.
                metadata["detail"] = "UNSAT_WITHOUT_CHECKED_CERTIFICATE"
                try:
                    proof = solver.get_proof()
                except (AttributeError, NotImplementedError):
                    proof = None
                if proof:
                    (output_dir / "solver.proof").write_text(
                        "\n".join(proof) + "\n", encoding="ascii"
                    )
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
            clauses.append(clause)
            solver.add_clause(clause)
            learned.append(record)
            with learned_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")
    finally:
        solver.delete()
    cnf_hash = write_dimacs(output_dir / "instance.cnf", variables.count, clauses)
    metadata.update(
        {
            "status": outcome,
            "solver": solver_name,
            "pysat_version": pysat_version,
            "seed_applied": seed_applied,
            "iterations": locals().get("iterations", 0),
            "learned_clauses": len(learned),
            "cnf_sha256": cnf_hash,
            "elapsed_seconds": time.monotonic() - started,
            "proof_checked": False,
        }
    )
    atomic_write_json(output_dir / "metadata.json", metadata)
    return metadata
