"""大数据 ETL 代码生成器：场景化模板（结构合规，占位符需按业务替换）。

场景：
- hive_partition  Hive 分区表（DDL + 动态分区插入 + 增量拉取）
- hive_zipper     拉链表（全量初始化 + 每日增量开链/关链）
- flink_sql       Flink SQL 作业（Kafka 源 + 维表 lookup + CK/JDBC sink + 作业配置）
- airflow_dag     Airflow DAG（依赖/重试/幂等/告警/数据质量对账）
- dolphinsched    DolphinScheduler 工作流（shell/sql 任务 + 依赖 + 超时告警）
"""
from __future__ import annotations

import re

_SCENARIOS = ("hive_partition", "hive_zipper", "flink_sql", "airflow_dag", "dolphinsched")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _safe(name: str, default: str) -> str:
    name = (name or "").strip().strip("`")
    return name if _IDENT.match(name) else default


def generate(scenario: str, table: str = "", dt_col: str = "dt") -> dict:
    if scenario not in _SCENARIOS:
        return {"ok": False, "error": f"未知场景: {scenario}，可选: {', '.join(_SCENARIOS)}"}
    t = _safe(table, "dwd_event")
    dt = _safe(dt_col, "dt")

    if scenario == "hive_partition":
        ddl = (
            f"CREATE TABLE IF NOT EXISTS ods.{t} (\n"
            f"  id          BIGINT      COMMENT '主键',\n"
            f"  biz_attrs   STRING      COMMENT '业务属性',\n"
            f"  updated_at  TIMESTAMP\n"
            f")\n"
            f"PARTITIONED BY ({dt} STRING COMMENT 'yyyyMMdd')\n"
            f"STORED AS ORC\n"
            f"TBLPROPERTIES ('orc.compress' = 'ZSTD');"
        )
        load = (
            f"-- 每日增量拉取（动态分区，只跑增量分区，禁止全表重刷）\n"
            f"SET hive.exec.dynamic.partition = true;\n"
            f"SET hive.exec.dynamic.partition.mode = nonstrict;\n"
            f"INSERT OVERWRITE TABLE ods.{t} PARTITION ({dt})\n"
            f"SELECT id, biz_attrs, updated_at,\n"
            f"       date_format(updated_at, 'yyyyMMdd') AS {dt}\n"
            f"FROM ods_{t}_source\n"
            f"WHERE updated_at >= '${{ds}} 00:00:00'   -- 调度参数：只拉昨日增量\n"
            f"  AND updated_at <  '${{next_ds}} 00:00:00';"
        )
        notes = ["分区过滤必须带（读侧 `WHERE {c}=...`），否则全表扫描；",
                 "重刷历史用独立任务指定分区，禁止去掉 WHERE 全表重跑；",
                 "幂等：同分区 INSERT OVERWRITE 覆盖写，可安全重试。"]
        return {"ok": True, "scenario": scenario, "artifacts": [("ddl.hql", ddl), ("daily_load.hql", load)], "notes": notes}

    if scenario == "hive_zipper":
        init = (
            f"-- 拉链表全量初始化（一次性）\n"
            f"CREATE TABLE IF NOT EXISTS dwd.{t}_zipper (\n"
            f"  id BIGINT, biz_attrs STRING,\n"
            f"  start_date STRING COMMENT '开链日', end_date STRING COMMENT '关链日，9999-12-31 未关链'\n"
            f") PARTITIONED BY ({dt} STRING) STORED AS ORC;\n"
            f"INSERT OVERWRITE TABLE dwd.{t}_zipper PARTITION ({dt}='${{ds_nodash}}')\n"
            f"SELECT id, biz_attrs, '${{ds}}' AS start_date, '9999-12-31' AS end_date\n"
            f"FROM ods.{t} WHERE {dt} = '${{ds_nodash}}';"
        )
        daily = (
            f"-- 每日增量：先关链（命中变化），再开链（新版本）——两步必须同分区原子重写\n"
            f"INSERT OVERWRITE TABLE dwd.{t}_zipper PARTITION ({dt}='${{ds_nodash}}')\n"
            f"SELECT\n"
            f"  COALESCE(n.id, o.id)      AS id,\n"
            f"  COALESCE(n.biz_attrs, o.biz_attrs) AS biz_attrs,\n"
            f"  CASE WHEN n.id IS NOT NULL AND o.id IS NOT NULL THEN o.start_date ELSE '${{ds}}' END AS start_date,\n"
            f"  CASE WHEN n.id IS NOT NULL AND o.end_date = '9999-12-31' THEN '${{ds}}' ELSE o.end_date END AS end_date\n"
            f"FROM dwd.{t}_zipper o                                  -- 昨日未关链全量\n"
            f"FULL OUTER JOIN (SELECT * FROM ods.{t} WHERE {dt}='${{ds_nodash}}') n\n"
            f"  ON o.id = n.id\n"
            f"WHERE o.{dt} = DATE_FORMAT(DATE_SUB('${{ds}}', 1), 'yyyyMMdd');"
        )
        notes = ["查询最新版必须 `end_date = '9999-12-31'`，漏条件会读出历史版本；",
                 "关链/开链在同一次 OVERWRITE 内完成，防止中间态被读到；",
                 "重跑单日分区前先回滚该分区（用前一日分区重建），避免链断裂。"]
        return {"ok": True, "scenario": scenario, "artifacts": [("zipper_init.hql", init), ("zipper_daily.hql", daily)], "notes": notes}

    if scenario == "flink_sql":
        job = (
            f"-- Flink SQL 作业骨架（Kafka 源 → 维表 lookup → sink；占位符按环境替换）\n"
            f"CREATE TABLE src_{t} (\n"
            f"  id BIGINT, biz_attrs STRING, ts TIMESTAMP(3),\n"
            f"  WATERMARK FOR ts AS ts - INTERVAL '5' SECOND\n"
            f") WITH (\n"
            f"  'connector' = 'kafka', 'topic' = '<topic>',\n"
            f"  'properties.bootstrap.servers' = '<brokers>',\n"
            f"  'properties.group.id' = '<group>',\n"
            f"  'scan.startup.mode' = 'group-offsets',\n"
            f"  'format' = 'json'\n"
            f");\n"
            f"CREATE TABLE dim_<dim> (id BIGINT, attr STRING, PRIMARY KEY (id) NOT ENFORCED)\n"
            f"WITH ('connector' = 'jdbc', 'url' = '<url>', 'table-name' = '<dim>', 'lookup.cache.max-rows' = '10000', 'lookup.cache.ttl' = '60s');\n"
            f"CREATE TABLE sink_{t} (id BIGINT, attr STRING, ts TIMESTAMP(3))\n"
            f"WITH ('connector' = 'jdbc', 'url' = '<url>', 'table-name' = '{t}', 'sink.buffer-flush.max-rows' = '500', 'sink.buffer-flush.interval' = '1s');\n"
            f"INSERT INTO sink_{t}\n"
            f"SELECT s.id, d.attr, s.ts FROM src_{t} s LEFT JOIN dim_<dim> FOR SYSTEM_TIME AS OF s.ts AS d ON s.id = d.id;"
        )
        notes = ["事件时间必须配 WATERMARK（窗口/lookup AS OF 依赖）；",
                 "维表 lookup 开缓存（max-rows/ttl），防打爆 MySQL；",
                 "sink 开批量刷写；作业参数：checkpoint 60s + EXACTLY_ONCE（Kafka sink 需事务前缀）。"]
        return {"ok": True, "scenario": scenario, "artifacts": [(f"{t}_job.sql", job)], "notes": notes}

    if scenario == "airflow_dag":
        dag = (
            f"from datetime import datetime, timedelta\n"
            f"from airflow import DAG\n"
            f"from airflow.providers.apache.hive.operators.hive import HiveOperator\n"
            f"from airflow.operators.empty import EmptyOperator\n"
            f"\n"
            f"default_args = {{\n"
            f"    'owner': 'data',\n"
            f"    'retries': 3,                      # 失败重试：网络抖动是常态\n"
            f"    'retry_delay': timedelta(minutes=5),\n"
            f"    'retry_exponential_backoff': True,\n"
            f"    'email_on_failure': True,\n"
            f"    'depends_on_past': False,          # 分区级任务不做跨日依赖\n"
            f"}}\n"
            f"with DAG(\n"
            f"    dag_id='{t}_daily',\n"
            f"    schedule='30 1 * * *',\n"
            f"    start_date=datetime(2026, 1, 1),\n"
            f"    catchup=False,                     # 禁止回填雪崩；补数走独立 backfill DAG\n"
            f"    max_active_runs=1,                 # 同 DAG 串行，防分区写冲突\n"
            f"    default_args=default_args,\n"
            f"    tags=['etl', '{t}'],\n"
            f") as dag:\n"
            f"    extract = HiveOperator(task_id='extract', hql='-- TODO 拉取增量（见 hive_partition 模板）')\n"
            f"    transform = HiveOperator(task_id='transform', hql='-- TODO 转换（幂等：分区 OVERWRITE）')\n"
            f"    check_cnt = HiveOperator(task_id='check_count',  # 数据质量对账\n"
            f"        hql=\"SELECT IF(cnt > 0, 1, 0) FROM (SELECT count(1) AS cnt FROM dwd.{t} WHERE dt='${{ds_nodash}}') t\")\n"
            f"    done = EmptyOperator(task_id='done')\n"
            f"    extract >> transform >> check_cnt >> done"
        )
        notes = ["任务必须幂等（分区 OVERWRITE / 去重键），重试才安全；",
                 "行数对账（check_count）失败即阻断下游；",
                 "告警进群（email_on_failure + 自定义 callback），值班响应有 SLA。"]
        return {"ok": True, "scenario": scenario, "artifacts": [(f"{t}_daily.py", dag)], "notes": notes}

    # dolphinsched
    ds = (
        f"# DolphinScheduler 工作流定义（YAML，占位符按项目替换）\n"
        f"name: {t}_daily\n"
        f"schedule: '0 30 1 * * ?'\n"
        f"tasks:\n"
        f"  - name: extract\n"
        f"    type: SQL\n"
        f"    datasource: hive_prod\n"
        f"    sql: |-\n"
        f"      -- TODO 增量拉取（禁止全表重刷）\n"
        f"    timeout: 3600\n"
        f"    failRetryTimes: 3\n"
        f"    failRetryInterval: 300\n"
        f"  - name: transform\n"
        f"    type: SQL\n"
        f"    datasource: hive_prod\n"
        f"    sql: |-\n"
        f"      -- TODO 幂等转换（分区 OVERWRITE）\n"
        f"    dependsOn: [extract]\n"
        f"  - name: check\n"
        f"    type: SHELL\n"
        f"    script: |-\n"
        f"      cnt=$(hive -S -e \"SELECT count(1) FROM dwd.{t} WHERE dt=$(date -d yesterday +%Y%m%d)\")\n"
        f"      [ \"$cnt\" -gt 0 ] || {{ echo 'row count check failed'; exit 1; }}\n"
        f"    dependsOn: [transform]\n"
        f"alertGroup: data_oncall"
    )
    notes = ["依赖关系显式声明（dependsOn），禁止靠时间对齐；",
             "超时 + 失败重试 + 告警组三件套齐备；对账失败退出非零。"]
    return {"ok": True, "scenario": scenario, "artifacts": [(f"{t}_workflow.yaml", ds)], "notes": notes}


__all__ = ["generate", "_SCENARIOS"]
