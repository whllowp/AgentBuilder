"""慢 SQL 定位与诊断 SQL 生成器：产出六步 SOP 与可在用户库直接执行的系统表查询。

无需真实数据库连接；每条 SQL 标注所属 SOP 步骤。
"""
from __future__ import annotations

# 六步 SOP：发现 → 取证 → 归因 → 改写 → 验证 → 固化（详版见 knowledge/slow-query-troubleshooting.md）
_SOP = [
    {"no": 1, "name": "发现", "action": "用 system.query_log 找出慢查询（duration > 5s），看 read_rows/read_bytes 判断是扫描型还是资源型慢。"},
    {"no": 2, "name": "取证", "action": "读 ProfileEvents 分类瓶颈：FileOpen/OSRead 高=I/O 型；OCPUWait 高=CPU 型；ContextLock 高=排队型；external_aggregation=溢出磁盘型。"},
    {"no": 3, "name": "归因", "action": "EXPLAIN indexes=1 看三个指标：Parts N/M（分区裁剪）、Granules N/M（主键裁剪）、Key Condition（键条件是否 unknown），按决策树定位到索引/分区/列裁剪/聚合 JOIN 四类根因。"},
    {"no": 4, "name": "改写", "action": "按规范 5.2 优先级套手段：补 WHERE 命中排序键前缀 → 列裁剪 → 键列函数改区间 → 跳数索引 → 投影/MV → 字典 → argMax 替代 FINAL。"},
    {"no": 5, "name": "验证", "action": "EXPLAIN ANALYZE 对比改写前后的 elapsed/read_rows/read_bytes（相同 max_threads）；上线后观察 P95 变化。"},
    {"no": 6, "name": "固化", "action": "查询级熔断（max_execution_time/max_rows_to_read）、只读账号配额、高频模式沉淀为索引/投影/MV、duration>5s 告警与 part 碎片巡检。"},
]

_QUERIES = [
    {
        "name": "top_slow_queries",
        "title": "TOP 慢查询",
        "stage": 1,
        "sql": (
            "SELECT event_time, user, query_id, query_duration_ms,\n"
            "       read_rows, formatReadableSize(read_bytes) AS read_size,\n"
            "       formatReadableSize(memory_usage) AS mem, query\n"
            "FROM system.query_log\n"
            "WHERE type = 'QueryFinish' AND event_date >= today() - 3\n"
            "  AND query_duration_ms > 5000\n"
            "ORDER BY query_duration_ms DESC\n"
            "LIMIT 20;"
        ),
        "purpose": "第 1 步·发现：定位最慢查询；扫描量亿级=索引问题，扫描小但慢=锁/资源问题。",
    },
    {
        "name": "profile_events",
        "title": "瓶颈取证（ProfileEvents）",
        "stage": 2,
        "sql": (
            "SELECT ProfileEvents['FileOpen'] AS file_open,\n"
            "       ProfileEvents['OSCPUWaitMicroseconds'] AS cpu_wait_us,\n"
            "       ProfileEvents['ContextLockWaitMicroseconds'] AS lock_wait_us,\n"
            "       ProfileEvents['ExternalAggregationMergePartsWithSeconds'] AS ext_agg\n"
            "FROM system.query_log\n"
            "WHERE query_id = '<目标query_id>';"
        ),
        "purpose": "第 2 步·取证：I/O 型 / CPU 型 / 排队型 / 溢出磁盘型分类。",
    },
    {
        "name": "table_parts_health",
        "title": "分区 part 碎片健康度",
        "stage": 3,
        "sql": (
            "SELECT database, table, count() AS active_parts, sum(rows) AS rows,\n"
            "       countIf(active_parts_per_partition > 10) AS fragmented_partitions\n"
            "FROM (\n"
            "    SELECT database, table, partition, count() AS active_parts_per_partition, sum(rows) AS rows\n"
            "    FROM system.parts WHERE active\n"
            "    GROUP BY database, table, partition\n"
            ")\n"
            "GROUP BY database, table\n"
            "HAVING fragmented_partitions > 0 OR active_parts > 100\n"
            "ORDER BY active_parts DESC;"
        ),
        "purpose": "第 3 步·归因（表级）：part > 10/分区 或总 part > 100 预警碎片（写入侧问题）。",
    },
    {
        "name": "mutation_backlog",
        "title": "mutation 堆积",
        "stage": 3,
        "sql": (
            "SELECT database, table, mutation_id, is_done, create_time, latest_fail_reason\n"
            "FROM system.mutations\n"
            "WHERE is_done = 0\n"
            "ORDER BY create_time;"
        ),
        "purpose": "第 3 步·归因（表级）：mutation 堆积会持续重写 part 挤占资源（规范 3-5）。",
    },
    {
        "name": "validate_index_hit",
        "title": "索引命中验证模板",
        "stage": 5,
        "sql": (
            "EXPLAIN indexes = 1\n"
            "SELECT <列清单> FROM <表名>\n"
            "WHERE <待验证的过滤条件>;"
        ),
        "purpose": "第 5 步·验证：查看 Primary Key / Skip Indexes 的 Parts/Granules 裁剪效果。",
    },
    {
        "name": "async_insert_status",
        "title": "异步插入攒批状态",
        "stage": 3,
        "sql": (
            "SELECT event_date, count() AS flushes, avg(rows) AS avg_rows_per_flush\n"
            "FROM system.asynchronous_insert_log\n"
            "WHERE event_date >= today() - 3\n"
            "GROUP BY event_date\n"
            "ORDER BY event_date DESC;"
        ),
        "purpose": "第 3 步·归因（写入侧）：确认 async_insert 攒批生效（avg_rows 越大越有效）。",
    },
    {
        "name": "dictionary_health",
        "title": "字典加载健康度",
        "stage": 3,
        "sql": (
            "SELECT name, status, last_exception, element_count, bytes_allocated\n"
            "FROM system.dictionaries\n"
            "WHERE status != 'LOADED' OR last_exception != '';"
        ),
        "purpose": "第 3 步·归因：字典加载失败/重复键风险排查（规范 4.2-3）。",
    },
    {
        "name": "replacing_merge_parts_age",
        "title": "ReplacingMergeTree part 收敛",
        "stage": 6,
        "sql": (
            "SELECT name, value FROM system.merge_tree_settings\n"
            "WHERE name IN ('min_age_to_force_merge_seconds', 'min_age_to_force_merge_on_partition_only');"
        ),
        "purpose": "第 6 步·固化：确认强制合并参数（600s 收敛）已配置，降低 FINAL 查询代价（规范 2.9-4）。",
    },
]

_STAGE_NAMES = {s["no"]: s["name"] for s in _SOP}


def build_diagnostics(table: str = "") -> dict:
    """返回六步 SOP 与诊断 SQL 集合；table 非空时附带该表的规模与列统计查询。"""
    queries = [dict(q, stage_name=_STAGE_NAMES.get(q["stage"], "")) for q in _QUERIES]
    if table:
        t = table.replace("'", "")
        queries.insert(
            3,
            {
                "name": "table_stats",
                "title": f"表 {t} 的规模与压缩",
                "stage": 3,
                "stage_name": _STAGE_NAMES[3],
                "sql": (
                    f"SELECT partition, name, rows, formatReadableSize(data_compressed_bytes) AS compressed,\n"
                    f"       formatReadableSize(data_uncompressed_bytes) AS uncompressed\n"
                    f"FROM system.parts WHERE active AND table = '{t}'\n"
                    f"ORDER BY partition, name LIMIT 100;"
                ),
                "purpose": "第 3 步·归因：评估数据量级与压缩比，作为分区粒度与索引收益的依据。",
            },
        )
    return {
        "ok": True,
        "sop": _SOP,
        "queries": queries,
        "hint": "在目标库执行后把结果贴回来，我会基于数值按六步 SOP 给出量化优化建议。",
    }
