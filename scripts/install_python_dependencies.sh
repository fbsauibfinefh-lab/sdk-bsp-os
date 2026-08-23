#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA="${CONDA_EXE:-/home/whk/miniconda3/bin/conda}"

cd "$ROOT"
"$CONDA" run --no-capture-output -n AIoT-v1.0 python -m pip install -e .
"$CONDA" run --no-capture-output -n AIoT-v1.0 python -m pip install \
    west cmake ninja scons cryptography cbor2

if [[ -f third_party/zephyr/scripts/requirements.txt ]]; then
    "$CONDA" run --no-capture-output -n AIoT-v1.0 python -m pip install \
        -r third_party/zephyr/scripts/requirements.txt
fi
