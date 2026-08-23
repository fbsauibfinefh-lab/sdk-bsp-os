# 扩展指南

## 增加芯片 SDK

1. 将源码放置或链接到 `sdk/<name>/source`。
2. 新建示例 JSON，设置稳定 SDK ID、能力列表和工具链。
3. 运行摄取并检查文件、函数和构建规则覆盖情况。
4. 厂商特有命名只应通过配置或独立 profile 扩展，避免污染通用规则。
5. 增加人工标注语义集、闭包真值和小型测试夹具。

## 增加功能绑定

在对应 OS 后端的 binding generator 中声明：

- 目标 OS 侧稳定接口；
- 所需 SDK 符号集合；
- 类型转换和返回值归一化规则；
- 生成源码模板；
- 每个 SDK 符号的 IR 证据。

缺少任一必要符号时不得生成“看似可用”的空实现，应在绑定清单中标记缺失并由实验统计。

## 增加 OS 后端

实现 `OSBackend.generate(..., options=None)` 和 `OSBackend.build()`，并提供与 RT-Thread 后端等价的产物验证入口。后端负责目标 OS 的设备模型、工程结构、配置机制、构建规则和产物检查；通用 IR、语义恢复和闭包层不得依赖 K210 路径。

当前第二后端为 Zephyr 4.4，使用 devicetree/Kconfig/CMake/Ninja，与 RT-Thread 的设备对象/SCons 路径形成区分。新增第三后端时应复用现有 IR、闭包、诊断和产物验证契约，不复制流水线控制逻辑。

若目标芯片已有成熟 Zephyr/RT-Thread 驱动，应使用 `NativeDriverBindingTracer` 记录原生驱动到输入 SDK 实体的调用证据；只有目标 BSP 缺少相应绑定时，才增加新的生成式 binding generator。

## 增加诊断规则

在 `build_diagnoser` 中新增精确模式、分类和约束，并使用真实日志增加测试。只有“加入源码”和“加入包含目录”等增量、可回溯操作可以默认自动执行；删除实现、修改 ABI、调整链接脚本或内存布局需要显式策略和独立验证。

## 增加真值集与实验

在 `experiments/` 中增加一个版本化 JSON，分别标注 `semantic_symbols`、`binding_symbols` 和 `device_operations`。项目配置引用该文件后，流水线自动输出方法指标和七类证据消融。新增样本不应复制评估代码，只增加输入配置和人工核验数据。
