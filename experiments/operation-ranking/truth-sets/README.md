# 操作级真值集合

本目录保存格式一致的操作级真值，包括两名工程师的独立标注、一套由二者仲裁得到的 H03 真值，以及旧自动真值。转换过程不隐式合并标注，也不自动运行训练。

## 可选真值

| 真值 ID | 文件 | 来源 | 查询组 |
| --- | --- | --- | ---: |
| `human-engineer-1` | `human-engineer-1.json` | 工程师 1 源码审计 | 418 |
| `human-engineer-2` | `human-engineer-2.json` | 工程师 2 源码审计 | 418 |
| `human-adjudicated-h03` | `human-adjudicated-h03.json` | H01/H02 源码级仲裁 H03 | 418 |
| `automatic-v0.9` | `automatic-v0.9.json` | v0.9 旧自动分级弱监督数据 | 418 |

四份文件均使用 `operation-truth-set-v1`，包含 22 套训练 SDK、固定源码修订号、19 个操作，以及 3/2/1/0 级符号列表。三套板卡 SDK 不在其中。

两份输入人工审计内部都使用了 `A01`。根据项目负责人确认，转换文件分别赋予规范编号 `H01` 和 `H02`；原始 `A01` 保存在 `source_metadata_annotator_id`，源文件和 SHA-256 保存在 `source-audits/` 与各真值文件中。计算双人一致性前仍需确认两名工程师确实独立工作，并对候选并集补齐缺失评分。

H03 不是第三名标注者，而是对 H01、H02 候选并集进行固定版本源码复核后的仲裁结果。它包含 1,009 个候选，等级 0/1/2/3 数量分别为 162/259/178/410，查询组状态为 `complete` 284 个、`no_public_api` 134 个。上游验证报告已通过 22 套 SDK、418 个查询组、零外部板卡泄漏和零宏泄漏检查。共享候选上的二次加权 Kappa 为 0.7953；该值不覆盖候选并集中的单方缺失项，不能写成正式的全并集双人 Kappa。

## 重新转换

```bash
cd /home/whk/RTT-porting/bspforge
conda run --no-capture-output -n AIoT-v1.0 \
  python scripts/convert_operation_truth_sets.py
```

该命令只校验和转换真值，不生成排序数据集，也不训练模型。

## 选择真值

旧自动真值是 manifest 的默认值，用于保持既有实验口径。需要使用某位工程师的标注时显式指定：

```bash
python scripts/build_operation_dataset.py \
  --truth-set human-engineer-1 \
  --unretrievable-truth-policy skip-missing
python scripts/build_operation_dataset.py --truth-set human-engineer-2
python scripts/build_operation_dataset.py --truth-set human-adjudicated-h03
python scripts/build_operation_dataset.py --truth-set automatic-v0.9
```

注册信息和各套统计见 `registry.json`。四套真值不会被系统隐式合并。默认值仍为 `automatic-v0.9`，本次转换没有改变既有实验口径。

H01 当前有 10 个宏别名、C++ 限定名或兼容层名称不在函数候选空间。默认策略 `error` 会严格终止；只有明确指定 `skip-missing` 才会记录缺失并跳过没有可达正例的组。该策略不能替代候选并集补标和后续仲裁。

不同真值必须使用每查询组独立随机种子的新版数据生成器，保证外部候选不受前序训练组跳过情况影响。2026-08-28 的公平复跑记录见 `docs/adaptive-gate-human-truth-rerun-20260828.md`。
