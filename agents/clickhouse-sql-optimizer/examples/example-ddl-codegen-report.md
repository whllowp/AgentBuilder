# ClickHouse 优化报告

## 任务解析

| 项 | 值 |
| --- | --- |
| 任务类型 | 建表方案生成 |
| 涉及表 | ods.orders_cdc |
| 语句数 | 查询 0；DDL 0；EXPLAIN 0 |
| 建表场景 | CDC 入湖/Upsert（ReplacingMergeTree(updated_at) + 软删） |
| 适用版本 | ClickHouse 24.x |

## 建表方案

场景：CDC 入湖/Upsert（ReplacingMergeTree(updated_at) + 软删）

```sql
CREATE TABLE ods.orders_cdc
(
    tenant_id UInt32 COMMENT '业务主键-tenant_id',
    event_type UInt32 COMMENT '业务主键-event_type'
    event_time DateTime COMMENT '业务时间',
    updated_at DateTime COMMENT 'CDC更新时间(单调版本列)',
    is_deleted UInt8 DEFAULT 0 COMMENT '软删标记',
    amount Decimal(18, 2) COMMENT '金额',
    status LowCardinality(String) COMMENT '状态',
    raw String COMMENT '原始报文'
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(event_time)
ORDER BY (tenant_id, event_type, event_time)
TTL event_time + INTERVAL 90 DAY
SETTINGS index_granularity = 8192, min_age_to_force_merge_seconds = 600;
```

**设计要点**：
- 去重键 = ORDER BY 列，业务主键必须在其中（规范 2.3-3）。
- 版本列 updated_at 必须单调递增，否则'最新版本'无定义（规范 2.9-2）。
- 高频查询取最新值用 MV+argMax 或 LIMIT 1 BY，查询时 FINAL 仅低频（规范 2.9-1）。
- min_age_to_force_merge_seconds=600 让 part 尽快收敛，降低读取端去重代价（规范 2.9-4）。

**自检**：引擎 ReplacingMergeTree，7 列，排序键 3 列，发现 0 处问题：❌0 / ⚠️0 / ℹ️0，模板结构合规 ✅

## 审查发现

## 优化建议

- 生成的表结构已按规范设计（低基数前置排序键、分区对齐 TTL、类型合规）；按业务替换占位列后，用 `EXPLAIN indexes=1` 验证真实查询命中。

## 慢 SQL 定位与优化流程（六步 SOP）

1. **发现**：用 system.query_log 找出慢查询（duration > 5s），看 read_rows/read_bytes 判断是扫描型还是资源型慢。
2. **取证**：读 ProfileEvents 分类瓶颈：FileOpen/OSRead 高=I/O 型；OCPUWait 高=CPU 型；ContextLock 高=排队型；external_aggregation=溢出磁盘型。
3. **归因**：EXPLAIN indexes=1 看三个指标：Parts N/M（分区裁剪）、Granules N/M（主键裁剪）、Key Condition（键条件是否 unknown），按决策树定位到索引/分区/列裁剪/聚合 JOIN 四类根因。
4. **改写**：按规范 5.2 优先级套手段：补 WHERE 命中排序键前缀 → 列裁剪 → 键列函数改区间 → 跳数索引 → 投影/MV → 字典 → argMax 替代 FINAL。
5. **验证**：EXPLAIN ANALYZE 对比改写前后的 elapsed/read_rows/read_bytes（相同 max_threads）；上线后观察 P95 变化。
6. **固化**：查询级熔断（max_execution_time/max_rows_to_read）、只读账号配额、高频模式沉淀为索引/投影/MV、duration>5s 告警与 part 碎片巡检。

## 诊断与验证

在目标库执行以下诊断 SQL，把结果贴回可获得量化优化建议：

**TOP 慢查询**（第 1 步：发现） 第 1 步·发现：定位最慢查询；扫描量亿级=索引问题，扫描小但慢=锁/资源问题。
```sql
SELECT event_time, user, query_id, query_duration_ms,
       read_rows, formatReadableSize(read_bytes) AS read_size,
       formatReadableSize(memory_usage) AS mem, query
FROM system.query_log
WHERE type = 'QueryFinish' AND event_date >= today() - 3
  AND query_duration_ms > 5000
ORDER BY query_duration_ms DESC
LIMIT 20;
```

**瓶颈取证（ProfileEvents）**（第 2 步：取证） 第 2 步·取证：I/O 型 / CPU 型 / 排队型 / 溢出磁盘型分类。
```sql
SELECT ProfileEvents['FileOpen'] AS file_open,
       ProfileEvents['OSCPUWaitMicroseconds'] AS cpu_wait_us,
       ProfileEvents['ContextLockWaitMicroseconds'] AS lock_wait_us,
       ProfileEvents['ExternalAggregationMergePartsWithSeconds'] AS ext_agg
FROM system.query_log
WHERE query_id = '<目标query_id>';
```

**分区 part 碎片健康度**（第 3 步：归因） 第 3 步·归因（表级）：part > 10/分区 或总 part > 100 预警碎片（写入侧问题）。
```sql
SELECT database, table, count() AS active_parts, sum(rows) AS rows,
       countIf(active_parts_per_partition > 10) AS fragmented_partitions
FROM (
    SELECT database, table, partition, count() AS active_parts_per_partition, sum(rows) AS rows
    FROM system.parts WHERE active
    GROUP BY database, table, partition
)
GROUP BY database, table
HAVING fragmented_partitions > 0 OR active_parts > 100
ORDER BY active_parts DESC;
```

**表 ods.orders_cdc 的规模与压缩**（第 3 步：归因） 第 3 步·归因：评估数据量级与压缩比，作为分区粒度与索引收益的依据。
```sql
SELECT partition, name, rows, formatReadableSize(data_compressed_bytes) AS compressed,
       formatReadableSize(data_uncompressed_bytes) AS uncompressed
FROM system.parts WHERE active AND table = 'ods.orders_cdc'
ORDER BY partition, name LIMIT 100;
```

**mutation 堆积**（第 3 步：归因） 第 3 步·归因（表级）：mutation 堆积会持续重写 part 挤占资源（规范 3-5）。
```sql
SELECT database, table, mutation_id, is_done, create_time, latest_fail_reason
FROM system.mutations
WHERE is_done = 0
ORDER BY create_time;
```

## 规范依据（知识库命中）

- **物化视图（MV）与投影（Projection）的取舍**（materialized-views-and-projections.md）：# 物化视图（MV）与投影（Projection）的取舍…

完整规范见《clickhouse开发规范.md》（Agent 根目录）。

---
*本报告由 clickhouse-sql-optimizer 离线管线生成（未调用 LLM）；LLM 模式可获得交互式定制。*