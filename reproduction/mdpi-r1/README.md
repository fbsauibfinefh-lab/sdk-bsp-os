# BSPForge 第一次返修复现入口

此目录对应2026年11月18日发布的论文返修代码。正式方法保持原83维来源OOF模型与91维部署模型，使用完整性复核后的H03评价；不包含11月17日探索重训模型，也不包含多维特征重设计分支。

## 公开内容与数据获取

公开仓库包括六模块实现、原冻结模型与运行包、三板六配置、五个补充SDK双OS的绑定及测试程序、指标审计脚本、SDK固定版本和哈希、特征列顺序与复现说明。

新版H03逐查询评价文件、完整运行记录、工程师原始表格与内部材料按论文Data Availability声明向通讯作者获取。本次不新增公开这些文件。旧提交中已有的H03/H02及实验JSON是历史快照，并非当前完整性复核后的评价入口。第三方SDK、RTOS、编译器和预训练编码器需从其原来源取得，适用各自许可证。

## 本文采用的冻结范围

| 范围 | 查询/配置 | 当前口径 |
| --- | --- | --- |
| 来源SDK | 20 SDK、18来源簇、284查询 | 按来源分组五折OOF，83维 |
| 实板SDK | K210、PSoC E84、STM32F103，55适用查询 | 均未参与训练，91维；实板共6配置 |
| 补充SDK | MAX32650、STM32F4、Stellaris、ASF3、nRF5，91适用查询 | 均未参与训练，双OS共10配置 |
| 语义消融 | 完整方法及四个视图移除条件 | 对同一补充H03重评，指标定义不变 |
| 三组件构建对照 | 6配置乘4条件，共24次 | 完整6/6，其余各4/6最终编译通过 |

补充SDK按19项操作登记，共95项，91项存在本研究范围内稳定单一入口。两OS合计182项适用记录，168通过、14失败；100/100启动。逐轮严格组合断言为1670/1820，与包含原子周期证据的168/182不是同一分母，分开保留。原第一组探索SDK不计入本文当前五SDK汇总。

完整性复核后的主指标：

| 队列 | P@1 | Recall@5 | Hit@5 | MAP | nDCG@10 |
| --- | --- | --- | --- | --- | --- |
| 来源 | 0.908451 | 0.708853 | 0.992958 | 0.812972 | 0.854169 |
| 实板SDK | 0.945455 | 0.653257 | 1.000000 | 0.705509 | 0.787382 |
| 五补充SDK | 0.736264 | 0.810845 | 0.956044 | 0.720225 | 0.783233 |

`expected-metrics.json`保存各阈值、视图和基线的机器可读期望值；`expected-integration-results.json`保存仿真配置、固件哈希、构建和工程用时汇总。工程师原件仍在作者存档，统计以最新论文与作者2026年11月17日确认口径为准。

## 环境与目录

论文实验主机为AMD Ryzen 5 5600G（6核12线程），Windows物理内存约15.36 GiB，WSL可见约7.4 GiB；WSL Ubuntu 22.04、Python 3.12.13、Renode 1.17.0、ARM GCC 14.2.1。时间受主机、线程、缓存和并发负载影响。环境版本与来源以 `environment.json`、根目录 `environment.yml`、`toolchains/manifest.json`为入口。

建议使用相邻布局，工程名可以不同：

```text
RTT-porting/
  bspforge/                 # 本仓库
  zephyr/                   # 按environment.json固定版本准备，含west模块
  evaluation-sdks/          # 固定原始SDK仓库
  models/                  # Jina预训练权重，不纳入Git
  tools/renode-1.17.0/      # Renode安装目录
```

仓库内 `sdk/<名称>/source`、`third_party/rt-thread`、`third_party/zephyr` 和 `toolchains/` 为本地依赖。RT-Thread目标配置、Zephyr west依赖和CMSIS模块也需准备。第三方版本、下载地址和工具链哈希在清单中；已有本地环境可复用，不要覆盖自己的SDK副本。

```bash
conda create -n AIoT-v1.0 python=3.12
conda activate AIoT-v1.0
python -m pip install -e '.[dev,retrieval]'
python -m pip install lightgbm west cmake ninja scons pyserial
export PYTHONPATH="$PWD:$PWD/scripts"
```

当前语法解析依赖固定为tree-sitter 0.25.2兼容范围（`<0.26`），避免0.26版Point对象问题；`pyproject.toml`已声明上限。源码动作保护复用 `bspforge/source_syntax.py` 的定位工具，不带入新排序方案。

编码器权重与旧缓存的重建入口是 `cache_pretrained_code_embeddings.py` 和 `cache_multiview_effect_embeddings.py`。MiniLM、Jina的版本及本地权重摘要见环境清单；生成排序表示需要先取得这些依赖，已有嵌入时无需再运行编码器。

## 一 直接检查公开代码

下面的测试使用合成SDK和模拟传输，不需要连接实板，也不冒充本轮重新运行固件。

```bash
python scripts/verify_revision_publication.py
python -m pytest -q tests/test_pipeline_modules.py tests/test_revision_r1.py tests/test_revision_publication.py
```

## 二 重算论文指标

取得作者提供的 `H03-evaluation-records-20261117.json`，在本仓库根目录执行：

```bash
python reproduction/mdpi-r1/audit_h03_evaluation.py \
  --records /path/to/H03-evaluation-records-20261117.json \
  --output /path/to/H03-verified-metrics.json
python scripts/verify_revision_publication.py \
  --metrics /path/to/H03-verified-metrics.json
```

这只重算固定排序，不训练、不烧录。τ=1时等级1/2/3相关；τ=2与3保持同一排序，仅改变相关集合。没有相关项的查询按既有规则排除并报告数量。P@1、Recall@5、Hit@5、MAP、二值nDCG@10沿用原公式。仿真继续使用源文件定位的候选身份。各方法均使用同一当前H03，不把补标带来的评价变化解释为模型训练增益。

`paired-source-intervals.json`保留当前来源聚类的成对消融区间。原始逐查询记录需随作者材料取得；只有Top-5的历史基线只报告可重算的头部检索指标，不能据它补造完整MAP。

## 三 三板六配置

准备三款SDK、两RTOS和工具链后，以 `examples/<板卡>-<OS>/project.json` 为入口；配置中的输入、后端和工具链路径应对应本机。示例：

```bash
python -m bspforge.cli pipeline --config examples/k210-rtthread/project.json
python -m bspforge.cli pipeline --config examples/k210-zephyr/project.json
```

其余入口为 `psoc-e84-rtthread`、`psoc-e84-zephyr`、`stm32f103-rtthread`、`stm32f103-zephyr`。输出在 `workspace/runs/<run-id>`：IR、候选和规范绑定、闭包、逐轮诊断、生成路径、ELF/BIN校验及报告。实板接线和协议见 `docs/hardware-validation.md` 及三板各自的冻结验证文档。

复做三组件消融：

```bash
python scripts/evaluate_revision_integration_ablations.py --help
python scripts/run_revision_fault_cases.py --help
```

按帮助指定独立工作目录，避免覆盖已有验收记录。完整条件、去兼容性、目标组件全量和去反馈共24次构建；受控诊断故障案例与正常生成构建分别报告。

## 四 五SDK双OS

先下载固定源码并准备输入与IR；这一步不读取真值。`--download`只为缺失目录创建仓库，发现已有目录提交不同会停止，不会重置它。

```bash
python scripts/bootstrap_revision_r1.py --download
python scripts/bootstrap_revision_r1.py --prepare
python scripts/bootstrap_revision_r1.py --verify-inputs
python scripts/rank_revision_sdk_matrix.py --experiment-root experiments/revision-r1-replacements
python scripts/rank_revision_sdk_matrix.py --experiment-root experiments/revision-r1-expanded
```

排名程序先构造无标签候选，再计算字段、代码和硬件效果表示，使用已冻结91维模型打分，每操作保留128候选。模型摘要取自公开契约，不需要取得参考标签才能推断。之后执行十个配置，例如：

```bash
python scripts/run_replacement_sdk_matrix.py \
  --experiment-root experiments/revision-r1-replacements \
  --only max32650-msdk --os rtthread --rounds 10 --contract-guards
python scripts/run_replacement_sdk_matrix.py \
  --experiment-root experiments/revision-r1-replacements \
  --only max32650-msdk --os zephyr --rounds 10 --contract-guards
```

同批再运行STM32F4；`revision-r1-expanded`下按同样方式运行Stellaris、ASF3和nRF5的两个OS。Stellaris使用QEMU Cortex-M3，其余使用Renode平台。运行结果保存至 `experiments/<批次>/<SDK>/<OS>/results.json`；该目录还保存 `compiler-feedback.json`、`build-result.json`、逐轮原始字节和哈希固定的ELF。函数选择见SDK目录的 `typed-selection.json`，生成工程在 `workspace/<批次>/<SDK>/<OS>/`。

SDK ABI、实例、时钟、引脚和OS入口是显式适配配置；不将它们称作完全无需工程配置的新板迁移。选择器从模型序列中检查公开ABI与活动声明，通用契约保护排除已证明的动作冲突。OS已有IRQ/启动实现与生成SDK路径分别记录归属，不以已有驱动的存在否定合法绑定，也不将其改称全部是工具新生成的实现。

本轮最终十配置没有触发自动编译修复；运行反馈下完善的通用规则是开发更新。原六配置正常构建的自动反馈4/6到6/6，以及受控缺头文件/唯一符号修复，分别提供编译反馈机制证据。保留14项最终失败，不把它们从适用分母删除。

## 关键文件导航

| 文件/目录 | 作用 |
| --- | --- |
| `bspforge/sdk_ingestor`、`bspforge/ir_store` | 混合解析与版本化实体 |
| `bspforge/semantic_resolver`、`bspforge/binding_planner.py` | 无标签候选排序和规范操作绑定 |
| `bspforge/closure_solver`、`bspforge/build_diagnoser` | 目标兼容闭包和有界诊断修复 |
| `bspforge/binding_contract_guard.py` | 跨SDK共用的源码动作冲突保护 |
| `bspforge/os_backend`、`ports/replacement-simulation` | 原生设备代码与运行断言 |
| `scripts/replacement_sdk_binding.py`、`expanded_sdk_binding.py` | 五SDK显式ABI、实例和薄适配配置 |
| `simulation-sdks.json`、`sources/`、`config/` | 固定提交、输入哈希和事前操作范围 |
| `feature-schema-83.csv`、`model-contract.json` | 83/91维输入及部署模型摘要 |
| `audit_h03_evaluation.py`、`expected-metrics.json` | 当前评价入口与核对值 |
| `files.sha256.json` | 本次公开文件路径、大小和SHA-256 |

旧开发文档和历史结果保留追溯功能；本文当前口径以本目录为准。Git标签固定代码版本，提交记录本身不是功能或实验有效性的替代证据。
