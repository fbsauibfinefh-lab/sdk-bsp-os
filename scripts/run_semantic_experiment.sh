#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA="${CONDA_EXE:-/home/whk/miniconda3/bin/conda}"

cd "$ROOT"
"$CONDA" run --no-capture-output -n AIoT-v1.0 python scripts/ingest_semantic_corpus.py
"$CONDA" run --no-capture-output -n AIoT-v1.0 python scripts/build_semantic_dataset.py
"$CONDA" run --no-capture-output -n AIoT-v1.0 python scripts/evaluate_ranker_cv.py \
    --dataset experiments/generated/semantic-ranking-dataset.json \
    --output experiments/generated/semantic-ranking-cv.json
"$CONDA" run --no-capture-output -n AIoT-v1.0 python scripts/train_ranker.py \
    --dataset experiments/generated/semantic-ranking-dataset.json \
    --output models/semantic-ranker.txt
