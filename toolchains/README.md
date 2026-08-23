# 工具链目录

交叉编译器安装在本目录下，但二进制和下载缓存不提交到 Git。运行以下命令会下载、校验 SHA-256 并安装三套工具链：

```bash
./scripts/install_toolchain.sh
```

- `riscv-none-embed-gcc-10.2.0`：兼容原有 RT-Thread K210 BSP 的 `rv64imafc/lp64f` 参数。
- `xpack-riscv-none-elf-gcc-14.2.0-3`：用于 Zephyr 4.4 的 K210 板级端口。
- `arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi`：用于 STM32F103 与 PSoC E84 的 RT-Thread/Zephyr 构建。

版本、前缀、下载地址和摘要记录在 `manifest.json`。不同架构和 ABI 始终使用独立子目录，防止构建时误用编译器。
