#!/usr/bin/env bash
set -euo pipefail

: "${SGLAB_DASHBOARD_REPOSITORY:?set SGLAB_DASHBOARD_REPOSITORY}"
: "${SGLAB_DASHBOARD_WORKSPACE:?set SGLAB_DASHBOARD_WORKSPACE}"

dashboard_host="${SGLAB_DASHBOARD_HOST:-127.0.0.1}"
dashboard_port="${SGLAB_DASHBOARD_PORT:-8788}"
dashboard_python="${SGLAB_DASHBOARD_PYTHON:-python3}"

if [[ "${SGLAB_DASHBOARD_REPOSITORY}" != /* ]]; then
  echo "SGLAB_DASHBOARD_REPOSITORY must be an absolute path" >&2
  exit 2
fi
if [[ "${SGLAB_DASHBOARD_WORKSPACE}" != /* ]]; then
  echo "SGLAB_DASHBOARD_WORKSPACE must be an absolute path" >&2
  exit 2
fi
if [[ ! -d "${SGLAB_DASHBOARD_REPOSITORY}/src/sglab" ]]; then
  echo "SGLAB_DASHBOARD_REPOSITORY does not contain src/sglab" >&2
  exit 2
fi
if [[ ! "${dashboard_port}" =~ ^[0-9]+$ ]] \
  || (( dashboard_port < 1 || dashboard_port > 65535 )); then
  echo "SGLAB_DASHBOARD_PORT must be between 1 and 65535" >&2
  exit 2
fi

if [[ -n "${SGLAB_DASHBOARD_TOKEN_FILE:-}" ]]; then
  if [[ ! -f "${SGLAB_DASHBOARD_TOKEN_FILE}" ]] \
    || [[ -L "${SGLAB_DASHBOARD_TOKEN_FILE}" ]]; then
    echo "SGLAB_DASHBOARD_TOKEN_FILE must be a regular file" >&2
    exit 2
  fi
  SGLAB_DASHBOARD_TOKEN="$(
    < "${SGLAB_DASHBOARD_TOKEN_FILE}"
  )"
  if [[ -z "${SGLAB_DASHBOARD_TOKEN}" ]]; then
    echo "SGLAB_DASHBOARD_TOKEN_FILE is empty" >&2
    exit 2
  fi
  export SGLAB_DASHBOARD_TOKEN
fi

cd "${SGLAB_DASHBOARD_REPOSITORY}"
export PYTHONPATH="${SGLAB_DASHBOARD_REPOSITORY}/src"
exec "${dashboard_python}" -m sglab serve \
  --workspace "${SGLAB_DASHBOARD_WORKSPACE}" \
  --host "${dashboard_host}" \
  --port "${dashboard_port}"
