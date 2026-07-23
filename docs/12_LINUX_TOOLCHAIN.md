# Linux Toolchain

## Core environment

- Python 3.12+
- `uv` recommended, regular `venv` supported
- GCC or Clang with C++17
- CMake and Ninja
- Git
- cgroup v2 / systemd where available

## Ubuntu / Debian

Suggested packages:

```bash
sudo apt update
sudo apt install -y \
  build-essential cmake ninja-build git curl pkg-config \
  python3 python3-venv python3-dev \
  nauty
```

Package names vary by distribution release. `doctor` must report missing executables rather than assuming installation succeeded.

## Arch / Manjaro

```bash
sudo pacman -S --needed \
  base-devel cmake ninja git curl pkgconf python nauty
```

## Python

```bash
uv venv
source .venv/bin/activate
uv pip install -e .
uv pip install -e '.[sat,reference]'
```

For `python-sat`, use the package named `python-sat`, not the unrelated space-physics package named `pysat`.

## nauty / Traces

Use for:

- canonical labeling;
- graph6 tools;
- small-order isomorph-free generation.

Official site: https://pallini.di.uniroma1.it/

## PySAT and CaDiCaL

Use PySAT as the Python prototyping interface. Record the actual backend and version. Avoid solver-specific assumptions in the target plugin.

Official docs: https://pysathq.github.io/docs/html/api/solvers.html

## SAT Modulo Symmetries

Optional advanced tool for isomorph-free graph generation under constraints.

- docs: https://sat-modulo-symmetries.readthedocs.io/
- source: https://github.com/markirch/sat-modulo-symmetries

Pin a tested commit in `tools.lock.json` after installation.

## Glasgow Subgraph Solver

Optional exact subgraph-isomorphism verifier for cycle pattern graphs.

Source: https://github.com/ciaranm/glasgow-subgraph-solver

Treat loop-related proof-logging options carefully and record the exact version and flags.

## Optional tools not required in v1

- `plantri` for planar graph targets;
- `snarkhunter` for specialized cubic graph generation;
- OR-Tools CP-SAT for later structural plugins;
- Lean for formalization after a mathematical result exists.

## Codex CLI

Codex reads repository-level `AGENTS.md`. For interactive work:

```bash
codex -C /path/to/repository
```

For a scripted pass:

```bash
codex exec -C /path/to/repository "$(cat CODEX_PROMPT.md)"
```

Official references:

- https://developers.openai.com/codex/cli
- https://developers.openai.com/codex/agent-configuration/agents-md
- https://developers.openai.com/codex/developer-commands
