# 方法参考文献、引用边界与知识产权风险检查

## 1. 使用说明

本文档是工程与论文写作的内部检查清单，不构成法律意见，也不能保证不存在第三方专利。它解决三个实际问题：哪些思想已有公开来源必须引用；BSPForge 的具体工作与公开方法有何区别；源码、模型、SDK 和生成物在公开时要遵守什么许可边界。

## 2. 方法来源与差异矩阵

| BSPForge 方法 | 必须引用的已有工作 | 可合理主张的本项目工作 | 不应主张 |
| --- | --- | --- | --- |
| MiniLM 小模型编码 | MiniLM、Sentence-BERT | 在 Migration IR/API 迁移任务中的输入表示、调优和完整工程验证 | 发明小型 Transformer 或句向量模型 |
| token 级 MaxSim | ColBERT、ColBERTv2 | 五类 SDK IR 字段专用查询、非空字段归一化、字段消融及与静态契约融合 | 发明 late interaction 或 MaxSim |
| LambdaMART 排序 | LambdaRank/LambdaMART | 四级迁移相关性、SDK 独立分组、面向接口契约的特征 | 发明 learning-to-rank |
| 语义代码检索 | CodeSearchNet、CodeBERT、GraphCodeBERT | 从自然语言代码检索转化为“规范化 RTOS 操作到 SDK API”的受约束排序 | 首次用预训练模型理解代码 |
| API 组合约束 | 结构化预测和约束推断相关工作 | 参数化互补、同 API 族、共享句柄/目录/HAL 层等 BSP 迁移约束 | 发明结构化预测、beam search 或整数规划 |
| 编译反馈 | CompCoder、编译错误修复相关工作 | 把构建诊断映射为稳定实体约束并反馈给迁移排序，明确不声称运行正确 | 首次使用编译器反馈；编译通过即功能正确 |
| 选择性接受 | selective prediction、conformal risk control | 面向迁移绑定的多证据置信度和开发集阈值协议 | 在未实现严格校准时声称有限样本风险保证 |

## 3. 核心参考文献

### 3.1 小模型和语义表示

1. Wang et al. **MiniLM: Deep Self-Attention Distillation for Task-Agnostic Compression of Pre-Trained Transformers.** NeurIPS 2020. [论文页](https://proceedings.neurips.cc/paper/2020/hash/3f5ee243547dee91fbd053c1c4a845aa-Abstract.html)
2. Reimers and Gurevych. **Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks.** EMNLP-IJCNLP 2019. [ACL Anthology](https://aclanthology.org/D19-1410/)
3. Feng et al. **CodeBERT: A Pre-Trained Model for Programming and Natural Languages.** Findings of EMNLP 2020. [ACL Anthology](https://aclanthology.org/2020.findings-emnlp.139/)
4. Guo et al. **GraphCodeBERT: Pre-training Code Representations with Data Flow.** ICLR 2021. [arXiv](https://arxiv.org/abs/2009.08366)
5. Husain et al. **CodeSearchNet Challenge: Evaluating the State of Semantic Code Search.** 2019. [arXiv](https://arxiv.org/abs/1909.09436)

### 3.2 迟交互与排序

6. Khattab and Zaharia. **ColBERT: Efficient and Effective Passage Search via Contextualized Late Interaction over BERT.** SIGIR 2020. [arXiv](https://arxiv.org/abs/2004.12832)
7. Santhanam et al. **ColBERTv2: Effective and Efficient Retrieval via Lightweight Late Interaction.** NAACL 2022. [ACL Anthology](https://aclanthology.org/2022.naacl-main.272/)
8. Burges, Ragno, and Le. **Learning to Rank with Non-Smooth Cost Functions.** NeurIPS 2006. [Microsoft Research](https://www.microsoft.com/en-us/research/publication/learning-to-rank-with-non-smooth-cost-functions/)
9. Burges. **From RankNet to LambdaRank to LambdaMART: An Overview.** MSR-TR-2010-82. [Microsoft Research](https://www.microsoft.com/en-us/research/publication/from-ranknet-to-lambdarank-to-lambdamart-an-overview/)
10. Sentence Transformers. **Hard Negative Mining documentation.** [官方文档](https://www.sbert.net/docs/package_reference/util/hard_negatives.html)

### 3.3 编译反馈、约束和风险控制

11. Wang et al. **Compilable Neural Code Generation with Compiler Feedback.** Findings of ACL 2022. [ACL Anthology PDF](https://aclanthology.org/2022.findings-acl.2.pdf)
12. Ahmed et al. **Compilation Error Repair: For the Student Programs, From the Student Programs.** ICSE-SEET 2018. [Microsoft Research](https://www.microsoft.com/en-us/research/publication/compilation-error-repair-student-programs-student-programs/)
13. Xu, Guo, and Wei. **Conformal Risk Control for Ordinal Classification.** UAI 2023. [PMLR](https://proceedings.mlr.press/v216/xu23a.html)
14. **Conformal Risk Control.** ICLR 2024. [OpenReview PDF](https://openreview.net/pdf?id=33XGfHLtZg)
15. **Type-Constrained Code Generation with Language Models.** PACMPL 2025. [ACM DOI](https://doi.org/10.1145/3729274)
引用纪律是只保留真正支撑方法或讨论的文献，不为凑数量加入未使用条目。正式 BibTeX 应从出版社、ACL Anthology、PMLR 或作者主页导出，不从二次博客复制。

## 4. 雷同与抄袭风险判断

### 4.1 当前代码来源

本轮新增的字段解析、MaxSim 调用、约束规则、编译反馈映射、评测和文档均为针对 BSPForge 现有 IR 数据结构独立实现，没有复制 ColBERT、CompCoder 或其他论文仓库的代码。采用公开算法思想本身不构成抄袭，但论文必须引用原始来源，并清楚区分“采用”“改造”和“提出”。

### 4.2 当前最接近的公开思想

最接近字段迟交互的是 ColBERT；最接近排序器的是 LambdaMART；最接近编译闭环的是 CompCoder 和编译错误修复；最接近自动接受控制的是 conformal/selective prediction。它们分别面向文本检索、通用排序、代码生成/修复和风险控制，没有给出“异构芯片 SDK IR 到多 RTOS 设备模型绑定”的完整问题定义、API 组合规则、构建闭包和固件验证流程。

因此，论文创新点应放在任务建模和组合方法上，而不是单个通用算法组件：

- SDK Migration IR 的字段化迁移语义表示；
- 面向规范化设备操作的字段专用迟交互；
- 结合句柄、API 族、层级和互补操作的组合约束；
- 排序、绑定、闭包、编译诊断、固件和上板验证的可追溯闭环；
- SDK 独立分组与选择性自动接受协议。

### 4.3 与已有专利的边界

用户已有专利涉及基于大语言模型的 BSP 代码生成。本工程当前核心是小型编码器辅助的 API 检索与排序、确定性约束、构建闭包和多 RTOS 后端，不以大语言模型生成 BSP 代码。论文和开源 README 中仍应避免直接复用专利说明书中的大段表述、流程图或权利要求措辞。

正式投稿及软件发布前，应由专利代理人逐项比对：论文方法步骤是否落入已提交权利要求；学校、项目出资方和发明人对代码及数据的权属；公开 Git 历史是否早于专利申请允许的公开时间。Git 提交记录可以证明演化过程，但不能自动证明专利新颖性、作者身份或无侵权。

## 5. 开源许可检查

| 资产 | 当前许可/情况 | 风险控制 |
| --- | --- | --- |
| BSPForge 自有代码 | MIT | 保留 `LICENSE` 和版权声明 |
| MiniLM / Sentence Transformers | 模型卡与项目通常标注 Apache-2.0 | 固定模型提交，保留模型名、许可和 NOTICE；发布前再次核对模型卡 |
| LightGBM | MIT | 在第三方清单中署名和附许可证 |
| Tree-sitter / tree-sitter-c | MIT | 在第三方清单中署名和附许可证 |
| RT-Thread | Apache-2.0 | 源码不纳入本仓库；分发派生 BSP 时保留许可证和 NOTICE |
| Zephyr | Apache-2.0，子模块可能有其他许可 | 遵循其 SPDX 和 `LICENSES` 清单，不整体复制到本仓库 |
| Kendryte K210 standalone SDK | 根目录 Apache-2.0，第三方目录另有许可 | 只提交来源、版本和摘要，不提交 SDK 副本 |
| STM32CubeF1 | CMSIS Apache-2.0、HAL/BSP 多为 BSD-3-Clause，部分组件为 ST SLA0044 | 实验尽量只使用 HAL/CMSIS；分发生成工程前逐文件确认，避免把 SLA0044 组件误按 MIT 发布 |
| PSoC E84 SDK | 多组件独立许可；本次核心 device-support 多为 Apache-2.0 | 保留组件级许可证，不把整套厂商 SDK 打包进仓库 |
| GNU/厂商工具链 | 二进制和运行库许可各异 | 仓库仅保留下载清单与校验值，不重新托管工具链二进制 |

当前 `.gitignore` 已排除 SDK 源码、RTOS 源码、工具链和大体积源代码派生候选数据。这不仅控制仓库体积，也降低未审查第三方内容被再次分发的风险。

## 6. 数据和生成物风险

训练数据由开源 SDK 的函数名、签名、文件路径、include 和调用关系派生。虽然函数名和事实性关系通常保护强度较低，完整签名集合与大规模结构化抽取仍可能受数据库权利、许可条款或合同限制。因此公开仓库应优先发布：

- SDK URL、提交哈希、许可证标识和重建脚本；
- 聚合指标、模型权重、真值操作符号清单和哈希；
- 不含大段源码的最小错误样例。

不要直接提交完整 SDK IR、源码正文、厂商头文件集合、预编译库或工具链。生成工程若复制了闭包中的 SDK 源文件，必须作为本地实验产物处理；对外分发前按源文件 SPDX/许可证逐项审查。

## 7. 论文写作规则

可使用的表述：

- “借鉴迟交互检索的 MaxSim 机制，本文提出面向 SDK Migration IR 的字段专用表示……”；
- “采用 LambdaMART 作为可解释特征融合基线……”；
- “编译反馈用于校准可构建性，不用于替代功能验证……”；
- “本文提出的贡献是面向 BSP 迁移的组合设计与闭环验证。”

应避免的表述：

- “首次提出 MaxSim/学习排序/编译反馈”；
- “编译成功证明迁移正确”；
- “三块板卡结果证明适用于所有芯片和 RTOS”；
- “Git 有提交历史，因此证明方法没有侵权”；
- 未引用来源地改写论文算法段落，或复用原论文图表结构后只替换术语。

## 8. 投稿前检查清单

- [ ] 对方法段逐段标出“已有组件、本文改造、本文新增”。
- [ ] 所有公式旁引用原始论文，尤其是 MaxSim、LambdaMART 和风险控制。
- [ ] 使用查重系统检查论文正文，并人工检查“同义改写式雷同”。
- [ ] 对三块板卡真值执行第二标注者盲审并报告一致性。
- [ ] 冻结参数后增加未查看 SDK 进行一次性确认测试。
- [ ] 生成 `THIRD_PARTY_NOTICES.md`，记录 Python 包、模型、RTOS、SDK 和工具链许可。
- [ ] 检查 Git 中不存在 SDK 源码、工具链二进制、厂商库和大体积派生 IR。
- [ ] 核对学校项目合同、专利申请和开源发布的时间及权属要求。
- [ ] 对公开生成工程运行 SPDX/许可证扫描；必要时只发布补丁和重建脚本。
- [ ] 由导师和专利代理人审查最终创新点与专利权利要求边界。
