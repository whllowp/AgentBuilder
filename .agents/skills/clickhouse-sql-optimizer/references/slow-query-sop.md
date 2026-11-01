# 慢 SQL 定位与优化六步 SOP

来源：知识库 `slow-query-troubleshooting.md` + 规范 5.1。详版含完整 SQL。

## 第 1 步 发现：找到慢查询

```sql
SELECT event_time, user, query_id, query_duration_ms,
       read_rows, formatReadableSize(read_bytes) AS read_size,
       formatReadableSize(memory_usage) AS mem, query
FROM system.query_log
WHERE type = 'QueryFinish' AND event_date >= today() - 3
  AND query_duration_ms > 5000
ORDER BY query_duration_ms DESC LIMIT 20;
```

判读：扫描亿级行才慢=索引问题；扫描小仍慢=锁/资源问题；memory_usage 高=内存型。

## 第 2 步 取证：瓶颈分类（ProfileEvents）

| 信号 | 含义 |
|------|------|
| `FileOpen`/`OSReadChars` 高 | I/O 型 → 列裁剪/压缩/索引 |
| `OCPUWait`/`OCPUVirtualTime` 高 | CPU 型 → 聚合/正则/字符串处理 |
| `ContextLock` 等待高 | 排队/锁型 → 并发限流/长事务 |
| `external_aggregation/sort = 1` | 溢出磁盘型 → 内存不足 |

## 第 3 步 归因：EXPLAIN 三指标决策树

`EXPLAIN indexes = 1 SELECT ...;`

1. **Parts N/M > 0.5** → WHERE 缺分区列条件（补分区裁剪）
2. **Granules N/M > 0.3 或 Key Condition 缺失/unknown** → 过滤未命中排序键前缀 / 键列被函数包裹（改写 WHERE 或调排序键）
3. **裁剪好但 read_bytes 大** → SELECT * / 宽行（列裁剪）
4. **裁剪好、列少、仍慢** → 聚合/JOIN/去重贵：count(DISTINCT)→uniq、JOIN→字典/grace_hash、FINAL→argMax MV
5. **表级**：system.parts 分区 part>10（碎片）；system.mutations 堆积（后台重写挤资源）

## 第 4 步 改写：按优先级套手段

补 WHERE/命中排序键 → 列裁剪 → 键列函数改区间 → 跳数索引 → 分区裁剪 → 投影 → MV 预聚合 → 字典 → argMax MV 替代 FINAL → query cache → grace_hash。每条附预期收益依据。

## 第 5 步 验证：前后对比

```sql
EXPLAIN ANALYZE SELECT <改写后查询>;  -- 相同 max_threads 下对比 elapsed/read_rows/read_bytes
```

上线后观察 system.query_log 同 pattern 的 P95 变化。

## 第 6 步 固化：防复发

1. 查询级熔断：`SETTINGS max_execution_time=30, max_rows_to_read=1e9`
2. 只读账号 + max_rows_to_read/max_execution_time profile
3. 高频模式沉淀为跳数索引/投影/MV（EXPLAIN indexes=1 验证后保留）
4. 监控：duration>5s 告警；part 碎片与 mutation 堆积巡检
5. 改写前后查询与 EXPLAIN 存档（query_id + log_comment 标记）
