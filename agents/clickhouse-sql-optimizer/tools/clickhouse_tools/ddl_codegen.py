"""建表 DDL 代码生成器：按场景产出符合《clickhouse开发规范.md》第 2 章的建表模板。

场景（scenario）：
- append_log   追加写明细表（MergeTree，月分区 + TTL，维度前/时间后的排序键）
- cdc_upsert   CDC 入湖/Upsert（ReplacingMergeTree(updated_at) + is_deleted 软删）
- collapsing   增减回撤（CollapsingMergeTree(sign)）
- agg_rollup   预聚合汇总（AggregatingMergeTree + 目标物化视图）

模板中的列均为示例占位，生成后按业务替换；所有模板的结构（引擎/排序键/分区/TTL）直接合规，
生成结果可再交给 advise_ddl 复核（离线管线自动做这一步）。
"""
from __future__ import annotations

import re

_SCENARIOS = ("append_log", "cdc_upsert", "collapsing", "agg_rollup")

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def _safe(name: str, default: str) -> str:
    name = (name or "").strip().strip("`\"")
    return name if _IDENT_RE.match(name) else default


def _dim_list(dimensions: str, default: "list[str]") -> "list[str]":
    dims = [d.strip().strip("`\"") for d in re.split(r"[,，\s]+", dimensions or "") if d.strip()]
    return [d for d in dims if _IDENT_RE.match(d)] or default


def _partition_for(ttl_days: int, granularity: str, time_col: str) -> str:
    g = (granularity or "").lower()
    if g in ("month", "月", "toyyyymm"):
        return f"toYYYYMM({time_col})"
    if g in ("day", "日", "toyyyymmdd"):
        return f"toYYYYMMDD({time_col})"
    # 默认按 TTL 给建议粒度：≤7 天 TTL 用日，否则月（规范 2.4：粒度对齐 TTL，避免过度分区）
    return f"toYYYYMMDD({time_col})" if ttl_days and ttl_days <= 7 else f"toYYYYMM({time_col})"


def _dim_cols(dims: list[str], type_: str, comment_prefix: str) -> str:
    parts = []
    for d in dims:
        parts.append(f"    {d} {type_} COMMENT '{comment_prefix}{d}'")
    return ",\n".join(parts)


def generate_ddl(
    scenario: str,
    table: str = "",
    dimensions: str = "",
    time_col: str = "event_time",
    ttl_days: int = 90,
    partition: str = "",
) -> dict:
    """生成建表 DDL 与配套对象。返回 {ok, scenario, ddl, extras, notes}。"""
    if scenario not in _SCENARIOS:
        return {"ok": False, "error": f"未知场景: {scenario}，可选: {', '.join(_SCENARIOS)}"}
    ttl_days = max(0, int(ttl_days))
    time_col = _safe(time_col, "event_time")
    dims = _dim_list(dimensions, ["tenant_id", "event_type"])
    order_tail = ", ".join(dims + [time_col])
    partition_by = _partition_for(ttl_days, partition, time_col)
    ttl_clause = "\nTTL {} + INTERVAL {} DAY".format(time_col, ttl_days or 36500) if ttl_days else ""

    if scenario == "append_log":
        table = _safe(table, "dwd.event_log")
        ddl = (
            "CREATE TABLE {}\n(\n{}\n"
            "    {} DateTime COMMENT '事件时间(本地时区)',\n"
            "    user_id UInt64 COMMENT '用户ID',\n"
            "    amount Decimal(18, 2) COMMENT '金额',\n"
            "    status LowCardinality(String) COMMENT '状态',\n"
            "    payload String COMMENT '扩展JSON',\n"
            "    INDEX idx_user user_id TYPE bloom_filter(0.01) GRANULARITY 1\n"
            ")\n"
            "ENGINE = MergeTree\n"
            "PARTITION BY {}\n"
            "ORDER BY ({}){}"
            "\nSETTINGS index_granularity = 8192;"
        ).format(table, _dim_cols(dims, "UInt32", "维度-"), time_col, partition_by, order_tail, ttl_clause)
        notes = [
            "排序键 = 维度(低基数在前) → 时间(最后)，与查询过滤模式对齐（规范 2.3-1）。",
            "分区 {} 与 TTL 粒度对齐，整分区删除（规范 2.4-2/2.8-1）。".format(partition_by),
            "替换示例列；新增列只允许追加（DEFAULT 兜底），删列/改类型需新表迁移（规范 3-6）。",
            "user_id 等高基数非键过滤列配 bloom_filter；文本 LIKE 列换 tokenbf_v1/ngrambf_v1（规范 2.7-2）。",
        ]
        return {"ok": True, "scenario": scenario, "ddl": ddl, "extras": [], "notes": notes}

    if scenario == "cdc_upsert":
        table = _safe(table, "ods.orders_cdc")
        ddl = (
            "CREATE TABLE {}\n(\n{}\n"
            "    {} DateTime COMMENT '业务时间',\n"
            "    updated_at DateTime COMMENT 'CDC更新时间(单调版本列)',\n"
            "    is_deleted UInt8 DEFAULT 0 COMMENT '软删标记',\n"
            "    amount Decimal(18, 2) COMMENT '金额',\n"
            "    status LowCardinality(String) COMMENT '状态',\n"
            "    raw String COMMENT '原始报文'\n"
            ")\n"
            "ENGINE = ReplacingMergeTree(updated_at)\n"
            "PARTITION BY {}\n"
            "ORDER BY ({}){}"
            "\nSETTINGS index_granularity = 8192, min_age_to_force_merge_seconds = 600;"
        ).format(table, _dim_cols(dims, "UInt32", "业务主键-"), time_col, partition_by, order_tail, ttl_clause)
        notes = [
            "去重键 = ORDER BY 列，业务主键必须在其中（规范 2.3-3）。",
            "版本列 updated_at 必须单调递增，否则'最新版本'无定义（规范 2.9-2）。",
            "高频查询取最新值用 MV+argMax 或 LIMIT 1 BY，查询时 FINAL 仅低频（规范 2.9-1）。",
            "min_age_to_force_merge_seconds=600 让 part 尽快收敛，降低读取端去重代价（规范 2.9-4）。",
        ]
        return {"ok": True, "scenario": scenario, "ddl": ddl, "extras": [], "notes": notes}

    if scenario == "collapsing":
        table = _safe(table, "dws.metric_collapsing")
        ddl = (
            "CREATE TABLE {}\n(\n{}\n"
            "    {} DateTime COMMENT '业务时间',\n"
            "    metric Decimal(18, 4) COMMENT '度量值(可正可负)',\n"
            "    sign Int8 COMMENT '折叠标记 +1/-1'\n"
            ")\n"
            "ENGINE = CollapsingMergeTree(sign)\n"
            "PARTITION BY {}\n"
            "ORDER BY ({}){}"
            "\nSETTINGS index_granularity = 8192;"
        ).format(table, _dim_cols(dims, "UInt32", "维度-"), time_col, partition_by, order_tail, ttl_clause)
        notes = [
            "写入成对 +1/-1 行表达回撤；乱序到达场景改 VersionedCollapsingMergeTree(sign, ver)（规范 2.2-1）。",
            "查询必须 SUM(sign * metric)，漏写 sign 是正确性事故（规范 4.3-3）。",
        ]
        return {"ok": True, "scenario": scenario, "ddl": ddl, "extras": [], "notes": notes}

    # agg_rollup
    detail = _safe(table, "dwd.event_log")
    rollup = detail.rsplit(".", 1)
    rollup_name = "{}.mv_{}".format(rollup[0], rollup[1]) if len(rollup) == 2 else "mv_" + detail
    dim_cols_plain = ", ".join(dims)
    agg_cols = "\n".join("    {} UInt32".format(d) for d in dims)
    ddl = (
        "CREATE TABLE {}\n(\n{}\n"
        "    {} DateTime,\n"
        "    cnt AggregateFunction(count),\n"
        "    amt_sum AggregateFunction(sum, Decimal(18, 2)),\n"
        "    uv AggregateFunction(uniq, UInt64)\n"
        ")\n"
        "ENGINE = AggregatingMergeTree\n"
        "PARTITION BY {}\n"
        "ORDER BY ({});"
    ).format(rollup_name, agg_cols, time_col, partition_by, order_tail)
    mv = (
        "CREATE MATERIALIZED VIEW {name}_mv\n"
        "TO {name}\n"
        "AS\n"
        "SELECT\n"
        "    {dims},\n"
        "    toStartOfHour({tc}) AS {tc},\n"
        "    countState() AS cnt,\n"
        "    sumState(amount) AS amt_sum,\n"
        "    uniqState(user_id) AS uv\n"
        "FROM {detail}\n"
        "GROUP BY {dims}, {tc};"
    ).format(name=rollup_name, dims=dim_cols_plain, tc=time_col, detail=detail)
    query_example = (
        "-- 查询聚合表（Merge 后用 *Merge 补齐未合并状态）\n"
        "SELECT {dims}, {tc},\n"
        "       countMerge(cnt) AS cnt, sumMerge(amt_sum) AS amt, uniqMerge(uv) AS uv\n"
        "FROM {name}\n"
        "WHERE {tc} >= now() - INTERVAL 7 DAY\n"
        "GROUP BY {dims}, {tc};"
    ).format(dims=dim_cols_plain, tc=time_col, name=rollup_name)
    notes = [
        "MV 仅随 INSERT 触发：对明细的 UPDATE/DELETE 不传播，回溯历史需手工回填（规范 5.3-2）。",
        "聚合列用 AggregateFunction 状态类型，读取端用 countMerge/sumMerge/uniqMerge（规范 2.2-1）。",
        "POPULATE 有丢增量风险：新建 MV 停写窗口回填或双写切换（知识库 materialized-views-and-projections）。",
        "仪表盘查聚合表、ad-hoc 查明细表；小时粒度不够就再加一层日粒度 MV。",
    ]
    return {"ok": True, "scenario": scenario, "ddl": ddl, "extras": [mv, query_example], "notes": notes}


__all__ = ["generate_ddl", "_SCENARIOS"]
