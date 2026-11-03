---
title: 大数据 ETL 最佳实践（幂等/增量/拉链/对账/调度）
keywords: ETL 幂等 重试 回滚 分区 增量 拉链表 开链 关链 数据质量 对账 调度 Airflow DolphinScheduler 依赖 告警 Hive Flink SQL
source: 数仓工程实践共识 + Hive/Flink/Airflow 官方文档要点
---

# 大数据 ETL 最佳实践

## 幂等（可安全重试的第一原则）

1. 分区级 `INSERT OVERWRITE`（同分区覆盖写）是 Hive 侧幂等的默认形态；
2. 追加表用去重键（主键 + 批次号）+ 重复写入容忍或先删后插；
3. Flink sink 开幂等/事务（upsert 或 exactly-once + 事务前缀）；
4. 重跑单日分区前先回滚该分区（用前一日重建），避免链式污染。

## 增量与分区

1. 增量拉取必须带调度参数过滤（`${ds}`/`${ds_nodash}` 或分区等值），禁止全表重刷；
2. 读侧查询必须带分区过滤，否则全表扫描；
3. 重刷历史走独立任务 + 显式分区列表，评审后执行。

## 拉链表（SCD2）

1. 结构：`start_date`（开链）/ `end_date`（关链，`9999-12-31` = 当前版本）；
2. 每日增量：命中变化则关链（`end_date = ${ds}`），新版本开链；两步放同一次 OVERWRITE 原子完成；
3. 查询最新版必须 `end_date = '9999-12-31'`，漏条件读出历史版本（正确性事故）。

## 数据质量对账

1. 行数对账（源 vs 目标，偏差阈值告警）+ 主键唯一性抽检；
2. 对账失败即阻断下游（任务非零退出），不允许"先跑完再说"；
3. 关键金额类指标加波动率校验（环比 >50% 告警）。

## 调度（Airflow / DolphinScheduler）

1. 依赖显式声明，禁止靠时间对齐；
2. `retries >= 3` + 指数退避；超时必须有（防资源挂死）；
3. `max_active_runs=1`（分区写冲突防护）+ `catchup=False`（防回填雪崩，补数走独立 backfill）；
4. 告警进值班群，失败 SLA 响应。

## Flink SQL 作业要点

1. 事件时间必须配 WATERMARK（窗口与 lookup AS OF 依赖）；
2. 维表 lookup 开缓存（max-rows/ttl），防打爆外部库；
3. sink 开批量刷写；checkpoint 60s + exactly-once（Kafka 事务前缀）。
