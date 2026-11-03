# 大数据开发报告

## 需求解析

- 场景：hive_zipper（按关键词推断；不符请补充描述）

## 代码

**zipper_init.hql**
```sql
-- 拉链表全量初始化（一次性）
CREATE TABLE IF NOT EXISTS dwd.dwd_order_zipper (
  id BIGINT, biz_attrs STRING,
  start_date STRING COMMENT '开链日', end_date STRING COMMENT '关链日，9999-12-31 未关链'
) PARTITIONED BY (dt STRING) STORED AS ORC;
INSERT OVERWRITE TABLE dwd.dwd_order_zipper PARTITION (dt='${ds_nodash}')
SELECT id, biz_attrs, '${ds}' AS start_date, '9999-12-31' AS end_date
FROM ods.dwd_order WHERE dt = '${ds_nodash}';
```

**zipper_daily.hql**
```sql
-- 每日增量：先关链（命中变化），再开链（新版本）——两步必须同分区原子重写
INSERT OVERWRITE TABLE dwd.dwd_order_zipper PARTITION (dt='${ds_nodash}')
SELECT
  COALESCE(n.id, o.id)      AS id,
  COALESCE(n.biz_attrs, o.biz_attrs) AS biz_attrs,
  CASE WHEN n.id IS NOT NULL AND o.id IS NOT NULL THEN o.start_date ELSE '${ds}' END AS start_date,
  CASE WHEN n.id IS NOT NULL AND o.end_date = '9999-12-31' THEN '${ds}' ELSE o.end_date END AS end_date
FROM dwd.dwd_order_zipper o                                  -- 昨日未关链全量
FULL OUTER JOIN (SELECT * FROM ods.dwd_order WHERE dt='${ds_nodash}') n
  ON o.id = n.id
WHERE o.dt = DATE_FORMAT(DATE_SUB('${ds}', 1), 'yyyyMMdd');
```

## 设计要点

- 查询最新版必须 `end_date = '9999-12-31'`，漏条件会读出历史版本；
- 关链/开链在同一次 OVERWRITE 内完成，防止中间态被读到；
- 重跑单日分区前先回滚该分区（用前一日分区重建），避免链断裂。

## 审查结果（模板自检）

- 发现 1 处：中危1
- 🟡 [ETL-105] 调度缺数据质量对账（count/主键校验）：加 check_count / 对账任务，失败阻断下游

## 上线检查单

- 调度参数：${ds}/${ds_nodash} 与分区对齐；补数走独立 backfill；
- 回滚：分区级用前一日分区重建；拉链单日重跑先回滚该分区；
- 对账：行数源 vs 目标 + 主键唯一性，失败即阻断下游；
- 告警：失败进值班群，超时与重试参数已内置模板。

---
*本报告由 bigdata-developer 离线管线生成（未调用 LLM）。*