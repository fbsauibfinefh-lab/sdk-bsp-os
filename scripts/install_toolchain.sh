#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="10.2.0-1.2"
ARCHIVE="xpack-riscv-none-embed-gcc-${VERSION}-linux-x64.tar.gz"
URL="https://github.com/xpack-dev-tools/riscv-none-embed-gcc-xpack/releases/download/v${VERSION}/${ARCHIVE}"
CACHE="$ROOT/toolchains/.cache"
DESTINATION="$ROOT/toolchains/riscv-none-embed-gcc-10.2.0"

mkdir -p "$CACHE" "$ROOT/toolchains"
if [[ ! -x "$DESTINATION/bin/riscv-none-embed-gcc" ]]; then
    if [[ ! -f "$CACHE/$ARCHIVE" ]]; then
        wget -c "$URL" -O "$CACHE/$ARCHIVE"
    fi
    temporary="$ROOT/toolchains/.extract-${VERSION}"
    rm -rf "$temporary"
    mkdir -p "$temporary"
    tar -xzf "$CACHE/$ARCHIVE" -C "$temporary" --strip-components=1
    rm -rf "$DESTINATION"
    mv "$temporary" "$DESTINATION"
fi

"$DESTINATION/bin/riscv-none-embed-gcc" --version | head -n 1
printf 'Installed: %s\n' "$DESTINATION"

