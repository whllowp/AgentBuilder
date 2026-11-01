---
title: 查询诊断与优化 SOP（query_log/EXPLAIN/PREWHERE/读写顺序）
keywords: 查询优化 慢查询 query_log EXPLAIN EXPLAIN ANALYZE PIPELINE ProfileEvents granules parts PREWHERE WHERE 下推 SELECT* 列裁剪 keyset 分页 LIMIT OFFSET uniq 近似 采样 SAMPLE max_execution_time 优化手段
source: ClickHouse 官方《查询优化指南》+ 《clickhouse开发规范.md》第 4/5 节
---

# 查询诊断与优化 SOP

## 诊断流程

1. `system.query_log`（type='QueryFinish'）按 `query_duration_ms` 排序找慢查询；看 `read_rows/read_bytes` 定位扫描量；`ProfileEvents` 区分瓶颈：FileOpen/PagesRead 高 → I/O；OCPUWait/ContextLock 高 → 排队/锁；OSReadBytes 与磁盘相关。
2. `EXPLAIN`：默认 PLAN；`EXPLAIN PLAN indexes=1` 看 `Parts: N/M`（分区裁剪）与 `Granules: N/M`（主键裁剪）；`EXPLAIN PIPELINE` 看并行度；`EXPLAIN ANALYZE` 真实执行统计。
3. 表健康：`system.parts`（active=1，分区 part > 10 碎片预警）、`system.merges`、`system.mutations`。
4. 任何建议必须附"预期收益依据"（granule 裁剪率、part 裁剪率、列数减少量）。

## 查询改写规则

1. 禁止 `SELECT *`：列存按列读，明确列清单（10x 级差异常见）。
2. 大表查询必带 WHERE，过滤条件命中排序键前缀或分区键。
3. 键列不套函数：`WHERE toDate(ts)='2026-09-01'` → `WHERE ts >= '2026-09-01' AND ts < '2026-09-02'`；同理 `toYYYYMM`、`substr(key)`、`col+1`、类型不一致比较。
4. PREWHERE：`optimize_move_to_prewhere` 默认开；高选择性（过滤 90%+ 行）条件可手工 `PREWHERE` 强制先行。
5. 分页：禁止 `LIMIT 100000, 20` 大偏移；keyset 分页 `WHERE (id, ts) > (last_id, last_ts) ORDER BY id, ts LIMIT 20`。
6. 高基数 `count(DISTINCT)` → `uniq()`（误差 <1%）/ `uniqCombined()`；分位数用 `quantileTDigest`。
7. `LIKE '%xxx%'` 前导通配是全块扫描 → tokenbf_v1/ngrambf_v1 索引列、`hasToken()`、倒排索引。
8. 探索分析用 `SAMPLE 0.1`（表需声明 `SAMPLE BY`）。

## 优化手段优先级（投入产出排序）

| 优先级 | 手段 | 症状 |
|--------|------|------|
| 1 | 补 WHERE / 命中排序键前缀 | Granules N/M ≈ 1 |
| 2 | 列裁剪 | read_bytes >> 结果 |
| 3 | 键列函数改区间 | Key Condition unknown |
| 4 | 跳数索引 | 非键列高选择性过滤 |
| 5 | 分区裁剪 | Parts 全读 |
| 6 | 投影 | 一表多查询模式 |
| 7 | MV 预聚合 | 固定报表重复聚合 |
| 8 | 字典替代 JOIN | JOIN 慢、维表小 |
| 9 | argMax MV 替代 FINAL | Replacing 查询慢 |
| 10 | query cache | 高并发重复报表 |
| 11 | grace_hash JOIN | 大 JOIN OOM |

## 资源与配额

- 生产查询设 `max_execution_time`；交互查询加 `max_bytes_before_external_group_by/sort`。
- 只读账号 + `max_rows_to_read` 熔断；SETTINGS 写在查询级。
- `max_threads` 匹配 CPU（小查询 4~8）；标记 `query_id`/`log_comment` 便于追踪。
