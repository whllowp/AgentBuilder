---
name: bigdata-developer
description: 大数据开发技能。凡是用户要写/改 Hive 分区表与增量拉取、拉链表（SCD2 开链关链）、Flink SQL 实时作业、Airflow DAG、DolphinScheduler 工作流，或审查 ETL 代码的幂等性/增量过滤/调度重试/数据对账/拉链条件——都应使用本技能：场景化合规模板生成 + 8 条 ETL 规则静态审查 + 上线检查单。
---

# 大数据开发

生成并审查大数据管道代码，设计底线：**幂等、增量、可重试、有对账**。可执行实现在 `agents/bigdata-developer/`。

## 工作流

1. 生成（按场景关键词映射：拉链/scd→hive_zipper；flink/实时/维表→flink_sql；airflow/调度→airflow_dag；dolphinscheduler→dolphinsched；其余→hive_partition）：
   ```bash
   python agents/bigdata-developer/src/bigdata_agent/cli.py "帮我写订单拉链表，表名 dwd_order" --offline
   cat job.sql | python agents/bigdata-developer/src/bigdata_agent/cli.py - --offline   # 只审查
   ```
2. 生成结果与用户代码一律过 `etl_review` 自检（8 条规则）：
   - ETL-101 高危：INSERT OVERWRITE 无分区条件（全表覆盖）
   - ETL-102 中危：SELECT * 直通 INSERT
   - ETL-103 高危：增量任务缺时间过滤（无 ${ds}/分区条件）
   - ETL-104 高危：DAG 缺 retries
   - ETL-105 中危：缺数据质量对账
   - ETL-106 高危：拉链查询漏 end_date='9999-12-31'
   - ETL-107 中危：DAG 缺 max_active_runs/catchup 控制
   - ETL-108 高危：DROP 非 tmp 表（深检转 sql-danger-reviewer）
3. 输出附上线检查单：调度参数对齐 / 回滚方式 / 对账口径 / 告警组。

## 关键实践（详版 knowledge/etl-best-practices.md）

- 幂等：分区级 OVERWRITE；拉链关链/开链同一次 OVERWRITE 原子完成；
- 增量：必须带 `${ds}`/`${ds_nodash}` 或分区等值过滤，禁止全表重刷；
- 调度：retries≥3+退避、max_active_runs=1、catchup=False、对账失败阻断下游；
- Flink SQL：WATERMARK 必配、维表 lookup 开缓存、sink 批量刷写 + exactly-once。

## 约束

- 连接信息用 `<占位>`，不编造表结构；破坏性 SQL 提示转 sql-danger-reviewer。
