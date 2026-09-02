#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from bspforge.code_effect_encoder import MODEL_CODE_REVISION, MODEL_ID, MODEL_REVISION


def main() -> int:
    parser = argparse.ArgumentParser(description="下载并校验固定版本的冻结代码编码器")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    from huggingface_hub import snapshot_download
    from transformers import AutoModel, AutoTokenizer

    args.output.parent.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=MODEL_ID,
        revision=MODEL_REVISION,
        local_dir=args.output,
        ignore_patterns=["*.onnx", "*.gguf", "*.h5", "*.msgpack"],
    )
    AutoTokenizer.from_pretrained(args.output)
    model = AutoModel.from_pretrained(
        args.output,
        trust_remote_code=True,
        code_revision=MODEL_CODE_REVISION,
    )
    print({
        "model": MODEL_ID,
        "revision": MODEL_REVISION,
        "code_revision": MODEL_CODE_REVISION,
        "path": str(args.output.resolve()),
        "dimension": int(model.config.hidden_size),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
