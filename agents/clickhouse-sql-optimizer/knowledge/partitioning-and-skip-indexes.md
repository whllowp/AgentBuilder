---
title: 分区策略与跳数索引（minmax/set/bloom_filter/tokenbf/ngrambf/inverted）
keywords: PARTITION BY 分区 裁剪 toYYYYMM toYYYYMMDD TTL part 碎片 过度分区 skip index 跳数索引 minmax set bloom_filter tokenbf ngrambf inverted 倒排 GRANULARITY
source: ClickHouse 官方《Choosing a Partitioning Key》《Top 10 Best Practices》+ 《clickhouse开发规范.md》第 2.4/2.7 节
---

# 分区策略与跳数索引

## 分区：数据管理手段，不是查询加速手段

1. 分区的价值：TTL 整区删除、按分区搬数/备份；查询加速主要靠 ORDER BY 稀疏索引。
2. 官方经验："超过几十个分区，多半是过度分区"。parts 之间**不跨分区合并**，过度分区 → part 碎片、合并压力、打开文件开销；官方实测月分区查询 20s vs 不分区 0.4s（慢 46 倍、加载内存多 55%）。
3. 粒度决策：
   - 有按天 TTL 的日志大表：`toYYYYMMDD(event_date)` 或 `toMonday(...)`，但单表日增量需 ≥ 数百万行；
   - 小表/无 TTL/数据量 < 10 亿行：不分区 `PARTITION BY tuple()` 往往更优；
   - 一般表按月 `toYYYYMM`；TTL ≤ 7 天时分区粒度对齐为日。
4. 监控：单表活跃分区 > 1000 告警；`system.parts` 中 `active=1` 分区 part 数 > 10 预警碎片。
5. 验证裁剪：`EXPLAIN` 看 `Parts: N/M`，N 应远小于 M；查询 WHERE 应含分区列。

## 跳数索引选型（DATA SKIP INDEX）

跳数索引按 granule 块（默认 8192 行 × GRANULARITY）存储元信息，读时跳过不满足的块。只加在**不在排序键中但常被过滤**的列。

| 类型 | 适用 | 示例 |
|------|------|------|
| `minmax` | 数值/时间，块内局部有序 | `INDEX idx_amt amount TYPE minmax GRANULARITY 2` |
| `set(N)` | 低基数等值/IN；`set(0)` 自动全存 | `INDEX idx_city city TYPE set(100)` |
| `bloom_filter(误判率)` | 高基数等值、数组 contains | `INDEX idx_uid user_id TYPE bloom_filter(0.01)` |
| `tokenbf_v1(...)` | 分词文本 `LIKE '%token%'` | 日志 message 列 |
| `ngrambf_v1(...)` | 子串 `LIKE '%片段%'` | URL、无空格文本 |
| `inverted` | 全文检索（v26.2 GA） | 新版文本检索首选 |

- 官方实测：`minmax` 过滤 `total_votes > 1000` 使扫描行数从 1.5 亿降到 2900 万（-80%）。
- GRANULARITY 从 1 起评估，默认 1；索引有写放大，单表建议 ≤ 5 个。
- 验证：`EXPLAIN indexes=1` 看 `granules` 过滤效果；无效索引删除。
- 排序键前缀列上再加跳数索引是浪费。

## EXPLAIN 验证示例

```sql
EXPLAIN indexes = 1
SELECT user_name FROM t_events WHERE amount > 1000;
-- 看 Primary Keys 部分 granules 与 Skip Indexes 部分
```
