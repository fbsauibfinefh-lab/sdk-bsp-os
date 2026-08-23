# 工具链目录

工具链安装在本目录下，但二进制和压缩包不提交到 Git。K210 配置采用 xPack GNU RISC-V Embedded GCC 10.2.0-1.2，因为现有 RT-Thread K210 BSP 使用 `riscv-none-embed-` 前缀和 `rv64imafc/lp64f` 参数。

```bash
./scripts/install_toolchain.sh
toolchains/riscv-none-embed-gcc-10.2.0/bin/riscv-none-embed-gcc --version
```

安装脚本支持断点续传并在解压后检查编译器。后续架构应使用独立子目录和 manifest 条目，禁止混用不同架构或 ABI 的二进制文件。

