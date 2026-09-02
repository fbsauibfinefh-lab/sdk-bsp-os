#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_SOURCE="${BSPFORGE_K210_SDK:-/mnt/d/Wuhk/AIOT/k210sdk/kendryte-standalone-sdk}"
RTTHREAD_SOURCE="${BSPFORGE_RTTHREAD:-/mnt/d/Wuhk/RTT/rt-thread}"
STM32_SOURCE="${BSPFORGE_STM32_SDK:-/home/whk/RTT-porting/STM32CubeF1}"
PSOC_SOURCE="${BSPFORGE_PSOC_SDK:-/home/whk/RTT-porting/sdk-bsp-psoc_e84-edgi-talk}"
ZEPHYR_SOURCE="${BSPFORGE_ZEPHYR:-/home/whk/RTT-porting/zephyr}"

require_dir() {
    if [[ ! -d "$1" ]]; then
        printf 'Required directory is missing: %s\n' "$1" >&2
        exit 2
    fi
}

link_input() {
    local source="$1"
    local destination="$2"
    mkdir -p "$(dirname "$destination")"
    if [[ -L "$destination" ]]; then
        ln -sfn "$source" "$destination"
    elif [[ -e "$destination" ]]; then
        printf 'Keeping existing input: %s\n' "$destination"
    else
        ln -s "$source" "$destination"
    fi
}

require_dir "$SDK_SOURCE"
require_dir "$RTTHREAD_SOURCE"
require_dir "$STM32_SOURCE/Drivers"
require_dir "$PSOC_SOURCE/libraries"
require_dir "$PSOC_SOURCE/rt-thread"
require_dir "$ZEPHYR_SOURCE"
link_input "$SDK_SOURCE" "$ROOT/sdk/k210/source"
link_input "$STM32_SOURCE" "$ROOT/sdk/stm32f103/source"
link_input "$PSOC_SOURCE/libraries" "$ROOT/sdk/psoc_e84-edgi-talk/source"
link_input "$RTTHREAD_SOURCE" "$ROOT/third_party/rt-thread"
link_input "$PSOC_SOURCE" "$ROOT/third_party/psoc-e84-sdk"
link_input "$ZEPHYR_SOURCE" "$ROOT/third_party/zephyr"

printf 'K210 SDK:      %s\n' "$(readlink -f "$ROOT/sdk/k210/source")"
printf 'STM32F103 SDK: %s\n' "$(readlink -f "$ROOT/sdk/stm32f103/source")"
printf 'PSoC E84 SDK:  %s\n' "$(readlink -f "$ROOT/sdk/psoc_e84-edgi-talk/source")"
printf 'RT-Thread:     %s\n' "$(readlink -f "$ROOT/third_party/rt-thread")"
printf 'Zephyr:        %s\n' "$(readlink -f "$ROOT/third_party/zephyr")"
