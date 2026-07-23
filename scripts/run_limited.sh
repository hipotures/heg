#!/usr/bin/env bash
set -euo pipefail

MEMORY_HIGH="${SGLAB_MEMORY_HIGH:-150G}"
MEMORY_MAX="${SGLAB_MEMORY_MAX:-168G}"
CPU_QUOTA="${SGLAB_CPU_QUOTA:-1400%}"

if command -v systemd-run >/dev/null 2>&1; then
  exec systemd-run --user --scope \
    -p "MemoryHigh=${MEMORY_HIGH}" \
    -p "MemoryMax=${MEMORY_MAX}" \
    -p "TasksMax=512" \
    -p "CPUQuota=${CPU_QUOTA}" \
    "$@"
fi

echo "warning: systemd-run unavailable; running without cgroup limits" >&2
exec "$@"
