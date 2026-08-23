#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CACHE="$ROOT/toolchains/.cache"
mkdir -p "$CACHE" "$ROOT/toolchains"

download() {
    local url="$1"
    local archive="$2"
    local sha256="$3"
    if [[ ! -f "$archive" ]] || ! printf '%s  %s\n' "$sha256" "$archive" | sha256sum -c -; then
        curl -fL --retry 3 "$url" -o "$archive.download"
        printf '%s  %s\n' "$sha256" "$archive.download" | sha256sum -c -
        mv "$archive.download" "$archive"
    fi
}

install_tar() {
    local archive="$1"
    local destination="$2"
    local compiler="$3"
    if [[ -x "$destination/bin/$compiler" ]]; then
        return
    fi
    if [[ -e "$destination" ]]; then
        printf '目标目录存在但工具链不完整，请确认后移除：%s\n' "$destination" >&2
        exit 2
    fi
    local temporary="$destination.installing"
    if [[ -e "$temporary" ]]; then
        printf '临时安装目录已存在，请确认后移除：%s\n' "$temporary" >&2
        exit 2
    fi
    mkdir -p "$temporary"
    tar -xf "$archive" -C "$temporary" --strip-components=1
    mv "$temporary" "$destination"
}

OLD_RISCV_ARCHIVE="$CACHE/xpack-riscv-none-embed-gcc-10.2.0-1.2-linux-x64.tar.gz"
download \
  'https://github.com/xpack-dev-tools/riscv-none-embed-gcc-xpack/releases/download/v10.2.0-1.2/xpack-riscv-none-embed-gcc-10.2.0-1.2-linux-x64.tar.gz' \
  "$OLD_RISCV_ARCHIVE" \
  'd72bdcd1eee41dc5a208a8a03976b70d014510deb5890c9e8738e804ba23f985'
install_tar "$OLD_RISCV_ARCHIVE" "$ROOT/toolchains/riscv-none-embed-gcc-10.2.0" 'riscv-none-embed-gcc'

RISCV_ARCHIVE="$CACHE/xpack-riscv-none-elf-gcc-14.2.0-3-linux-x64.tar.gz"
download \
  'https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases/download/v14.2.0-3/xpack-riscv-none-elf-gcc-14.2.0-3-linux-x64.tar.gz' \
  "$RISCV_ARCHIVE" \
  'f574415b63f12b09bdd3475223ab492a465d23810646c90c13a4c3b676c83503'
install_tar "$RISCV_ARCHIVE" "$ROOT/toolchains/xpack-riscv-none-elf-gcc-14.2.0-3" 'riscv-none-elf-gcc'

ARM_ARCHIVE="$CACHE/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi.tar.xz"
download \
  'https://developer.arm.com/-/media/Files/downloads/gnu/14.2.rel1/binrel/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi.tar.xz' \
  "$ARM_ARCHIVE" \
  '62a63b981fe391a9cbad7ef51b17e49aeaa3e7b0d029b36ca1e9c3b2a9b78823'
install_tar "$ARM_ARCHIVE" "$ROOT/toolchains/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi" 'arm-none-eabi-gcc'

"$ROOT/toolchains/riscv-none-embed-gcc-10.2.0/bin/riscv-none-embed-gcc" --version | head -n 1
"$ROOT/toolchains/xpack-riscv-none-elf-gcc-14.2.0-3/bin/riscv-none-elf-gcc" --version | head -n 1
"$ROOT/toolchains/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi/bin/arm-none-eabi-gcc" --version | head -n 1
