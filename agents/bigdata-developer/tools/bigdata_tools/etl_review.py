"""ETL/调度代码静态审查：幂等、分区、依赖、对账、重试五大主题的确定性检查。"""
from __future__ import annotations

import re

_RULES = []


def _rule(rule_id, severity, title, suggestion):
    def deco(fn):
        _RULES.append((rule_id, severity, title, fn, suggestion))
        return fn
    return deco


@_rule("ETL-101", "高危", "INSERT OVERWRITE 无分区条件（全表覆盖）",
       "补 PARTITION(...) 与分区过滤；全表重刷需评审 + 独立任务")
def _r_overwrite_no_partition(code: str) -> list[str]:
    hits = []
    for m in re.finditer(r"INSERT\s+OVERWRITE\s+TABLE\s+[\w.]+(?!\s+PARTITION)", code, re.IGNORECASE):
        seg = code[m.start(): m.start() + 120]
        if not re.search(r"PARTITION", seg, re.IGNORECASE):
            hits.append(seg.splitlines()[0][:100])
    return hits


@_rule("ETL-102", "中危", "SELECT * 直通 INSERT（无列映射）",
       "显式列出列清单，防上游加列导致错位")
def _r_select_star_insert(code: str) -> list[str]:
    if re.search(r"INSERT\s+[^;]{0,200}SELECT\s+\*", code, re.IGNORECASE | re.DOTALL):
        return [re.search(r"INSERT[^;]{0,80}", code, re.IGNORECASE | re.DOTALL).group(0)[:100]]
    return []


@_rule("ETL-103", "高危", "增量任务缺时间过滤（无 ds/分区条件）",
       "增量拉取必须带调度参数过滤（${ds}/${ds_nodash} 或分区等值）")
def _r_no_incremental_filter(code: str) -> list[str]:
    if re.search(r"INSERT\s+(OVERWRITE\s+)?INTO", code, re.IGNORECASE) and re.search(r"FROM\s+ods", code, re.IGNORECASE):
        if not re.search(r"\$\{ds|dt\s*=|partition", code, re.IGNORECASE):
            return ["INSERT ... FROM ods_* 全量无过滤"]
    return []


@_rule("ETL-104", "高危", "Airflow DAG 缺 retries（网络抖动即失败）",
       "default_args 配 retries>=3 与 retry_delay")
def _r_dag_no_retries(code: str) -> list[str]:
    if re.search(r"airflow|DAG\(", code) and not re.search(r"retries|failRetry", code, re.IGNORECASE):
        return ["DAG 定义无 retries/failRetryTimes"]
    return []


@_rule("ETL-105", "中危", "调度缺数据质量对账（count/主键校验）",
       "加 check_count / 对账任务，失败阻断下游")
def _r_no_check(code: str) -> list[str]:
    if re.search(r"INSERT|HiveOperator|type:\s*SQL", code, re.IGNORECASE) and not re.search(r"check|count\s*\(|对账", code, re.IGNORECASE):
        return ["无行数/对账校验"]
    return []


@_rule("ETL-106", "高危", "拉链表查询漏 end_date 开链条件",
       "最新版查询必须 AND end_date = '9999-12-31'")
def _r_zipper_no_end(code: str) -> list[str]:
    # 按语句判定：FROM <...zipper>（读拉链表）且整句无 end_date='9999-12-31' 过滤/字面值 → 漏条件
    hits = []
    for stmt in code.split(";"):
        if re.search(r"FROM\s+[\w.]*zipper", stmt, re.IGNORECASE) and not re.search(
            r"end_date\s*=\s*'9999|9999-12-31", stmt, re.IGNORECASE
        ):
            hits.append(("FROM " + re.search(r"FROM\s+[\w.]*zipper", stmt, re.IGNORECASE).group(0).split(None, 1)[1])[:80])
    return hits


@_rule("ETL-107", "中危", "DAG 未串行（max_active_runs 缺省可并发写同分区）",
       "max_active_runs=1（分区级任务防写冲突）")
def _r_dag_parallel(code: str) -> list[str]:
    if re.search(r"schedule=", code) and re.search(r"airflow|DAG\(", code) and not re.search(r"max_active_runs|catchup\s*=\s*False", code):
        return ["DAG 缺 max_active_runs/catchup 控制"]
    return []


@_rule("ETL-108", "高危", "DROP TABLE 无 tmp 前缀（复用 DGR 理念）",
       "确认对象：非 tmp 表删除需审批与备份（深度检查走 sql-danger-reviewer）")
def _r_drop_no_tmp(code: str) -> list[str]:
    hits = []
    for m in re.finditer(r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?([\w.]+)", code, re.IGNORECASE):
        if not re.match(r"(?i:.*tmp)", m.group(1)):
            hits.append(m.group(0)[:80])
    return hits


def review_code(code: str) -> dict:
    """审查 ETL SQL/调度代码，返回分级发现。"""
    if not code or not code.strip():
        return {"ok": False, "findings": [], "summary": "输入为空"}
    findings = []
    for rule_id, severity, title, fn, suggestion in _RULES:
        for ev in fn(code):
            findings.append({"rule_id": rule_id, "severity": severity, "title": title,
                             "evidence": ev, "suggestion": suggestion})
    order = {"高危": 0, "中危": 1, "低危": 2}
    findings.sort(key=lambda f: order.get(f["severity"], 9))
    counts = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    summary = (f"发现 {len(findings)} 处：" + " / ".join(f"{k}{v}" for k, v in counts.items())) if findings else "未发现问题（幂等/分区/依赖/对账/重试检查通过）"
    return {"ok": True, "findings": findings, "summary": summary, "rule_count": len(_RULES)}


__all__ = ["review_code"]
