#!/usr/bin/env bash
set -euo pipefail

ROOT="${BSPFORGE_EVAL_SDK_ROOT:-/home/whk/RTT-porting/evaluation-sdks}"
mkdir -p "$ROOT"

clone_pinned() {
    local name="$1"
    local repository="$2"
    local revision="$3"
    if [[ ! -d "$ROOT/$name/.git" ]]; then
        git clone --filter=blob:none "$repository" "$ROOT/$name"
    fi
    git -C "$ROOT/$name" fetch --depth 1 origin "$revision"
    git -C "$ROOT/$name" checkout --detach "$revision"
}

clone_pinned pico-sdk https://github.com/raspberrypi/pico-sdk.git a1438dff1d38bd9c65dbd693f0e5db4b9ae91779
clone_pinned nrfx https://github.com/NordicSemiconductor/nrfx.git aa83d4df8d5f41b591f23a8555794632afb3475d
clone_pinned esp-idf https://github.com/espressif/esp-idf.git 8c19b156084a0753687347cca1f5355782893533
clone_pinned mcux-sdk https://github.com/nxp-mcuxpresso/legacy-mcux-sdk.git 0420001d787c2c7bb062a2da4c46233d9daf2737

printf 'Evaluation SDK root: %s\n' "$ROOT"
