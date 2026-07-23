#!/usr/bin/env bash
set -euo pipefail

sudo apt update
sudo apt install -y \
  build-essential cmake ninja-build git curl pkg-config \
  python3 python3-venv python3-dev nauty

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

echo "Core toolchain installed. Optional SAT/SMS/Glasgow tools are documented in docs/12_LINUX_TOOLCHAIN.md."
