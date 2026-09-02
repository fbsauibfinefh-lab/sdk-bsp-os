#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA="${CONDA_EXE:-/home/whk/miniconda3/bin/conda}"
ROUNDS="${BSPFORGE_SIM_ROUNDS:-20}"
EXECUTABLE="$ROOT/workspace/generated/simulation-zephyr-native/build/zephyr/zephyr.exe"

cd "$ROOT"
"$CONDA" run --no-capture-output -n AIoT-v1.0 env \
    -u CFLAGS -u CXXFLAGS -u CPPFLAGS -u LDFLAGS \
    python -m bspforge.cli pipeline \
    --config examples/simulation-zephyr-native/project.json
"$CONDA" run --no-capture-output -n AIoT-v1.0 bspforge-hwtest \
    --command "$EXECUTABLE" \
    --board native_sim \
    --rtos zephyr \
    --timeout 2 \
    --rounds "$ROUNDS" \
    --output experiments/generated/zephyr-native-simulation.json
