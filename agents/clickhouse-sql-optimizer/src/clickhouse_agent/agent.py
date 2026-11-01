"""ClickHouseOptimizerAgent：LLM 工具调用模式 + 无 LLM 的离线 pipeline 模式。"""
from __future__ import annotations

from . import _bootstrap  # noqa: F401 —— 必须最先导入以建立 sys.path

from pathlib import Path

from common.agentcore import BaseAgent, ToolRegistry
from common.llm.client import LLMClient
from common.tools.knowledge_search import search as knowledge_search

from clickhouse_tools import (
    advise_ddl,
    build_diagnostics,
    build_registry,
    generate_ddl,
    parse_explain,
    review_sql,
)

from .analyzer import analyze_request
from .config import AgentConfig

_ICON = {"error": "❌", "warning": "⚠️ ", "info": "ℹ️ "}

_SCENARIO_DESC = {
    "append_log": "追加写明细表（MergeTree + 月分区 + TTL）",
    "cdc_upsert": "CDC 入湖/Upsert（ReplacingMergeTree(updated_at) + 软删）",
    "collapsing": "增减回撤（CollapsingMergeTree(sign)）",
    "agg_rollup": "预聚合汇总（AggregatingMergeTree + 物化视图）",
}


class ClickHouseOptimizerAgent:
    def __init__(self, config: AgentConfig, llm: LLMClient | None = None):
        self.config = config
        self.llm = llm or self._default_llm()
        self.tools: ToolRegistry = build_registry(config.agent_dir, config.tools)
        self.system_prompt = (config.prompts_dir / "system.md").read_text(encoding="utf-8")
        self._core = BaseAgent(
            llm=self.llm,
            system_prompt=self.system_prompt,
            tools=self.tools,
            max_iterations=config.max_iterations,
        )

    def _default_llm(self) -> LLMClient:
        settings = self.config.llm
        return LLMClient(
            base_url=settings.base_url,
            model=settings.model,
            api_key=settings.api_key,
            api_key_env=settings.api_key_env,
            temperature=settings.temperature,
            timeout=settings.timeout,
            max_retries=settings.max_retries,
        )

    # ---------------- LLM 模式 ----------------

    def run(self, request: str):
        """完整 Agent 回路（需可用的 LLM 端点）。"""
        return self._core.run(request)

    # ---------------- 离线模式 ----------------

    def offline(self, request: str) -> dict:
        """无 LLM 的规则管线：解析请求 -> SQL 审查 / DDL 评估 / 建表生成 / EXPLAIN 解读 -> 知识库佐证 -> 组装报告。"""
        profile = analyze_request(request)

        review = review_sql("\n;\n".join(profile["sqls"])) if profile["sqls"] else None
        ddl_results = [advise_ddl(d) for d in profile["ddl_texts"]]
        explain_results = [parse_explain(e) for e in profile["explain_texts"]]

        # 描述性建表需求：生成合规 DDL，再交给 advise_ddl 复核（自证模板合规）
        ddl_design = None
        if profile["ddl_design"]["intent"]:
            design = profile["ddl_design"]
            generated = generate_ddl(design["scenario"], table=design["table"] or "")
            if generated.get("ok"):
                selfcheck = advise_ddl(generated["ddl"])
                ddl_design = {"generation": generated, "selfcheck": selfcheck}

        knowledge = self._knowledge_hits(profile, review, ddl_results, explain_results, ddl_design)
        diagnostics = build_diagnostics(profile["tables"][0] if profile["tables"] else "")

        report = self._build_report(profile, review, ddl_results, explain_results, ddl_design, knowledge, diagnostics)
        return {
            "profile": profile,
            "review": review,
            "ddl_results": ddl_results,
            "explain_results": explain_results,
            "ddl_design": ddl_design,
            "knowledge": knowledge,
            "diagnostics": diagnostics,
            "report": report,
        }

    def _knowledge_hits(self, profile, review, ddl_results, explain_results, ddl_design) -> list[dict]:
        """按发现的问题检索知识库佐证（每类问题取 1 条最相关文档）。"""
        topics: list[str] = []
        if review:
            for issue in review.get("issues", []):
                rid = issue.get("rule_id", "")
                if rid in ("final_read_cost",):
                    topics.append("final argMax 去重")
                elif rid in ("key_function", "big_offset", "order_no_limit", "no_where", "select_star"):
                    topics.append("查询优化 EXPLAIN granules")
                elif rid == "leading_wildcard_like":
                    topics.append("跳数索引 tokenbf bloom_filter")
                elif rid in ("too_many_joins", "comma_join", "in_subquery"):
                    topics.append("join 字典 dictGet")
                elif rid == "mutation_api":
                    topics.append("常见陷阱 mutation")
                elif rid == "single_row_insert":
                    topics.append("常见陷阱 Too many parts async_insert")
                elif rid == "exact_distinct":
                    topics.append("查询优化 uniq 近似")
        if ddl_results:
            for r in ddl_results:
                if not r.get("ok"):
                    continue
                for issue in r.get("issues", []):
                    rid = issue.get("rule_id", "")
                    if rid in ("no_order_by", "order_by_high_card_first", "order_by_time_first", "order_by_too_long", "pk_not_prefix"):
                        topics.append("MergeTree ORDER BY 排序键 低基数")
                    elif rid in ("over_partition",):
                        topics.append("分区 过度分区 part")
                    elif rid.startswith("rmt") or rid == "collapsing_no_sign":
                        topics.append("ReplacingMergeTree 去重 argMax")
                    elif rid in ("no_skip_index", "skip_index_on_key"):
                        topics.append("跳数索引 minmax set bloom_filter")
                    elif rid in ("nullable_abuse", "float_money", "no_low_cardinality"):
                        topics.append("数据类型 LowCardinality Nullable")
        if explain_results:
            topics.append("慢SQL 定位 流程 SOP EXPLAIN")
        if ddl_design:
            topics.append("物化视图 投影 预聚合")

        seen, hits = set(), []
        for topic in topics:
            if topic in seen:
                continue
            seen.add(topic)
            try:
                results = knowledge_search(self.config.knowledge_dir, topic, 1)
            except FileNotFoundError:
                break
            for r in results:
                if r["file"] not in seen:
                    seen.add(r["file"])
                    hits.append(r)
        return hits[:4]

    def _build_report(self, profile, review, ddl_results, explain_results, ddl_design, knowledge, diagnostics) -> str:
        lines: list[str] = ["# ClickHouse 优化报告", ""]

        # ---- 任务解析 ----
        lines.append("## 任务解析\n")
        lines.append("| 项 | 值 |")
        lines.append("| --- | --- |")
        kind_desc = {
            "ddl": "建表 DDL 评估",
            "ddl_design": "建表方案生成",
            "explain": "EXPLAIN 执行计划解读",
            "sql_review": "SQL 静态审查",
            "mixed": "混合输入（DDL + 查询/EXPLAIN）",
            "unknown": "未识别到 SQL/DDL/EXPLAIN",
        }
        lines.append(f"| 任务类型 | {kind_desc.get(profile['kind'], profile['kind'])} |")
        lines.append(f"| 涉及表 | {', '.join(profile['tables']) if profile['tables'] else '（未识别/未知）'} |")
        lines.append(f"| 语句数 | 查询 {len(profile['sqls'])}；DDL {len(profile['ddl_texts'])}；EXPLAIN {len(profile['explain_texts'])} |")
        if profile["ddl_design"]["intent"]:
            lines.append(f"| 建表场景 | {_SCENARIO_DESC.get(profile['ddl_design']['scenario'], profile['ddl_design']['scenario'])} |")
        lines.append(f"| 适用版本 | ClickHouse {self.config.clickhouse_version} |")
        lines.append("")

        if profile["kind"] == "unknown":
            lines.append("未从输入中识别到 SQL、DDL、EXPLAIN 或建表需求。可以提供的输入：\n")
            lines.append("1. **慢 SQL**：贴出语句（贴 EXPLAIN 输出更佳）；")
            lines.append("2. **建表 DDL**：`SHOW CREATE TABLE` 的输出；")
            lines.append("3. **EXPLAIN 输出**：`EXPLAIN indexes = 1 SELECT ...` 的执行计划文本；")
            lines.append("4. **建表需求**：描述场景（明细日志 / CDC 去重 / 回撤 / 预聚合）与维度列。\n")

        # ---- 建表方案（生成） ----
        if ddl_design:
            gen = ddl_design["generation"]
            lines.append("## 建表方案\n")
            lines.append(f"场景：{_SCENARIO_DESC.get(gen['scenario'], gen['scenario'])}\n")
            lines.append("```sql")
            lines.append(gen["ddl"])
            for extra in gen.get("extras", []):
                lines.append("")
                lines.append(extra)
            lines.append("```\n")
            if gen.get("notes"):
                lines.append("**设计要点**：")
                for note in gen["notes"]:
                    lines.append(f"- {note}")
                lines.append("")
            sc = ddl_design.get("selfcheck", {})
            if sc.get("ok"):
                errs = [i for i in sc.get("issues", []) if i["severity"] == "error"]
                lines.append(f"**自检**：{sc['summary']}" + ("，模板结构合规 ✅" if not errs else ""))
                lines.append("")

        # ---- 审查发现 ----
        lines.append("## 审查发现\n")
        all_issues = []
        if review and review.get("ok"):
            lines.append(f"**SQL 审查**：{review['summary']}\n")
            all_issues.extend(review.get("issues", []))
        for idx, r in enumerate(ddl_results, 1):
            if r.get("ok"):
                lines.append(f"**DDL-{idx}**：{r['summary']}\n")
                all_issues.extend(r.get("issues", []))
        for idx, r in enumerate(explain_results, 1):
            if r.get("ok"):
                lines.append(f"**EXPLAIN-{idx}**：{r['summary']}\n")

        if all_issues:
            lines.append("| 级别 | 规则 | 证据 | 建议 |")
            lines.append("| --- | --- | --- | --- |")
            for i in all_issues[:20]:
                icon = _ICON.get(i["severity"], "-")
                evidence = i.get("evidence", "").replace("|", "\\|")[:60]
                suggestion = i.get("suggestion", "").replace("|", "\\|")
                lines.append(f"| {icon} | {i['title']}（{i.get('spec_ref', '')}） | `{evidence}` | {suggestion} |")
            lines.append("")
        elif profile["kind"] != "unknown" and not ddl_design:
            lines.append("- ✅ 规则审查未发现问题；性能问题可用下方诊断 SQL 量化定位。")
            lines.append("")

        # ---- 优化建议 ----
        lines.append("## 优化建议\n")
        if all_issues:
            for i in all_issues[:8]:
                lines.append(f"- {_ICON.get(i['severity'], '-')} **{i['title']}**")
                lines.append(f"  - 建议：{i['suggestion']}")
                lines.append(f"  - 依据：{i.get('spec_ref', '')}")
            if len(all_issues) > 8:
                lines.append(f"- …另有 {len(all_issues) - 8} 条见上表")
        elif ddl_design:
            lines.append("- 生成的表结构已按规范设计（低基数前置排序键、分区对齐 TTL、类型合规）；按业务替换占位列后，用 `EXPLAIN indexes=1` 验证真实查询命中。")
        else:
            lines.append("- 保持：过滤条件命中排序键前缀、列裁剪、批量写入、维度小表走字典。")
        lines.append("")

        if explain_results:
            lines.append("### EXPLAIN 指标解读\n")
            for r in explain_results:
                if not r.get("ok"):
                    continue
                metrics = r.get("metrics", {})
                for k, v in metrics.items():
                    lines.append(f"- {k}: `{v}`")
                for a in r.get("advice", []):
                    lines.append(f"- {_ICON.get(a['severity'], '-')} {a['title']} —— {a['action']}")
            lines.append("")

        # ---- 慢 SQL 定位与优化流程 ----
        lines.append("## 慢 SQL 定位与优化流程（六步 SOP）\n")
        sop = diagnostics.get("sop", [])
        for step in sop:
            lines.append(f"{step['no']}. **{step['name']}**：{step['action']}")
        lines.append("")

        # ---- 诊断与验证 ----
        lines.append("## 诊断与验证\n")
        lines.append("在目标库执行以下诊断 SQL，把结果贴回可获得量化优化建议：\n")
        for q in diagnostics.get("queries", [])[:5]:
            stage = f"（第 {q['stage']} 步：{q['stage_name']}）" if q.get("stage") else ""
            lines.append(f"**{q['title']}**{stage} {q['purpose']}")
            lines.append("```sql")
            lines.append(q["sql"])
            lines.append("```\n")

        # ---- 知识库与规范依据 ----
        if knowledge:
            lines.append("## 规范依据（知识库命中）\n")
            for k in knowledge:
                lines.append(f"- **{k['title']}**（{k['file']}）：{k['excerpt'][:150]}…")
            lines.append("")
        lines.append(f"完整规范见《{self.config.spec_file}》（Agent 根目录）。")
        lines.append("")
        lines.append("---")
        lines.append("*本报告由 clickhouse-sql-optimizer 离线管线生成（未调用 LLM）；LLM 模式可获得交互式定制。*")
        return "\n".join(lines)


def load_agent(agent_dir: str | Path | None = None) -> ClickHouseOptimizerAgent:
    """默认从本文件位置推断 Agent 目录构造 Agent。"""
    if agent_dir is None:
        agent_dir = Path(__file__).resolve().parents[2]
    return ClickHouseOptimizerAgent(AgentConfig.load(agent_dir))
