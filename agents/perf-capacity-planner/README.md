# 性能容量规划 Agent（perf-capacity-planner）

## 定位

把业务量级换算成资源结论：ClickHouse（存储/主键内存/分区数）、Kafka（分区数/存储）、Flink（并行度/slots/TM/RocksDB 内存）、通用服务（QPS→线程与连接池）。每个结论附**公式 + 假设（默认系数与实测修正法）+ 水位阈值（50/70 规则）+ 验证方法 + 敏感性**——拒绝黑盒数字。**已实现 v0.1**。

## 使用方式

```bash
python agents/perf-capacity-planner/src/capacity_agent/cli.py \
  "ClickHouse 日增 2 亿行，行宽 200B，保留 90 天，双副本" --offline
python agents/perf-capacity-planner/src/capacity_agent/cli.py "Kafka 每秒 5万条，保留 72 小时" --offline
cd agents/perf-capacity-planner && python -m pytest tests -q
```

## 实现结构

`tools/capacity_tools/capacity_calc.py`（四引擎容量模型，公式/假设/敏感性内建；kwargs 按签名过滤）、`spec_parser.py`（中文需求解析：亿/万缩放、双副本、保留期等）、`knowledge/capacity-models.md`（系数表与水位 SOP）、`src/capacity_agent/`（双模式 + CLI）、`tests/`（11 用例含手工复核断言）、`examples/`。

## 关联产物

ZCode 技能 `.agents/skills/perf-capacity-planner/`。
