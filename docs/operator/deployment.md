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

The repository includes a user-service template and a launcher that keep
machine-specific options out of `ExecStart`:

```bash
install -Dm755 scripts/run_dashboard_service.sh \
  ~/.local/libexec/sglab/run-dashboard-service
install -Dm644 deploy/systemd/sglab-graph-dashboard.service \
  ~/.config/systemd/user/sglab-graph-dashboard.service
install -Dm600 deploy/systemd/dashboard.env.example \
  ~/.config/sglab/dashboard.env
```

Edit `~/.config/sglab/dashboard.env`. Set absolute repository and workspace
paths, host, port, Python executable, and the path to a separate mode-600
token file. The environment file contains deployment options, not the token.

Enable or restart the service:

```bash
systemctl --user daemon-reload
systemctl --user enable --now sglab-graph-dashboard.service
systemctl --user restart sglab-graph-dashboard.service
systemctl --user status sglab-graph-dashboard.service
```

Changing an option requires only editing `dashboard.env` and restarting the
service. Restarting the dashboard does not Resume a campaign or change its
orchestration mode.

## Health checks

```bash
make doctor
sglab research-campaign status --workspace <workspace>
sqlite3 <workspace>/results.sqlite3 'PRAGMA integrity_check;'
```

Use dashboard/API health only as an operational signal, not as a mathematical
verification.
