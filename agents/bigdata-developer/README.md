# 大数据开发 Agent（bigdata-developer）

## 定位

大数据管道代码生成与审查：Hive 分区表与增量拉取、拉链表（SCD2 开链/关链）、Flink SQL 作业、Airflow DAG、DolphinScheduler 工作流。设计底线：**幂等、增量、可重试、有对账**。**已实现 v0.1**：5 场景合规模板（生成即通过自检）+ 8 条 ETL 规则静态审查 + 上线检查单。

## 使用方式

```bash
python agents/bigdata-developer/src/bigdata_agent/cli.py "帮我写订单拉链表，表名 dwd_order" --offline
cat job.sql | python agents/bigdata-developer/src/bigdata_agent/cli.py - --offline   # 只审查
cd agents/bigdata-developer && python -m pytest tests -q
```

## 实现结构

`tools/bigdata_tools/etl_codegen.py`（5 场景模板：hive_partition/hive_zipper/flink_sql/airflow_dag/dolphinsched）、`etl_review.py`（ETL-101~108：分区覆盖/SELECT* 直通/增量过滤/DAG 重试串行/对账/拉链 end_date/DROP 非 tmp）、`knowledge/etl-best-practices.md`、`src/bigdata_agent/`（场景识别 + 生成自检 + 审查，双模式）、`tests/`（13 用例）、`examples/`。

## 关联产物

ZCode 技能 `.agents/skills/bigdata-developer/`；破坏性 SQL 深检转 `../sql-danger-reviewer/`。
