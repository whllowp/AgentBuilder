---
title: 物化视图（MV）与投影（Projection）的取舍
keywords: 物化视图 MATERIALIZED VIEW 投影 PROJECTION 预聚合 argMax AggregatingMergeTree AggregateFunction force_optimize_projection POPULATE query cache TTL 触发时机
source: ClickHouse 官方博客《Top 10 Best Practice Tips》+ 《clickhouse开发规范.md》第 5.3 节
---

# 物化视图（MV）与投影（Projection）的取舍

## 物化视图（MATERIALIZED VIEW）

1. 触发时机：**仅 INSERT 触发**。UPDATE/DELETE 不传播；多表 JOIN 的 MV 只随左表触发——这是正确性边界，改维度表不会刷新已聚合结果。
2. 典型用法：明细表 → 预聚合表（`SummingMergeTree` / `AggregatingMergeTree` + `AggregateFunction` 状态类型），仪表盘查聚合表、ad-hoc 查明细表。
3. 去重场景：MV 里用 `argMax(col, version)` 物化"每键最新值"，替代查询时 FINAL（官方实测 argMax 1.0s vs FINAL 1.5s）。
4. `POPULATE` 只回填创建时刻已存在的数据，期间的增量会丢——生产用"新 MV + 手工回填 + 切换"或双写窗口。
5. 适合：查询模式固定、要多消费者共享、需要跨表落地的预聚合。

## 投影（PROJECTION）

1. 同一张表内的"另类排序副本"（`ORDER BY` 不同）或预聚合副本，查询优化器自动匹配。
2. 用 `force_optimize_projection = 1` 强制校验投影命中，防止默默回退全表扫。
3. 代价：写放大（每次 INSERT 维护多份 part 内数据）、part 内空间；删除/重建投影是轻量操作（相比改 ORDER BY）。
4. 适合：一表多查询模式（一套按租户查、一套按时间查）、对查询透明、轻量聚合。

```sql
ALTER TABLE events ADD PROJECTION p_by_user
(SELECT user_id, count(), sum(amount) GROUP BY user_id);
```

## 取舍决策

- 查询模式不稳定、要物化到独立表给多消费者 → MV。
- 仅换排序/轻量聚合、希望对查询透明 → 投影。
- 禁止对同一查询模式 MV + 投影叠加。
- 高并发重复报表还可叠加 query cache（`use_query_cache = 1`）。
