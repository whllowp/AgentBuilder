---
title: JOIN 优化与字典（Dictionary）最佳实践
keywords: JOIN hash join_algorithm grace_hash partial_merge full_sorting parallel_hash GLOBAL JOIN 字典 dictGet dictGetOrDefault 维表 join_use_nulls 谓词下推 analyzer 小表右表
source: ClickHouse 官方《Minimize and Optimize JOINs》《How ClickHouse Became Fast at Joins》+ Altinity KB + 《clickhouse开发规范.md》第 4.2 节
---

# JOIN 优化与字典最佳实践

## JOIN 基本规则

1. 小表放右表：默认 hash 算法对右表建哈希表。
2. JOIN 前两表都先过滤/聚合收敛行数与列数（v24.4+ analyzer 谓词下推最高 10x，仍应显式收敛）。
3. 实时/交互查询 JOIN 数 ≤ 3~4（官方建议）；更多表在 ETL 层预关联成宽表或用字典。
4. 关联键类型必须一致（UInt64 vs String 隐式转换破坏 hash 分发）。
5. Distributed 表下用 `GLOBAL JOIN` / `GLOBAL IN` 防右表子查询全量分发到每个分片。

## JOIN 算法选择（join_algorithm）

- `hash`（默认）：右表能进内存时最快；`parallel_hash` 多线程分桶建表。
- `grace_hash`：右表大、内存不足时分页溢出磁盘，推荐大 JOIN 默认备选。
- `partial_merge`：左大右更大的经典场景，右表排序分块落盘。
- `full_sorting_merge`：两表都按键有序。
- 多算法写法：`join_algorithm = 'hash,grace_hash'` 自动降级。

## 字典（Dictionary）替代维度 JOIN

1. 维度表特征：小、更新慢、等值关联 → 用 `dictGet('dim', 'attr', key)` / `dictGetOrDefault`。
2. 官方实测：JOIN 2.3s → 字典 JOIN 1.36s → dictGet 0.86s（约 3 倍）。
3. 字典源有重复键时**静默取最后一条**——构建前必须去重，否则维度值错乱。
4. 内存评估：复杂 key + range 字典最耗内存；`LAYOUT` 按基数选 `flat`（id ≤ 50 万）/`hashed`/`complex_key_hashed`/`cached`；刷新 `LIFETIME(MIN 600 MAX 900)` 平衡新鲜度与刷新开销。
5. 监控 `system.dictionaries` 的加载状态与异常。

## 典型改写

```sql
-- 慢：大表 JOIN 维表取名称
SELECT o.*, d.city_name FROM orders o JOIN dim_city d ON o.city_id = d.id;
-- 快：字典点查
SELECT o.*, dictGet('dim_city_dict', 'city_name', o.city_id) FROM orders o;
```
