"""bigdata-developer 测试：代码生成、审查规则、Agent 集成。"""
import pytest

from bigdata_tools.etl_codegen import generate
from bigdata_tools.etl_review import review_code
from bigdata_agent.agent import BigdataDeveloperAgent, detect_scenario, load_agent
from common.llm.client import LLMResponse, ToolCall
from common.llm.mock import MockLLM


# ---------------- 代码生成 ----------------

def test_all_scenarios_generate_and_pass_review():
    for s in ("hive_partition", "hive_zipper", "flink_sql", "airflow_dag", "dolphinsched"):
        g = generate(s, table="dwd_order")
        assert g["ok"], s
        assert g["artifacts"] and g["notes"]
        # 模板自检：不得触发高危规则（合规是模板的设计底线）
        code = "\n\n".join(c for _, c in g["artifacts"])
        review = review_code(code)
        assert not [f for f in review["findings"] if f["severity"] == "高危"], (s, review["findings"])


def test_zipper_has_end_date_condition():
    g = generate("hive_zipper", table="t")
    code = "\n".join(c for _, c in g["artifacts"])
    assert "9999-12-31" in code and "OVERWRITE" in code


def test_airflow_has_retry_and_check():
    code = dict(generate("airflow_dag", table="t")["artifacts"])["t_daily.py"]
    assert "retries" in code and "check_count" in code and "max_active_runs=1" in code


def test_invalid_scenario():
    assert not generate("spark_ml")["ok"]


# ---------------- 审查规则 ----------------

def test_review_rules_fire():
    bad = (
        "INSERT OVERWRITE TABLE dwd.orders\nSELECT * FROM ods.orders;\n"
        "DROP TABLE dwd.orders;"
    )
    r = review_code(bad)
    ids = {f["rule_id"] for f in r["findings"]}
    assert {"ETL-101", "ETL-102", "ETL-108"} <= ids


def test_review_incremental_missing_filter():
    r = review_code("INSERT INTO dwd.t\nSELECT id FROM ods.t_src;")
    assert any(f["rule_id"] == "ETL-103" for f in r["findings"])


def test_review_dag_no_retry():
    r = review_code("from airflow import DAG\nwith DAG(dag_id='x', schedule='@daily') as dag:\n    pass")
    assert any(f["rule_id"] == "ETL-104" for f in r["findings"])


def test_review_zipper_missing_end():
    r = review_code("-- 拉链表查询\nSELECT id FROM dwd.orders_zipper;")
    assert any(f["rule_id"] == "ETL-106" for f in r["findings"])


def test_review_clean_code_passes():
    good = (
        "INSERT OVERWRITE TABLE dwd.t PARTITION (dt='${ds_nodash}')\n"
        "SELECT id, name FROM ods.t WHERE dt='${ds_nodash}';\n"
        "-- check: SELECT count(1) FROM dwd.t WHERE dt='${ds_nodash}'"
    )
    r = review_code(good)
    assert not [f for f in r["findings"] if f["severity"] == "高危"]


# ---------------- 场景识别与 Agent ----------------

def test_detect_scenario():
    assert detect_scenario("帮我做订单拉链表") == "hive_zipper"
    assert detect_scenario("写个实时 flink 作业") == "flink_sql"
    assert detect_scenario("配一个 airflow 调度") == "airflow_dag"
    assert detect_scenario("建个分区表") == "hive_partition"


@pytest.fixture()
def agent():
    return load_agent()


def test_agent_offline_codegen(agent):
    r = agent.offline("帮我写订单拉链表，表名 dwd_order")
    assert r["mode"] == "codegen" and r["scenario"] == "hive_zipper"
    assert "## 代码" in r["report"] and "上线检查单" in r["report"]


def test_agent_offline_review(agent):
    r = agent.offline("INSERT OVERWRITE TABLE dwd.orders\nSELECT * FROM ods.orders;")
    assert r["mode"] == "review" and "ETL-101" in r["report"]


def test_mock_llm_loop(agent):
    llm = MockLLM([
        LLMResponse(tool_calls=[ToolCall(id="c1", name="etl_review", arguments={"code": "DROP TABLE dwd.x"})]),
        LLMResponse(content="## 审查结果\n已列出"),
    ])
    a = BigdataDeveloperAgent(agent.config, llm=llm)
    r = a.run("审查这段")
    assert r.answer.startswith("## 审查结果") and r.tool_trace[0].name == "etl_review"
