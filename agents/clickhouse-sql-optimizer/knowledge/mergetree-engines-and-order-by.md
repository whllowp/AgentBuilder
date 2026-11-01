---
title: MergeTree 家族引擎与 ORDER BY 排序键设计
keywords: MergeTree ReplacingMergeTree CollapsingMergeTree SummingMergeTree ORDER BY PRIMARY KEY 排序键 主键 稀疏索引 granule 引擎选择 去重
source: ClickHouse 官方文档最佳实践 + 《clickhouse开发规范.md》第 2.2/2.3/2.9 节
---

# MergeTree 家族引擎与 ORDER BY 排序键设计

## 引擎选型决策表

- 追加写、无去重：`MergeTree`。
- 同主键保留最新版本（CDC 入湖、Upsert）：`ReplacingMergeTree([version_col])`，可加 `is_deleted` 支持软删。
- 行数增减（聚合回撤）：`CollapsingMergeTree(Sign)` / `VersionedCollapsingMergeTree(Sign, Ver)`，Sign 取 ±1。
- 预聚合汇总：`SummingMergeTree` / `AggregatingMergeTree`（聚合列用 `AggregateFunction` 状态类型，配合 MV）。
- 生产明细表禁用 Kafka/RabbitMQ/Buffer 引擎直接落地：Kafka 引擎表只是摄入管道（MV 落地到 MergeTree）；Buffer 引擎异常重启丢数据。
- `Distributed` 表仅作分片查询入口，禁止高频小批量写入 Distributed 表。

## ORDER BY 设计原则（官方：单一最重要的优化，可达 100x）

ORDER BY 决定磁盘物理布局；PRIMARY KEY 决定加载进内存的稀疏索引（默认每 8192 行一个标记/granule）。设计规则：

1. 低基数列在前、高基数/时间列在后：`(tenant_id, event_type, event_date)`，不要 `(event_date, tenant_id)`，更不能 UUID/随机 ID 打头。
2. 排序键是"维度 → 时间"漏斗：等值/IN 过滤的维度列放前面，范围过滤的时间列放最后。
3. 排序键列数一般 ≤ 4，过长稀释前缀压缩收益并拖慢合并。
4. PRIMARY KEY 必须是 ORDER BY 的前缀子集，不允许 ORDER BY 之外的列。
5. 上线后不能改 ORDER BY——只能建新表迁移。设计阶段必须拿真实查询模式评审。
6. 官方基准：`ORDER BY (product_category, review_date)` 对齐查询模式后比 `ORDER BY (review_date)` 快 3 倍、扫描数据少 347 倍。

## ReplacingMergeTree 去重语义

1. 去重键 = ORDER BY 列：业务主键（如 order_id）必须在 ORDER BY 中，否则去重语义错误。
2. 合并是异步的，查询时不能假设已去重。取最新值的方案按优先级：
   - 物化视图 + `argMax(col, version)` 预物化（官方 1.5 亿行实测：多 part 下 1.0s vs FINAL 1.5s；单 part 0.40s vs 0.48s）；
   - `SELECT ... FINAL`：语义最简单但查询时读更多数据、限制下推，仅用于低频查询；
   - `LIMIT 1 BY key ORDER BY version DESC`：配合排序键 (key, version) 比 FINAL 便宜；
   - `OPTIMIZE TABLE t FINAL`：强制合并去重，重操作，只批量导入后离线执行。
3. `ReplacingMergeTree(version)` 必须提供单调递增版本列（updated_at 或 seq），否则"最新"无定义。
4. `min_age_to_force_merge_seconds = 600` + `min_age_to_force_merge_on_partition_only = 1` 让 part 尽快收敛，降低 FINAL 代价。

## CollapsingMergeTree 正确性

- 写入成对记录 +1/-1 行；查询必须 `SUM(Sign * amount)` 聚合，漏写 Sign 是正确性事故。
- 乱序到达场景用 VersionedCollapsingMergeTree（加版本列）。
