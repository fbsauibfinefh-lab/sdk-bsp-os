# SDK 输入目录

SDK 源码属于本地实验输入，不提交到 Git。每个 SDK 使用稳定目录名，并在其下创建 `source` 链接或副本：

```text
sdk/
  k210/
    source -> /mnt/d/Wuhk/AIOT/k210sdk/kendryte-standalone-sdk
```

运行 `scripts/bootstrap_local_inputs.sh` 可创建当前 K210 样例链接。正式实验需要记录上游版本、Git 提交号、工作区状态和归档校验值。

