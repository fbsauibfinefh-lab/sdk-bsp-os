#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA="${CONDA_EXE:-/home/whk/miniconda3/bin/conda}"

cd "$ROOT"
"$CONDA" run -n AIoT-v1.0 python -m pip install -e .
"$CONDA" run -n AIoT-v1.0 bspforge pipeline \
    --config examples/k210-rtthread/project.json "$@"

