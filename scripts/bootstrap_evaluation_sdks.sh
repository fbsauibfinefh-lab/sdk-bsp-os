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
clone_pinned mspm0-sdk https://github.com/TexasInstruments/mspm0-sdk.git 20807db79aa17b49f87ab8ec87f6b6d63ee2cb32
clone_pinned simplelink-lowpower-f2-sdk https://github.com/TexasInstruments/simplelink-lowpower-f2-sdk.git 3615ad5d3f4f271258d18a2f5ce1785064ff9a58
clone_pinned renesas-fsp https://github.com/renesas/fsp.git a409855a274402f69360a725656944e17929d1d9
clone_pinned microchip-csp https://github.com/Microchip-MPLAB-Harmony/csp.git 5499789708c5c91c4908c7dc74d5ea131cc9ebb1
clone_pinned analogdevices-no-os https://github.com/analogdevicesinc/no-OS.git c690a3744f081ade785f7de6e25adfa3e97b5dc9
clone_pinned sony-spresense https://github.com/sonydevworld/spresense.git 7fd61b2c03f06a4ff0302b84c755e58c338788b2
clone_pinned sifli-sdk https://github.com/OpenSiFli/SiFli-SDK.git 2de33db1a96952d4f7fa6d8a967d20b0c8eea555
clone_pinned bouffalo-sdk https://github.com/bouffalolab/bouffalo_sdk.git 5cd17516dfe8d9813e79008aeb29c3f930797804
clone_pinned wch-ch32v307 https://github.com/openwch/ch32v307.git 69a2eec903b4f919fcb73d1ab6c10c690780e4d1
clone_pinned nuclei-sdk https://github.com/Nuclei-Software/nuclei-sdk.git c5d7fda3b7dd487c92d00d082b3166ff69ec3343
clone_pinned libopencm3 https://github.com/libopencm3/libopencm3.git 2da12dc96e0b9e42a3332348dd9b02a0a17981f8
clone_pinned mbed-os https://github.com/ARMmbed/mbed-os.git d723bf9e55415433e108124ee6d36337feddf1b8
clone_pinned arduino-renesas https://github.com/arduino/ArduinoCore-renesas.git 424e86eff92d37f72123c2b641dd8bbf06a38b47
clone_pinned telink-hal https://github.com/zephyrproject-rtos/hal_telink.git 4226c7fc17d5a34e557d026d428fc766191a0800
clone_pinned alif-cmsis-dfp https://github.com/alifsemi/alif_ensemble-cmsis-dfp.git 908f59cbd1fa9031570f8cd8aee72348415f7984
clone_pinned silabs-hal https://github.com/zephyrproject-rtos/hal_silabs.git 28eb6670caf3486321a033c7f08687867a7ef4f4
clone_pinned hpm-sdk https://github.com/hpmicro/hpm_sdk.git 88b01b43900d8c30844a1e5cdd3f3b7aff6db40e
clone_pinned nuvoton-hal https://github.com/zephyrproject-rtos/hal_nuvoton.git 0f411a85da7d17a612d54450f608f4d30cdb971f

printf 'Evaluation SDK root: %s\n' "$ROOT"
