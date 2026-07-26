# Deployment

## Requirements

- Linux;
- Python 3.12 or newer;
- C++17 compiler;
- local filesystem supporting normal SQLite/WAL semantics;
- enough RAM for configured lane and verifier limits;
- Codex CLI compatible with the reviewed App Server protocol for AI campaigns.

## Install

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e .
make cyclecheck
```

Optional dependencies:

```bash
uv pip install -e '.[sat,reference]'
```

## Local dashboard

```bash
sglab serve   --workspace /srv/heg/workspace/experiment-01   --host 127.0.0.1   --port 8788
```

Local binding is the default security posture.

## LAN exposure

Use LAN exposure only deliberately:

```bash
SGLAB_WEB_TOKEN='<high-entropy-token>' sglab serve   --workspace /srv/heg/workspace/experiment-01   --host 0.0.0.0   --port 8788
```

Also configure:

- firewall allowlist;
- reverse proxy/TLS where appropriate;
- network segmentation;
- bearer-token rotation.

> [!WARNING]
> Binding to `0.0.0.0` without network controls exposes campaign actions and
> scientific artifacts to the reachable network.

## Process model

- dashboard: one local HTTP process;
- campaign coordinator: one owner per workspace;
- lanes: bounded child processes;
- verification broker/jobs: bounded child process(es);
- Codex App Server: private process with isolated homes;
- comparison worker: fixed argv child owned and reaped by dashboard.

Do not run two coordinators against one workspace.

## Service supervision

The project can be placed under systemd or another supervisor, but paid or
authenticated campaign Resume must remain explicit. Do not automatically
resume model execution after host restart without a reviewed plan.

## Health checks

```bash
make doctor
sglab research-campaign status --workspace <workspace>
sqlite3 <workspace>/results.sqlite3 'PRAGMA integrity_check;'
```

Use dashboard/API health only as an operational signal, not as a mathematical
verification.
