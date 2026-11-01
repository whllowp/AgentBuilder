"""Agent 集成测试：离线管线（SQL/DDL/EXPLAIN/建表需求）+ Mock LLM 工具回路。"""
import pytest

from clickhouse_agent.agent import ClickHouseOptimizerAgent, load_agent
from clickhouse_agent.config import AgentConfig
from common.llm.client import LLMResponse, ToolCall
from common.llm.mock import MockLLM


@pytest.fixture()
def agent() -> ClickHouseOptimizerAgent:
    return load_agent()


def test_config_loaded(agent):
    assert agent.config.name == "clickhouse-sql-optimizer"
    assert agent.config.version == "0.2.0"
    assert "ClickHouse" in agent.system_prompt
    for tool in ("review_sql", "advise_ddl", "ddl_codegen", "parse_explain", "build_diagnostics"):
        assert tool in agent.tools.names()


def test_offline_sql_review(agent):
    result = agent.offline("这条查询慢：```sql\nSELECT * FROM orders WHERE toDate(create_time) = '2026-09-01' LIMIT 100000, 20\n```")
    assert result["profile"]["kind"] == "sql_review"
    assert result["review"]["ok"]
    rule_ids = {i["rule_id"] for i in result["review"]["issues"]}
    assert "select_star" in rule_ids
    assert "key_function" in rule_ids
    assert "big_offset" in rule_ids
    report = result["report"]
    assert "## 任务解析" in report and "## 审查发现" in report and "## 诊断与验证" in report
    assert "慢 SQL 定位与优化流程" in report


def test_offline_ddl(agent):
    ddl = (
        "```sql\nCREATE TABLE t (\n  trace_id String,\n  pay_amount Float64,\n  ts DateTime\n) "
        "ENGINE = MergeTree PARTITION BY toYYYYMMDD(ts) ORDER BY (trace_id)\n```"
    )
    result = agent.offline(f"帮我评估这个建表：{ddl}")
    assert result["profile"]["kind"] == "ddl"
    rule_ids = {i["rule_id"] for i in result["ddl_results"][0]["issues"]}
    assert "order_by_high_card_first" in rule_ids
    assert "float_money" in rule_ids
    assert "over_partition" in rule_ids
    assert "## 优化建议" in result["report"]


def test_offline_ddl_design_cdc(agent):
    result = agent.offline("帮我建一张 cdc 入湖表，表名为 ods.orders_cdc，按 order_id 去重保留最新")
    assert result["profile"]["kind"] == "ddl_design"
    design = result["ddl_design"]
    assert design["generation"]["scenario"] == "cdc_upsert"
    assert "ReplacingMergeTree(updated_at)" in design["generation"]["ddl"]
    # 自检：生成的 DDL 无 error 级问题
    assert not [i for i in design["selfcheck"]["issues"] if i["severity"] == "error"]
    report = result["report"]
    assert "## 建表方案" in report
    assert "模板结构合规 ✅" in report


def test_offline_ddl_design_rollup(agent):
    result = agent.offline("帮我建一张看板用的预聚合汇总表")
    assert result["profile"]["kind"] == "ddl_design"
    assert result["ddl_design"]["generation"]["scenario"] == "agg_rollup"
    assert "## 建表方案" in result["report"]


def test_offline_explain(agent):
    explain = "```\nPrimaryKeyAllGranules: 990/1000\nKey Condition: (unknown)\n```"
    result = agent.offline(f"看下这个执行计划哪里有问题：{explain}")
    assert result["profile"]["kind"] == "explain"
    assert result["explain_results"][0]["ok"]
    assert "EXPLAIN 指标解读" in result["report"]


def test_offline_unknown(agent):
    result = agent.offline("ClickHouse 怎么调优")
    assert result["profile"]["kind"] == "unknown"
    assert "未从输入中识别" in result["report"]


def test_offline_report_has_diagnostics_and_sop(agent):
    result = agent.offline("SELECT * FROM events")
    assert "system.query_log" in result["report"]
    sop = result["diagnostics"]["sop"]
    assert [s["name"] for s in sop] == ["发现", "取证", "归因", "改写", "验证", "固化"]
    stages = {q["stage"] for q in result["diagnostics"]["queries"]}
    assert stages  # 诊断 SQL 已按 SOP 步骤标注


def test_mock_llm_tool_loop(agent):
    llm = MockLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="review_sql", arguments={"sql": "SELECT * FROM t"})]),
            LLMResponse(content="## 审查发现\n- SELECT * 已指出"),
        ]
    )
    core_agent = ClickHouseOptimizerAgent(agent.config, llm=llm)
    result = core_agent.run("审查这条 SQL")
    assert result.answer.startswith("## 审查发现")
    assert result.iterations == 2
    assert len(result.tool_trace) == 1
    assert result.tool_trace[0].name == "review_sql"
    assert result.tool_trace[0].ok


def test_mock_llm_unknown_tool(agent):
    llm = MockLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="no_such_tool", arguments={})]),
            LLMResponse(content="done"),
        ]
    )
    core_agent = ClickHouseOptimizerAgent(agent.config, llm=llm)
    result = core_agent.run("x")
    assert result.answer == "done"
    assert not result.tool_trace[0].ok


def test_config_load_custom_dir(tmp_path):
    cfg = AgentConfig.load(tmp_path)
    assert cfg.agent_dir == tmp_path.resolve()
    assert cfg.name == "clickhouse-sql-optimizer"  # 默认值兜底
