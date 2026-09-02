# 三块开发板外部测试真值

本目录保存 K210、STM32F103 和 PSoC E84 的外部测试真值来源与注册信息。三套 SDK 在项目 manifest 和转换结果中均固定为 `role=external-test`、`training_included=false`，不会进入 22 套 SDK 的训练或开发划分。

## 文件组织

- `source/evaluation-manifest.json`：人工真值提供方的固定版本及文件索引。
- `source/<sdk_id>/truth-audit-v1-final.json`：包含 0/1/2/3 级候选、源码位置、签名和判定依据的富审计真值。
- `source/validation.json`：人工真值的上游结构、证据、宏边界和训练隔离校验。
- `source/equivalence-adjudication-20260902.json`：冻结模型首次复测后，对预测冲突进行源码复核得到的三项等价 API 补充；该文件与原始 H03 分开保存。
- `registry.json`：转换产物、源文件哈希和汇总统计。
- 上层目录中的 `k210-operations.json`、`stm32f103-operations.json`、`psoc-e84-operations.json`：项目评测程序直接读取的操作真值。

转换输出保留完整分级：`symbols`、`alternative_symbols`、`related_symbols`、`irrelevant_symbols` 分别对应 3、2、1、0 级。`no_public_api` 查询组保留状态，不会被误当作存在正例的普通查询组。

## 重新转换

```bash
cd /home/whk/RTT-porting/bspforge
conda run --no-capture-output -n AIoT-v1.0 \
  python scripts/convert_external_board_truth.py
```

该命令只校验并转换外部测试真值，不构建训练数据集，也不训练模型。默认应用等价仲裁补丁并生成 `external-board-h03-equivalence-r1`；删除或通过不存在的 `--adjudication` 路径运行时可恢复未仲裁的原始 H03 转换口径。

## 数据隔离

训练真值注册表 `training_policy.truth_sets` 只包含 22 套训练 SDK 的真值。三块板卡通过各自 manifest 项的 `ground_truth` 字段加载，始终只作为 `external-test` 查询组，不参与模型训练或选参。由于三板结果已经用于 v2.5 错误分析和可行性保护开发，它们在后续论文中应称为“外部开发诊断集”，不能再称为方法冻结后的完全未见确认集；正式确认需增加新的未见 SDK。源码修订号同时写入项目 manifest 和真值文件，加载时不一致会立即报错。
