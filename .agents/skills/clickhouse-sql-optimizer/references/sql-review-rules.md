# SQL 审查规则（14 条）与改写示例

来源：《clickhouse开发规范.md》第 3/4 章。级别：❌ error / ⚠️ warning / ℹ️ info。

## 1. SELECT *（❌ 规范 4.1-1）

列存按列读，明确列清单（官方 10x 级差异常见）。

```sql
-- 差
SELECT * FROM events WHERE tenant_id = 3;
-- 好
SELECT event_type, count() FROM events WHERE tenant_id = 3 GROUP BY event_type;
```

## 2. 无 WHERE 的 SELECT（⚠️ 规范 4.1-2）

大表查询必带 WHERE 且命中排序键前缀/分区键；纯聚合走预聚合表（MV/投影）。

## 3. WHERE 中对键列套函数（⚠️ 规范 4.1-3）

表结构未知时措辞为"若该列在排序键/分区键上"。函数使 Key Condition 变 unknown。

```sql
-- 差
WHERE toDate(create_time) = '2026-09-01'
-- 好：半开区间
WHERE create_time >= '2026-09-01 00:00:00' AND create_time < '2026-09-02 00:00:00'
```

同族：`toYYYYMM(...)`、`substr(key,...)`、`col + 1`、键列类型不一致比较。

## 4. 大偏移分页（⚠️ 规范 4.1-4，阈值 offset ≥ 1000）

```sql
-- 差
ORDER BY order_id LIMIT 100000, 20
-- 好：keyset 分页
WHERE (order_id, create_time) > (:last_id, :last_ts) ORDER BY order_id, create_time LIMIT 20
```

## 5. FINAL（ℹ️ 规范 2.9-1/4.3-1）

查询时读更多数据且限制下推（官方 1.5 亿行实测 FINAL 1.5s vs argMax 1.0s）。高频报表改 MV+argMax 或 `LIMIT 1 BY key ORDER BY version DESC`；低频后台任务可保留。

## 6. LIKE 前导通配（⚠️ 规范 4.1-8）

`LIKE '%xxx%'` 全块扫描。建 tokenbf_v1（分词）/ngrambf_v1（子串）跳数索引并配 `hasToken()`；v26.2+ 可用 inverted 倒排索引。前缀匹配 `LIKE 'web-%'` 不算违规。

## 7. 精确去重（ℹ️ 规范 4.1-7）

`count(DISTINCT x)` / `uniqExact` 基数上亿时 → `uniq()`（误差<1%，内存恒定）/ `uniqCombined()`；分位数 → `quantileTDigest`。

## 8. JOIN 数量过多（⚠️ 规范 4.2-2，阈值 ≥4 个）

交互查询 ≤3~4 个；ETL 层预关联宽表或维度小表改字典。

## 9. 逗号连接（⚠️ 规范 4.2-1）

`FROM a, b` 无 JOIN 条件。显式 `JOIN ... ON`，让 v24.4+ 谓词下推生效。

## 10. IN (SELECT ...) 子查询（ℹ️ 规范 4.2-5）

Distributed 下改 `GLOBAL IN`，或右侧物化；右表大时评估 grace_hash JOIN。

## 11. ORDER BY 无 LIMIT（ℹ️ 规范 4.1-6）

结果集大时加 LIMIT；命中排序键时 `optimize_read_in_order` 免排序；确需全量排序评估 `max_bytes_before_external_sort`。

## 12. mutation 当常规 API（⚠️ 规范 2.8-3/3-5）

`ALTER TABLE ... DELETE/UPDATE` 是后台重写整个 part。日常少量删除用轻量 `DELETE FROM t WHERE ...`；批量重写放低峰 + `mutations_sync=0` + `system.mutations` 监控。注意：`DELETE FROM`（轻量删除）不算违规。

## 13. 单行 VALUES 插入（❌ 规范 3-1/3-2）

```sql
-- 差（Too many parts 风险）
INSERT INTO t (a, b) VALUES (1, 'x');
-- 好：多行批量（≥ 数千行更佳），间隔 ≥ 1s
INSERT INTO t (a, b) VALUES (1, 'x'), (2, 'y'), ...;
-- 客户端无法攒批：SETTINGS async_insert = 1, wait_for_async_insert = 1
```

## 14. JOIN 通用（规范 4.2）

- 小表放右表（默认 hash 对右表建哈希表）；JOIN 前两侧先过滤/聚合收敛。
- 维表（小、更新慢、等值关联）优先字典：`dictGet('dim_dict', 'attr', key)`（官方实测 JOIN 2.3s → dictGet 0.86s）。字典源重复键静默取最后一条，构建前去重。
- 大右表：`join_algorithm = 'grace_hash'` 或 `'partial_merge'`，或 `'hash,grace_hash'` 自动降级。
- 关联键类型必须一致；Distributed 下用 `GLOBAL JOIN`/`GLOBAL IN`。

## 诊断验证模板

```sql
EXPLAIN indexes = 1 SELECT <列清单> FROM <表> WHERE <条件>;   -- 看 Parts/Granules 裁剪

SELECT event_time, query_duration_ms, read_rows, formatReadableSize(read_bytes) AS rb, query
FROM system.query_log
WHERE type = 'QueryFinish' AND event_date >= yesterday()
ORDER BY query_duration_ms DESC LIMIT 20;                     -- TOP 慢查询
```
