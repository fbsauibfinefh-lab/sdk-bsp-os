# 第三方源码

`third_party/rt-thread` 是当前实验所用 RT-Thread 源码的本地链接。BSPForge 不在原目录中修改或编译源码：后端复制目标 BSP，并将固定版本的内核和组件目录以只读引用方式接入生成工程，所有构建产物均位于 `workspace/generated/`。

正式发布实验时应记录 RT-Thread 提交号和本地修改状态，或使用官方仓库中的固定提交重新运行。

