# 建表场景模板（4 场景）

与 Agent 工具 `ddl_codegen` 一致；替换占位列即可用。生成后按 DDL 检查清单自检。

## 1. append_log 追加写明细表

```sql
CREATE TABLE dwd.event_log
(
    tenant_id  UInt32 COMMENT '维度-tenant_id',
    event_type UInt32 COMMENT '维度-event_type',
    event_time DateTime COMMENT '事件时间(本地时区)',
    user_id    UInt64 COMMENT '用户ID',
    amount     Decimal(18, 2) COMMENT '金额',
    status     LowCardinality(String) COMMENT '状态',
    payload    String COMMENT '扩展JSON',
    INDEX idx_user user_id TYPE bloom_filter(0.01) GRANULARITY 1
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (tenant_id, event_type, event_time)
TTL event_time + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;
```

要点：排序键 = 维度(低基数在前) → 时间(最后)；分区粒度对齐 TTL（TTL ≤7 天改 toYYYYMMDD）；高基数非键过滤列配 bloom_filter。

## 2. cdc_upsert CDC 入湖/去重

```sql
CREATE TABLE ods.orders_cdc
(
    order_id   UInt32 COMMENT '业务主键-order_id',
    event_time DateTime COMMENT '业务时间',
    updated_at DateTime COMMENT 'CDC更新时间(单调版本列)',
    is_deleted UInt8 DEFAULT 0 COMMENT '软删标记',
    amount     Decimal(18, 2) COMMENT '金额',
    status     LowCardinality(String) COMMENT '状态',
    raw        String COMMENT '原始报文'
)
ENGINE = ReplacingMergeTree(updated_at)
PARTITION BY toYYYYMM(event_time)
ORDER BY (order_id, event_time)
SETTINGS index_granularity = 8192, min_age_to_force_merge_seconds = 600;
```

要点：去重键 = ORDER BY（业务主键必须在）；版本列单调递增；高频取最新用 MV+argMax 或 `LIMIT 1 BY order_id ORDER BY updated_at DESC`；查询时 FINAL 仅低频。

## 3. collapsing 增减回撤

```sql
CREATE TABLE dws.metric_collapsing
(
    tenant_id  UInt32 COMMENT '维度-tenant_id',
    event_time DateTime COMMENT '业务时间',
    metric     Decimal(18, 4) COMMENT '度量值(可正可负)',
    sign       Int8 COMMENT '折叠标记 +1/-1'
)
ENGINE = CollapsingMergeTree(sign)
PARTITION BY toYYYYMM(event_time)
ORDER BY (tenant_id, event_time);
```

要点：写入成对 +1/-1 行；查询必须 `SUM(sign * metric)`；乱序到达用 VersionedCollapsingMergeTree(sign, ver)。

## 4. agg_rollup 预聚合汇总（表 + MV + 查询）

```sql
CREATE TABLE dwd.mv_event_log
(
    tenant_id UInt32,
    event_type UInt32,
    event_time DateTime,
    cnt AggregateFunction(count),
    amt_sum AggregateFunction(sum, Decimal(18, 2)),
    uv AggregateFunction(uniq, UInt64)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (tenant_id, event_type, event_time);

CREATE MATERIALIZED VIEW dwd.mv_event_log_mv
TO dwd.mv_event_log AS
SELECT tenant_id, event_type,
       toStartOfHour(event_time) AS event_time,
       countState() AS cnt, sumState(amount) AS amt_sum, uniqState(user_id) AS uv
FROM dwd.event_log
GROUP BY tenant_id, event_type, event_time;

-- 查询：读取端用 *Merge 补齐未合并状态
SELECT tenant_id, event_type, event_time,
       countMerge(cnt) AS cnt, sumMerge(amt_sum) AS amt, uniqMerge(uv) AS uv
FROM dwd.mv_event_log
WHERE event_time >= now() - INTERVAL 7 DAY
GROUP BY tenant_id, event_type, event_time;
```

要点：MV 仅随 INSERT 触发（UPDATE/DELETE 不传播）；POPULATE 丢增量，用停写窗口回填；仪表盘查聚合表、ad-hoc 查明细表。
