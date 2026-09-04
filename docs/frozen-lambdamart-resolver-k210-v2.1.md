# 冻结 LambdaMART Resolver 接入与 K210 实板验证（v2.1）

## 1. 本轮目标与结论

本轮把此前离线评估的 `structural-prior-feasible-lambdamart-residual-v2.1` 冻结为可部署运行时包，并接入 BSPForge `SemanticResolver`。部署审计发现旧实验数据集的短名单构造会保留全部真值正例；即使导出包不含标签，该短名单也不能作为严格的目标板无标签输入。为消除这一风险，本轮重新从 K210 IR 构造完全不读取真值的候选集，对 14,814 个候选行完成全部特征计算和冻结模型推理，再按模型分数保留每项操作 Top-128。K210 的 RT-Thread 与 Zephyr 项目均使用该修正版模型包重新生成、编译和烧录。

K210 + RT-Thread 已形成完整的绑定级实板闭环：10 次自动复位全部启动，9 条命令每轮全部通过，共 90/90。测试覆盖时钟查询与门控、PLIC 回调、UART1 物理回环、GPIO 物理电平读写、GPIO 边沿中断、硬件定时器单次/周期回调和稳定性。

K210 + Zephyr 已完成同一 Resolver 输入下的原生设备生成、编译、烧录和协议实测：10/10 次启动成功，9 条命令每轮全部通过，共 90/90，失败与 `unsupported` 均为 0。生成工程先连接分析所得 K210 SDK 实现，再使用 `DEVICE_DEFINE` 和 Zephyr 驱动 API 注册 `clock_control`、UART、GPIO、Counter 四个 `struct device`；PLIC 按 Zephyr 二级 IRQ 子系统接入。自测代码只调用 Zephyr 标准设备 API，不直接调用 SDK 适配函数，因此该结果可作为本文五类目标能力已接入 Zephyr 设备/中断框架的端到端证据。

## 2. 冻结运行时契约

运行时包位于：

```text
models/runtime/k210-operation-lambdamart-h03-eq-r1-v2.1.json
```

包格式为 `frozen-operation-ranking-v1`，包含：

- 方法、模型、评估报告和无标签特征输入的 SHA-256；
- SDK ID、SDK digest、IR SHA-256 和目标架构；
- 19 个操作各自的冻结候选实体、最终分数、顺序和首位；
- 字段语义、代码双视图、寄存器效果、结构先验和可行性保护的特征契约；
- `contains_labels: false`，运行时包不携带 H03 标签。

无标签生成器保留所有具有正能力级静态证据的 IR 函数，形成 19 个查询、14,814 个候选行和 2,103 个唯一实体；不存在按真值注入正例或删除负例的步骤。冻结模型先对这些候选全部打分，随后仅为控制部署包体积而保存每项模型 Top-128，共 2,432 行。Resolver 会要求包中的每个实体仍能在当前 IR 中找到；SDK ID 或 digest 不一致、候选实体缺失、候选重复、计数不一致、非有限分数或声明 Top1 与确定性排序不一致时立即失败。

运行时包 SHA-256 为 `d1cad37db9f449d6333e4bb9eb69fac9753b9c61915c981625388258fcf63420`。这一设计保证固件与指定 SDK digest 的冻结结果逐实体一致，但它还不是任意新 SDK 的即时推理包。接入新 SDK 时必须运行同样的无标签候选生成、特征计算和模型推理流程，再导出该 SDK 的运行时包；不需要该 SDK 的人工真值。

## 3. Resolver 数据流

```text
SDK 源码与构建资产
  -> SDK Ingestor / IR Store
  -> 19 项规范操作的无标签全候选池
  -> 字段迟交互、结构检索、寄存器效果图、代码双视图
  -> 冻结 LambdaMART 对 14,814 行全部打分
  -> 每项按模型分数保留 Top-128 作为部署包
  -> 校验 SDK ID、digest 和实体完整性
  -> 与冻结部署候选按 entity_id 对齐
  -> 读取冻结 LambdaMART 最终分数并稳定排序
  -> 每项操作 Top1 写入 canonical-binding-plan.json
  -> Closure Solver 求解源码、头文件、启动和链接资产
  -> OS Backend 生成工程
  -> Build Diagnoser 根据真实编译错误增量修复
  -> ELF/BIN 静态验证
  -> 烧录与统一协议实板回归
```

Resolver 输出方法名为 `frozen-multiview-lambdamart-operation-resolution`。`02-semantic-resolution.json` 保存模型包、模型、报告、数据集、向量缓存和 SDK 的哈希；`02b-canonical-binding-plan.json` 保存 19 个最终选择；后续每项绑定继续携带 `entity_id`、符号、签名和源码证据。

## 4. 复现命令

首次生成 K210 无标签运行时包依次使用以下公开入口脚本，各脚本会在元数据中记录输入、输出和哈希：

```text
scripts/build_runtime_operation_dataset.py
scripts/add_cached_field_late_interaction_scores.py
scripts/add_structured_retrieval_scores.py
scripts/add_hardware_effect_graph_features.py
scripts/cache_pretrained_code_embeddings.py
scripts/cache_multiview_effect_embeddings.py
scripts/export_frozen_lambdamart_bundle.py
scripts/evaluate_frozen_operation_bundle.py
```

其中最后一个脚本只在冻结包生成之后读取独立真值，真值不回流到候选、特征或模型分数。

```bash
cd /home/whk/RTT-porting/bspforge

conda run --no-capture-output -n AIoT-v1.0 \
  python -m bspforge.cli pipeline \
  --config examples/k210-rtthread/project.json

conda run --no-capture-output -n AIoT-v1.0 \
  python -m bspforge.cli pipeline \
  --config examples/k210-zephyr/project.json
```

RT-Thread 烧录与 10 轮回归：

```bash
conda run --no-capture-output -n AIoT-v1.0 kflash \
  -p /dev/ttyACM0 -b 1500000 \
  workspace/generated/k210-rtthread-lambdamart/bsp/k210/rtthread.bin

conda run --no-capture-output -n AIoT-v1.0 \
  python -m bspforge.hardware_test.host \
  --port /dev/ttyACM0 --board k210 --rtos rtthread \
  --baudrate 115200 --timeout 8 --rounds 10 \
  --firmware workspace/generated/k210-rtthread-lambdamart/bsp/k210/rtthread.bin \
  --output workspace/hardware/k210-lambdamart-20260904/k210-rtthread-full-10rounds.json
```

Zephyr 烧录与 10 轮回归只需替换固件、RTOS 参数和输出文件：

```bash
conda run --no-capture-output -n AIoT-v1.0 kflash \
  -p /dev/ttyACM0 -b 1500000 \
  workspace/generated/k210-zephyr-lambdamart/build/zephyr/zephyr.bin

conda run --no-capture-output -n AIoT-v1.0 \
  python -m bspforge.hardware_test.host \
  --port /dev/ttyACM0 --board k210 --rtos zephyr \
  --baudrate 115200 --timeout 5 --rounds 10 \
  --firmware workspace/generated/k210-zephyr-lambdamart/build/zephyr/zephyr.bin \
  --output workspace/hardware/k210-lambdamart-20260904/k210-zephyr-full-10rounds.json
```

板卡接线为 IO7(TX) 与 IO6(RX) 短接，IO8 输出与 IO9 输入连接。USB UARTHS 继续承担主机协议，不与 UART1 回环混用。

## 5. 生成与编译结果

| 后端 | 操作绑定 | 闭包 | 构建迭代 | 固件 | 大小 | SHA-256 |
| --- | ---: | --- | ---: | --- | ---: | --- |
| RT-Thread | 19/19 | 71 文件、10 条构建规则 | 2 | `rtthread.bin` | 468104 B | `9702bdfd8274410fb642d6d8de96bf6327de75b3902c40f4dc19b10704fd16ea` |
| Zephyr | 19/19 | 71 文件、10 条构建规则 | 1 | `zephyr.bin` | 34744 B | `c423e5162fc28e725f66406499a87d46c3a7b63a2e253982476298f7a631d809` |

RT-Thread 第一轮链接发现 `sys_register_getchar`、`sys_register_putchar`、`sys_getchar` 和 `sys_putchar` 缺失。Build Diagnoser 根据 IR 找到已有 SDK 提供者 `lib/bsp/syscalls.c`，第二轮成功；19/19 项绑定均被编译反馈观察，生成的 UART、PIN、HWTIMER 操作表和注册函数均存在于 ELF。

Zephyr 一次构建成功，ELF/BIN 架构和段检查通过。编译反馈确认规范计划的 19/19 项操作均已进入本次编译；后端将其组织为 24 个可追溯 SDK 符号依赖，绑定宏召回率为 1.0。ELF 同时包含四个生成设备 getter 和两个验证入口。K210 SDK 的裸机 PLIC API 由生成桥接层映射到 Zephyr 二级 IRQ；这是符合 Zephyr 中断控制器模型的后端兼容映射，不是普通外设设备对象，也不修改语义排序结果。以 Zephyr 专属设备契约评估时，四类设备的操作宏召回率为 1.0。

## 6. 实板结果

| 组合 | 启动 | 适用命令通过 | 总命令 | unsupported | 失败 | 启动时间均值 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| K210 + RT-Thread | 10/10 | 90/90 | 90 | 0 | 0 | 198.225 ms |
| K210 + Zephyr | 10/10 | 90/90 | 90 | 0 | 0 | 32.608 ms |

RT-Thread 每轮关键观测一致：

| 命令 | 实际路径与通过条件 | 观测值 |
| --- | --- | --- |
| `clock.basic` | 预测 SDK 时钟包装执行 enable/get-frequency/disable | CPU 与 TIMER2 均为 403000000 Hz |
| `interrupt.basic` | RT-Thread HWTIMER -> 预测 timer/PLIC 绑定 -> 回调 | 1 次回调，约 11 ticks |
| `uart.loopback` | `rt_device_write/read(bspuart1)` -> 预测 UART1 绑定 -> IO7/IO6 | 16 bytes，0 errors |
| `gpio.toggle` | 预测 GPIO 配置/写/读 -> GPIOHS29/28 -> IO8/IO9 | 低电平 0，高电平 1 |
| `gpio.irq` | 预测 GPIO IRQ 注册 -> GPIOHS28 上升沿 -> PLIC 回调 | 1 次回调 |
| `timer.oneshot` | `bsptim0` -> 预测 TIMER0 启动/停止/周期设置 | 1 次回调，约 11 ticks |
| `timer.periodic` | 同一硬件路径的周期模式 | 3 次回调，约 31 ticks |

Zephyr 使用同一接线和同一九命令协议。十轮中 CPU/TIMER 时钟查询均为 390000000/1523437 Hz；UART 每轮发送并接收 16 字节且错误为 0；GPIO 输出锁存和输入实测均按 0/1 变化；GPIO 边沿、基础中断与单次定时器均为 1 次回调，周期定时器均严格为 3 次回调。周期回调达到目标后立即停表，验证的是初始化、模式、启停和 IRQ 可达性，不把约 2 ms 的主机观测值解释为定时精度。

机器可读报告已纳入仓库：

```text
experiments/hardware-results/k210-operation-lambdamart-v2.1/k210-rtthread-full-10rounds.json
experiments/hardware-results/k210-operation-lambdamart-v2.1/k210-zephyr-full-10rounds.json
experiments/hardware-results/k210-operation-lambdamart-v2.1/k210-zephyr-native-device-model.json
experiments/hardware-results/k210-operation-lambdamart-v2.1/k210-zephyr-native-artifact-verification.json
experiments/hardware-results/k210-operation-lambdamart-v2.1/k210-zephyr-native-method-evaluation.json
```

两份报告均采用协议 schema 1.1，直接嵌入已烧录 BIN 的相对路径、字节数和 SHA-256；报告中的启动 `build_id`、固件哈希、逐轮请求/响应和原始串口文本共同形成可追溯证据。

## 7. 实测中发现并修复的问题

RT-Thread UART 首次回环为 0/16。原因是 SDK `uart_receive_data` 和 RT-Thread `getc` 都是非阻塞接口，测试程序在发送后只读取一次。验证器改为在 100 ms 截止时间内轮询，最终 10 轮均为 16/16。修正作用于通用轮询式串口验证时序，不改变 Resolver 选择、SDK 绑定函数或板卡专用白名单。

Zephyr 首次可发送启动事件但无法接收命令。原因包括 K210 UARTHS 实际时钟描述不一致，以及空闲读取每次睡眠 1 ms；115200 baud 下约每 87 微秒到达一个字节，小 FIFO 会丢失命令。端口时钟修正后，验证线程在 `main()` 进入接收循环再发送 boot 事件，空闲轮询改为 50 微秒，协议接收恢复。

随后为 Zephyr 增加 `generated-sdk-adapter`。首次功能固件暴露两类后端契约问题：K210 SDK 的 PLIC 本地中断号不能直接当作 Zephyr 一级 IRQ，GPIO 驱动的 FPIOA 反向查询依赖裸机初始化状态。端口启用 Zephyr 二级 IRQ 表并由生成桥编码 K210 本地 IRQ；GPIO 初始化通过 SDK FPIOA API配置复用和上下拉，并在适配层设置 GPIOHS 方向寄存器，读写、边沿和注册仍调用 SDK API。周期定时器再增加启动前状态清理和达到目标后的停表，消除回调风暴。三项均由设备模型或 OS 中断语义触发，配置参数来自后端验证配置，不包含针对某次请求 ID、输出值或单轮结果的通过白名单。

## 8. 论文使用边界

- 可以声明：冻结 LambdaMART 选择已实际进入 K210 RT-Thread 的 19 项绑定、闭包、编译和固件，五类能力的可观测行为在 10 轮中全部通过。
- 可以声明：同一 Resolver 输入可生成并编译两种 RTOS 工程；Zephyr 侧已把 19/19 项规范绑定接入四类原生 `struct device` 驱动和 PLIC 中断子系统，并通过只使用标准 Zephyr API 的五能力实板回归。
- 不能声明：当前结果覆盖 Zephyr 的全部设备类别、全部 K210 外设或达到上游通用 BSP 的完整范围，也不能用功能回调次数宣称定时精度或性能提升。
- 不能把 90/90 当作 90 个独立语义样本；它是 9 条命令在 10 次复位中的重复运行。
- 10 轮适合本轮工程确认，正式论文仍应补充更长时间/更多轮次、另外两块板和人工 BSP 对照。

## 9. 无标签候选审计与事后指标

修正版冻结包生成完成后，才读取 K210 外部真值和既有等价仲裁执行评测。真值集合本身作为 Recall/AP/nDCG 的分母，不会只统计已经进入候选包的正例。

| 指标 | K210 结果 |
| --- | ---: |
| 真值符号进入无标签全候选池 | 48/48 |
| P@1 | 0.895 |
| Recall@5 | 0.775 |
| MAP | 0.722 |
| nDCG@10 | 0.816 |
| Hit@5 | 0.947 |

与旧短名单包相比有两项 Top1 改变：`gpio.write` 由 `gpiohs_set_pin` 变为 `gpio_set_pin`，`timer.start` 由 `timer_set_enable` 变为 `timer_enable`。严格真值暂未把 `timer_enable` 列为正例，因此 P@1 下降一项；但重新生成的 RT-Thread 固件在 10 轮硬件定时器单次和周期回归中全部通过。论文应把它记录为“严格真值不一致但端到端行为通过，需后续源码仲裁”的案例，不能在看到板测结果后直接改真值并回算主指标。

机器评测报告为 `experiments/operation-ranking/results-k210-runtime-label-free-lambdamart-v2.1.json`。它证明 K210 部署输入不依赖目标真值，但单板事后指标不替代训练 SDK 的厂商隔离交叉验证或新的冻结确认 SDK。
