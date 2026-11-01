---
title: 慢 SQL 定位与优化六步 SOP（发现→取证→归因→改写→验证→固化）
keywords: 慢SQL 定位 排查 流程 SOP query_log query_duration_ms ProfileEvents EXPLAIN ANALYZE 瓶颈 IO CPU 内存 归因 决策树 验证 固化 settings 熔断
source: 《clickhouse开发规范.md》第 5 章扩展 + ClickHouse 官方查询优化指南
---

# 慢 SQL 定位与优化六步 SOP

## 第 1 步：发现（找到慢查询）

```sql
SELECT event_time, user, query_id,
       query_duration_ms,
       read_rows, formatReadableSize(read_bytes) AS read_size,
       formatReadableSize(memory_usage) AS mem,
       query
FROM system.query_log
WHERE type = 'QueryFinish' AND event_date >= today() - 3
  AND query_duration_ms > 5000
ORDER BY query_duration_ms DESC
LIMIT 20;
```

看三个信号：`query_duration_ms`（耗时）、`read_rows/read_bytes`（扫描量，扫描亿级行才慢通常是索引问题；扫几十万行也慢则是锁/资源问题）、`memory_usage`（内存型慢）。高并发场景补看 `type='ExceptionWhileProcessing'` 的失败查询。

## 第 2 步：取证（瓶颈分类）

`ProfileEvents` 区分瓶颈类型：

| 信号 | 含义 | 指向 |
|------|------|------|
| `FileOpen`/`OSReadChars` 高、`read_uncompressed_bytes` >> `result_bytes` | I/O 型 | 列裁剪、压缩、索引裁剪 |
| `OCPUWait`/`OCPUVirtualTime` 高 | CPU 型 | 聚合函数、正则、字符串处理 |
| `ContextLock` 等待高、`PeerQueryWaitMicroseconds` | 排队/锁型 | 并发限流、长事务、Distributed 同步 |
| `external_aggregation`/`external_sort` = 1 | 溢出磁盘型 | group by/join 内存不足 |

```sql
SELECT ProfileEvents['FileOpen'] AS file_open,
       ProfileEvents['OSCPUWaitMicroseconds'] AS cpu_wait,
       ProfileEvents['ContextLockWaitMicroseconds'] AS lock_wait
FROM system.query_log WHERE query_id = '<目标query_id>';
```

## 第 3 步：归因（决策树）

`EXPLAIN indexes = 1 SELECT ...;` 然后按指标走决策树：

1. **Parts N/M 高（>0.5）** → WHERE 缺分区列条件（分区未裁剪）→ 5.2-5。
2. **Granules N/M 高（>0.3）或 Key Condition 缺失/unknown** → 过滤未命中排序键前缀，或键列被函数包裹 → 改写 WHERE / 调整排序键 → 5.2-1/5.2-3。
3. **裁剪都好但 read_bytes 大** → 读列过多（SELECT * / 宽行）→ 列裁剪 → 5.2-2。
4. **裁剪好、列少、仍慢** → 聚合/JOIN/去重本身贵：count(DISTINCT)→uniq、JOIN 慢→字典/grace_hash、FINAL→argMax MV → 5.2-7~11。
5. **表级问题**：`system.parts` 分区 part>10（碎片，写入侧问题）；`system.merges`/`system.mutations` 堆积（后台重写挤占资源）。

## 第 4 步：改写（按优先级套手段）

按规范 5.2 优先级表从上到下：补 WHERE/命中排序键前缀 → 列裁剪 → 键列函数改区间 → 跳数索引 → 分区裁剪 → 投影 → MV 预聚合 → 字典 → argMax MV 替代 FINAL → query cache → grace_hash。每条改写给出预期收益依据（裁剪率、扫描量），不凭感觉。

## 第 5 步：验证（前后对比）

```sql
EXPLAIN ANALYZE SELECT <改写后查询>;   -- 真实执行的耗时/行数
```

对比改写前后的 `elapsed`、`read_rows`、`read_bytes`；相同 `SETTINGS max_threads=8` 保证可比。上线后观察 `system.query_log` 同 pattern 查询的 duration 分位数（P95）变化。

## 第 6 步：固化（防复发）

1. **查询级熔断**：`SETTINGS max_execution_time = 30, max_rows_to_read = 1e9` 写进慢查询模板。
2. **账号配额**：只读账号 + `max_rows_to_read`/`max_execution_time` profile（规范 4.4-3）。
3. **结构固化**：高频模式沉淀为跳数索引/投影/MV（EXPLAIN indexes=1 验证后保留）。
4. **监控**：`query_duration_ms > 5s` 告警；part 碎片与 mutation 堆积巡检 SQL 见 build_diagnostics。
5. **回归**：把改写前后查询与 EXPLAIN 存档（query_id + log_comment 标记），避免他人改回坏写法。
