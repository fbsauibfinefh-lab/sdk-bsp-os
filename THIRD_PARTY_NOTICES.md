# 第三方组件说明

BSPForge 自有代码使用 MIT 许可证。以下第三方组件不属于 BSPForge，其许可证和版权归原作者所有。本文档用于工程追踪，实际分发时应以所安装版本中的许可证文件为准。

| 组件 | 用途 | 许可 | 分发方式 |
| --- | --- | --- | --- |
| sentence-transformers/all-MiniLM-L6-v2 | 操作与 SDK IR 语义编码 | Apache-2.0 | 记录模型名和提交，不在仓库复制基础模型 |
| jinaai/jina-embeddings-v2-base-code | C/C++ SDK 函数体与能力操作的冻结代码语义编码 | Apache-2.0 | 固定模型和远程代码提交，不在仓库复制约 312 MB 权重 |
| Sentence Transformers / Transformers | 模型加载、训练与推理 | Apache-2.0 | Python 可选依赖 |
| PyTorch | 张量计算 | BSD-style | Python 间接依赖 |
| LightGBM | LambdaMART 排序基线 | MIT | Python 可选依赖 |
| scikit-learn | 评测辅助 | BSD-3-Clause | Python 可选依赖 |
| NumPy | 数值计算 | BSD-3-Clause | Python 可选依赖 |
| tree-sitter / tree-sitter-c | C/C++ 混合语法前端 | MIT | Python 可选依赖 |
| pyserial | 实板串口回归 | BSD-3-Clause | Python 可选依赖 |
| RT-Thread | 目标 RTOS | Apache-2.0 | 本地外部源码，不纳入仓库 |
| Zephyr | 目标 RTOS | Apache-2.0；子模块可能不同 | 本地外部源码，不纳入仓库 |
| Kendryte standalone SDK | K210 输入 SDK | Apache-2.0；第三方目录可能不同 | 本地外部源码，不纳入仓库 |
| STM32CubeF1 | STM32F103 输入 SDK | 组件级 Apache-2.0、BSD-3-Clause、ST SLA0044 等 | 本地外部源码，不纳入仓库 |
| PSoC E84 SDK | PSoC 输入 SDK | 多组件独立许可，核心 device-support 为 Apache-2.0 | 本地外部源码，不纳入仓库 |

生成工程可能从输入 SDK 的构建闭包物化源文件。此类本地生成物不会自动变为 MIT 许可；对外发布前必须保留上游版权/许可证，并逐文件检查 SPDX 和厂商条款。工具链二进制及其运行库同样不由本仓库重新分发。

模型与主要方法来源见 `docs/related-work-citation-and-ip-risk-v0.9.md`。

## 返修追加SDK与仿真资源

本文当前正式五SDK队列、固定提交和逐文件摘要的公开入口为 `reproduction/mdpi-r1/simulation-sdks.json` 与 `reproduction/mdpi-r1/sources/`。Stellaris DriverLib、ASF3 SAM4S和nRF5 SDK的代码及CMSIS组件继续按原供应商和各文件许可证使用；本仓库只提供自身适配与测试代码、下载信息和哈希，不复制这些完整SDK。下述本地 `experiments/` 路径为作者归档位置，不表示该数据目录已随Git公开。

MAX32650 MSDK来自Analog Devices公开仓库，固定提交及逐文件哈希见 `experiments/revision-r1-replacements/max32650-msdk/source-manifest.json`。已使用源文件保留Apache-2.0版权头，构建辅助文件来自同一固定仓库。Zephyr依赖的hal_adi为独立上游组件，不与输入SDK的代码归属合并。

STM32F4 StdPeriph 1.8来自ST库的公开镜像，按源文件所附MCD-ST Liberty等供应商条款及CMSIS原许可使用，不归为BSPForge的MIT代码。原始资源位于 `../evaluation-sdks/revision-stm32f4-stdperiph`，CMSIS协议保存在该仓库Libraries/CMSIS。实验副本保留版权头和固定提交；完整第三方SDK不作为本项目源码重新发布。

Renode 1.17.0及其平台描述保存在工程同级tools目录，使用发布包及模型各自附带的许可证。原五SDK的来源、固定提交与文件哈希见 `experiments/revision-r1-five-sdk/manifest.json`。本地结果包中的生成绑定、上游源文件、工具与固件分别按其原许可解释；项目许可证不替代上游条款。
