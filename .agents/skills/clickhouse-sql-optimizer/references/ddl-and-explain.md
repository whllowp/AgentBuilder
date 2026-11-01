# DDL 评估（13 类检查）与 EXPLAIN 解读

来源：《clickhouse开发规范.md》第 2 章、第 5.1 节。建表**生成**见 `ddl-codegen.md`；慢 SQL 定位全流程见 `slow-query-sop.md`。

## DDL 检查清单

按顺序核对 CREATE TABLE；先提取：ENGINE（含参数）、PARTITION BY、ORDER BY、PRIMARY KEY、TTL、列定义（名/类型/Nullable/LowCardinality）、跳数索引。

| # | 检查 | 级别 | 要点 |
|---|------|------|------|
| 1 | ENGINE 缺失 | ❌ | MergeTree 家族必须显式声明 |
| 2 | Kafka/Buffer/RabbitMQ 直接落地 | ❌ | 只作摄入管道（MV 落地 MergeTree）；Buffer 重启丢数据 |
| 3 | MergeTree 家族无 ORDER BY | ❌ | 必须显式设计，不做默认 tuple() |
| 4 | ORDER BY 首列高基数（UUID/trace_id/随机 ID） | ⚠️ | 稀释稀疏索引，改低基数在前 |
| 5 | ORDER BY 首列是时间列 | ⚠️ | 其他维度过滤失效；重排为 (维度…, 时间) 漏斗 |
| 6 | PRIMARY KEY 不是 ORDER BY 前缀 | ❌ | 只能取前缀子集 |
| 7 | 细粒度分区（toYYYYMMDD）但无 TTL | ⚠️ | 过度分区风险（parts 不跨分区合并，慢 46x）；对齐 TTL 或改月/不分区 |
| 8 | Nullable 列过多（>3 且 >30%） | ⚠️ | 额外 UInt8 位图；默认值 + 哨兵值替代 |
| 9 | 金额列用 Float（amount/price/fee/cost/balance） | ❌ | 必须 Decimal(18, x) |
| 10 | 状态/类型列用裸 String | ℹ️ | LowCardinality(String) 或 Enum8（去重值 <1 万） |
| 11 | ReplacingMergeTree 无版本列 / 版本列非单调 | ⚠️ | `ReplacingMergeTree(updated_at)`；软删加 is_deleted |
| 12 | CollapsingMergeTree 无 Sign 列 | ❌ | Sign Int8 ±1；查询 `SUM(Sign*x)`；乱序用 Versioned |
| 13 | 有 DateTime 列但无 TTL；宽表无跳数索引；排序键列上建跳数索引 | ℹ️/⚠️ | TTL 粒度=分区粒度；索引只加非键过滤列 |

### 参考 DDL（正面示例）

```sql
CREATE TABLE dws.events
(
    tenant_id   UInt32 COMMENT '租户',
    event_type  LowCardinality(String) COMMENT '事件类型',
    event_date  DateTime COMMENT '事件时间',
    user_id     UInt64,
    amount      Decimal(18, 2),
    INDEX idx_user user_id TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(event_date)
ORDER BY (tenant_id, event_type, event_date)
TTL event_date + INTERVAL 90 DAY
SETTINGS index_granularity = 8192, min_age_to_force_merge_seconds = 600;
```

## EXPLAIN 解读

用 `EXPLAIN indexes = 1`（必要时 `EXPLAIN ANALYZE`）拿执行计划，按这些指标量化：

| 指标 | 位置 | 判读 |
|------|------|------|
| `PrimaryKeyAllParts: N/M` / `Parts: N/M` | PrimaryKey / Skip 段 | 分区裁剪：N/M > 0.5 → WHERE 缺分区列条件（目标 <0.2） |
| `PrimaryKeyAllGranules: N/M` / `Granules: N/M` | 同上 | 主键裁剪：N/M > 0.3 → 过滤未命中排序键前缀；≤0.05 且总量大 → 良好 |
| `Key Condition: ...` | PrimaryKey 段 | 缺失（有 WHERE 时）或含 `unknown` → 键列被函数包裹或非键列过滤 |
| `Expression ((...))` 首行 | 顶部 | 投影列清单，≥15 列提示列裁剪 |
| PREWHERE 标记 | Filter 节点 | `optimize_move_to_prewhere` 默认开；高选择性条件可手工 PREWHERE |

### 判读示例

```
PrimaryKey
  Key Condition: (unknown)          ← WHERE 里 toDate(ts)=... 改半开区间
  PrimaryKeyAllParts: 10/10         ← 分区未裁剪：WHERE 补分区列
  PrimaryKeyAllGranules: 990/1000   ← 排序键未命中：重排 ORDER BY 或加跳数索引
```

### 诊断 SQL（给用户在库上执行）

```sql
-- TOP 慢查询（ProfileEvents 区分 I/O vs 排队）
SELECT event_time, query_duration_ms, read_rows, formatReadableSize(read_bytes), query
FROM system.query_log WHERE type = 'QueryFinish' AND event_date >= yesterday()
ORDER BY query_duration_ms DESC LIMIT 20;

-- part 碎片
SELECT database, table, count() AS active_parts FROM system.parts
WHERE active GROUP BY database, table HAVING active_parts > 100;

-- mutation 堆积
SELECT database, table, mutation_id, is_done, latest_fail_reason
FROM system.mutations WHERE is_done = 0;
```
