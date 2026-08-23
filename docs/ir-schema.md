# SDK Migration IR 数据结构

IR 使用 JSON 表示，包含五类主要集合：

| 集合 | 作用 | 稳定标识依据 |
| --- | --- | --- |
| `files` | 源码、头文件、构建、链接和启动资产 | SDK ID + 相对路径 |
| `functions` | 函数定义、签名、调用、包含和宏上下文 | SDK ID + 路径 + 符号 + 行号 |
| `symbols` | 可参与链接诊断的全局变量定义 | SDK ID + 路径 + 符号 + 行号 |
| `build_rules` | CMake、Make 和 SCons 构建引用 | SDK ID + 构建文件路径 |
| `edges` | `defines`、`calls`、`includes`、`builds` 关系 | 两端实体 ID |
| `stats` | 摄取覆盖情况 | 当前快照 |

顶层 `sdk.digest` 根据有序文件哈希生成。实体证据使用 SDK 相对路径，因此实验可在不同机器和目录中重现；绝对 `sdk.root` 仅用于记录本地来源，不参与实体标识。

## 诊断增量字段

构建闭包还包含：

- `repair_sources`：诊断阶段要求额外参与构建的源码；
- `repair_include_dirs`：诊断阶段补充的头文件搜索目录；
- `repair_history`：每轮诊断、动作和证据；
- `provenance`：所有初始和增量实体的加入原因。

## 版本演进

当前 schema 版本为 `1.0`。兼容修改可以增加可选字段；破坏性修改需要提升主版本并提供转换器。后续可增加预处理配置、AST 类型、静态库符号表、内存区域模型和代码生成血缘。
