#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA="${CONDA_EXE:-/home/whk/miniconda3/bin/conda}"
CONFIGS=(
    examples/k210-rtthread/project.json
    examples/k210-zephyr/project.json
    examples/stm32f103-rtthread/project.json
    examples/stm32f103-zephyr/project.json
    examples/psoc-e84-rtthread/project.json
    examples/psoc-e84-zephyr/project.json
)

cd "$ROOT"
for config in "${CONFIGS[@]}"; do
    printf '\n===== %s =====\n' "$config"
    "$CONDA" run --no-capture-output -n AIoT-v1.0 env \
        -u CFLAGS -u CXXFLAGS -u CPPFLAGS -u LDFLAGS \
        python -m bspforge.cli pipeline --config "$config" "$@"
done
