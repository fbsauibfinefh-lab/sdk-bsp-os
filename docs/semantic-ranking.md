# 语义排序实验

## 两种方法

`resolver.method=weighted` 是七类证据的固定权重基线；`resolver.method=learned` 使用 LightGBM LambdaRank。二者消费同一 IR、能力模式、阈值和 Top-K，差别只在候选排序分数，因此可以隔离排序方法对后续绑定与闭包的影响。

## 数据划分

训练样本按“SDK + 能力”组成排序组，标签表示候选与目标操作的相关程度。不得把同一 SDK 的函数随机拆分到训练和测试；正式实验采用 leave-one-SDK-out，每轮用其余 SDK 训练，在完全未见的 SDK 上测试。

训练数据至少包含两个 SDK：

```bash
conda run -n AIoT-v1.0 python scripts/train_ranker.py \
  --dataset experiments/ranker-training.json \
  --output workspace/models/semantic-ranker.txt
```

在独立测试 SDK 上对照：

```bash
conda run -n AIoT-v1.0 python scripts/compare_resolvers.py \
  --ir workspace/runs/<run-id>/01-sdk-ir.json \
  --ground-truth experiments/<sdk>-ground-truth.json \
  --model workspace/models/semantic-ranker.txt \
  --output workspace/runs/<run-id>/resolver-comparison.json
```

至少报告 Precision、Recall、F1、Recall@K、MRR、解析耗时、闭包规模和规范化操作绑定覆盖。当前仓库提供训练和对照实现，但只有 K210 完整真值，尚不能给出可信的学习排序优越性结论。
