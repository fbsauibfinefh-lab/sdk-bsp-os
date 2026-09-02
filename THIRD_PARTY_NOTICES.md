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
