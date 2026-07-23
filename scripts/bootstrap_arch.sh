#!/usr/bin/env bash
set -euo pipefail

sudo pacman -S --needed \
  base-devel cmake ninja git curl pkgconf python nauty

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

echo "Core toolchain installed. Optional SAT/SMS/Glasgow tools are documented in docs/12_LINUX_TOOLCHAIN.md."
