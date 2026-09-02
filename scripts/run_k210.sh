#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA="${CONDA_EXE:-/home/whk/miniconda3/bin/conda}"

cd "$ROOT"
"$CONDA" run --no-capture-output -n AIoT-v1.0 python -m bspforge.cli pipeline \
    --config examples/k210-rtthread/project.json "$@"
