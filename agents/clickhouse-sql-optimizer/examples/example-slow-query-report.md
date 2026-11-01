# ClickHouse 优化报告

## 任务解析

| 项 | 值 |
| --- | --- |
| 任务类型 | 混合输入（DDL + 查询/EXPLAIN） |
| 涉及表 | dws.orders |
| 语句数 | 查询 1；DDL 1；EXPLAIN 0 |
| 适用版本 | ClickHouse 24.x |

## 审查发现

**SQL 审查**：共 1 条语句，发现 4 处问题：❌1 / ⚠️2 / ℹ️1

**DDL-1**：引擎 ReplacingMergeTree，5 列，排序键 1 列，发现 6 处问题：❌1 / ⚠️3 / ℹ️2

| 级别 | 规则 | 证据 | 建议 |
| --- | --- | --- | --- |
| ❌ | 禁止 SELECT *（含 DISTINCT *）（规范 4.1-1） | `SELECT * FROM dws.orders FINAL WHERE toDate(create_time) = '` | 列存按列读：明确列出所需列。官方实测列裁剪常有 10x 级差异；EXPLAIN 的 Read columns 可验证。 |
| ⚠️  | WHERE 中对列使用函数包裹（若该列在排序键/分区键上则裁剪失效）（规范 4.1-3） | `WHERE toDate(create_time) = '2026-09-01' ORDER BY order_id L` | 改写为半开区间或等值比较：toDate(ts)=d → ts>=d AND ts<d+1；toYYYYMM(c)=m → c>=月初 AND c<次月初。改写后用 EXPLAIN 确认 Key Condition 不再是 unknown。 |
| ⚠️  | 大偏移分页（offset=100000）（规范 4.1-4） | `order_id LIMIT 100000, 20` | LIMIT offset,n 需要先扫描并丢弃 offset 行。改用 keyset 分页：WHERE (id, ts) > (last_id, last_ts) ORDER BY id, ts LIMIT n。 |
| ℹ️  | 查询使用 FINAL（有查询时代价）（规范 2.9-1 / 4.3-1） | `SELECT * FROM dws.orders FINAL WHERE toDate(create_time) = '` | FINAL 读更多数据且限制部分下推（官方 1.5 亿行实测 1.5s vs argMax 1.0s）。高频报表：MV+argMax 预物化最新值，或 LIMIT 1 BY key ORDER BY version DESC；低频后台任务可保留 FINAL。 |
| ❌ | 金额列 pay_amount 使用 Float64（规范 2.5-3） | `pay_amount Float64` | 金额/费率必须 Decimal(18, x)，Float 有精度误差。 |
| ⚠️  | ORDER BY 首列 trace_id 疑似高基数（UUID/随机 ID）（规范 2.3-1） | `ORDER BY (trace_id)` | 首列高基数会稀释稀疏索引：改为低基数维度在前、高基数/时间在后。上线后不可改，需新表迁移。 |
| ⚠️  | 细粒度分区但无 TTL（过度分区风险）（规范 2.4-1/2.4-2） | `PARTITION BY toYYYYMMDD，无 TTL` | 分区是数据管理手段：超过几十个分区多半过度（parts 不跨分区合并，官方实测慢 46x）。无 TTL/数据 < 10 亿行建议 PARTITION BY tuple() 或改月分区；有 TTL 时分区粒度对齐 TTL。 |
| ⚠️  | ReplacingMergeTree 未指定版本列（规范 2.9-2） | `ENGINE = ReplacingMergeTree()` | 加版本列：ENGINE = ReplacingMergeTree(updated_at)，否则按插入顺序取值，乱序写入时'最新'不确定。 |
| ℹ️  | 低基数列建议 LowCardinality/Enum：status（规范 2.5-1/2.5-2） | `String 列: status` | 去重值 < 1 万的字符串列用 LowCardinality(String) 或 Enum8；配合 ZSTD 压缩收益明显。 |
| ℹ️  | 有时间列但未声明 TTL（规范 2.8-1） | `TTL 子句缺失` | 明细大表应声明 TTL（或明确永久保留）；TTL 粒度 = 分区粒度时整分区删除效率最高。 |

## 优化建议

- ❌ **禁止 SELECT *（含 DISTINCT *）**
  - 建议：列存按列读：明确列出所需列。官方实测列裁剪常有 10x 级差异；EXPLAIN 的 Read columns 可验证。
  - 依据：规范 4.1-1
- ⚠️  **WHERE 中对列使用函数包裹（若该列在排序键/分区键上则裁剪失效）**
  - 建议：改写为半开区间或等值比较：toDate(ts)=d → ts>=d AND ts<d+1；toYYYYMM(c)=m → c>=月初 AND c<次月初。改写后用 EXPLAIN 确认 Key Condition 不再是 unknown。
  - 依据：规范 4.1-3
- ⚠️  **大偏移分页（offset=100000）**
  - 建议：LIMIT offset,n 需要先扫描并丢弃 offset 行。改用 keyset 分页：WHERE (id, ts) > (last_id, last_ts) ORDER BY id, ts LIMIT n。
  - 依据：规范 4.1-4
- ℹ️  **查询使用 FINAL（有查询时代价）**
  - 建议：FINAL 读更多数据且限制部分下推（官方 1.5 亿行实测 1.5s vs argMax 1.0s）。高频报表：MV+argMax 预物化最新值，或 LIMIT 1 BY key ORDER BY version DESC；低频后台任务可保留 FINAL。
  - 依据：规范 2.9-1 / 4.3-1
- ❌ **金额列 pay_amount 使用 Float64**
  - 建议：金额/费率必须 Decimal(18, x)，Float 有精度误差。
  - 依据：规范 2.5-3
- ⚠️  **ORDER BY 首列 trace_id 疑似高基数（UUID/随机 ID）**
  - 建议：首列高基数会稀释稀疏索引：改为低基数维度在前、高基数/时间在后。上线后不可改，需新表迁移。
  - 依据：规范 2.3-1
- ⚠️  **细粒度分区但无 TTL（过度分区风险）**
  - 建议：分区是数据管理手段：超过几十个分区多半过度（parts 不跨分区合并，官方实测慢 46x）。无 TTL/数据 < 10 亿行建议 PARTITION BY tuple() 或改月分区；有 TTL 时分区粒度对齐 TTL。
  - 依据：规范 2.4-1/2.4-2
- ⚠️  **ReplacingMergeTree 未指定版本列**
  - 建议：加版本列：ENGINE = ReplacingMergeTree(updated_at)，否则按插入顺序取值，乱序写入时'最新'不确定。
  - 依据：规范 2.9-2
- …另有 2 条见上表

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

**表 dws.orders 的规模与压缩**（第 3 步：归因） 第 3 步·归因：评估数据量级与压缩比，作为分区粒度与索引收益的依据。
```sql
SELECT partition, name, rows, formatReadableSize(data_compressed_bytes) AS compressed,
       formatReadableSize(data_uncompressed_bytes) AS uncompressed
FROM system.parts WHERE active AND table = 'dws.orders'
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

- **查询诊断与优化 SOP（query_log/EXPLAIN/PREWHERE/读写顺序）**（query-optimization.md）：## 诊断流程

1. `system.query_log`（type='QueryFinish'）按 `query_duration_ms` 排序找慢查询；看 `read_rows/read_bytes` 定位扫描量；`ProfileEvents` 区分瓶颈：FileOpen/PagesRead …
- **MergeTree 家族引擎与 ORDER BY 排序键设计**（mergetree-engines-and-order-by.md）：## ReplacingMergeTree 去重语义

1. 去重键 = ORDER BY 列：业务主键（如 order_id）必须在 ORDER BY 中，否则去重语义错误。
2. 合并是异步的，查询时不能假设已去重。取最新值的方案按优先级：
   - 物化视图 + `argMax(col, ve…
- **常见性能陷阱与案例（12 例）**（common-pitfalls.md）：## 案例 10：Nullable 滥用 → 压缩差查询慢

症状：额外 UInt8 null 位图文件、扫描变慢。
处置：默认值（0、''、epoch）+ 哨兵值；只在无法约束的外部数据用 Nullable。…
- **分区策略与跳数索引（minmax/set/bloom_filter/tokenbf/ngrambf/inverted）**（partitioning-and-skip-indexes.md）：## 分区：数据管理手段，不是查询加速手段

1. 分区的价值：TTL 整区删除、按分区搬数/备份；查询加速主要靠 ORDER BY 稀疏索引。
2. 官方经验："超过几十个分区，多半是过度分区"。parts 之间**不跨分区合并**，过度分区 → part 碎片、合并压力、打开文件开销；官方实测月…

完整规范见《clickhouse开发规范.md》（Agent 根目录）。

---
*本报告由 clickhouse-sql-optimizer 离线管线生成（未调用 LLM）；LLM 模式可获得交互式定制。*