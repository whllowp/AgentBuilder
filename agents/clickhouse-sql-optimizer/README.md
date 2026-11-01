# ClickHouse SQL 优化 Agent

## 定位

针对 ClickHouse 场景的 SQL 与表设计优化助手。**已实现 v0.2**：SQL 静态审查、建表方案生成与 DDL 评估、慢 SQL 定位六步 SOP 与诊断 SQL 生成、EXPLAIN 量化解读，支持 LLM 工具回路与离线模式。

知识底座：《clickhouse开发规范.md》（Agent 根目录，v1.1）——基于 ClickHouse 官方文档/博客最佳实践（ORDER BY 100x、过度分区 46x、字典 JOIN 3x、FINAL vs argMax 实测、v24~26 新分析器特性等）+ Altinity 知识库整理，覆盖建表/写入/查询/慢 SQL 六步 SOP/优化手段/陷阱案例 7 章。

## 输入 / 输出

- 输入（可混合，自动识别类型）：
  - SQL 语句（慢查询）
  - 建表 DDL（`SHOW CREATE TABLE` 输出）
  - 建表需求描述（"帮我建一张 CDC 入湖表"——按场景关键词推断）
  - `EXPLAIN` / `EXPLAIN indexes=1` 输出文本
- 输出（Markdown 报告）：
  - `## 任务解析`：输入类型、涉及表、建表场景
  - `## 建表方案`（生成任务）：合规 DDL（+MV/查询示例）+ 设计要点 + advise_ddl 自检结果
  - `## 审查发现`：分级问题表（❌强制 / ⚠️建议 / ℹ️提示 + 证据 + 规范条目）
  - `## 优化建议`：逐条可执行改写与预期收益依据
  - `## 慢 SQL 定位与优化流程`：六步 SOP（发现→取证→归因→改写→验证→固化）
  - `## 诊断与验证`：按 SOP 步骤标注的 EXPLAIN / system.* 验证 SQL
  - `## 规范依据`：知识库命中摘录

## 实现结构

```
clickhouse-sql-optimizer/
├── clickhouse开发规范.md       # 规范原文 v1.1（知识底座，7 章 + 附录含建表模板索引）
├── config.yaml                 # LLM 端点 / 6 个工具开关 / CK 版本
├── prompts/
│   ├── system.md               # 系统提示词（角色、16 条核心规范、四类任务工作流、输出格式）
│   └── review.md               # SQL/DDL/建表方案复查清单（LLM 二阶段）
├── src/clickhouse_agent/       # Agent 本体（Python 3.10+，无第三方强依赖）
│   ├── agent.py                # LLM 工具回路 + 离线管线（审查/评估/生成/解读→佐证→报告）
│   ├── analyzer.py             # 规则式任务解析（DDL/EXPLAIN/SQL/建表需求识别与场景推断）
│   ├── config.py / cli.py / _bootstrap.py
├── tools/clickhouse_tools/     # Agent 可调用的工具
│   ├── sql_review.py           # 14 条 SQL 静态审查规则（含改写建议与规范引用）
│   ├── ddl_advisor.py          # DDL 解析 + 13 类检查（引擎/排序键/分区/类型/去重语义）
│   ├── ddl_codegen.py          # 建表方案生成（append_log/cdc_upsert/collapsing/agg_rollup）
│   ├── explain_parser.py       # EXPLAIN 解读（Parts/Granules 裁剪率、Key Condition）
│   ├── diagnostics.py          # 慢SQL六步 SOP + 8 类 system.* 诊断 SQL（按步骤标注）
│   └── __init__.py             # build_registry（6 个工具注册）
├── knowledge/                  # 规范提炼 7 篇（含 slow-query-troubleshooting 六步 SOP）
├── tests/                      # pytest 94 用例（规则、生成自检、SOP、离线管线、Mock LLM 回路）
└── examples/                   # 离线管线生成的示例报告
```

依赖的公共层：`common/agentcore`（执行循环、工具协议）、`common/llm`（OpenAI 兼容客户端、Mock）、`common/tools/knowledge_search`（通用知识检索）。

## 工具（tools）

| 工具 | 职责 |
|------|------|
| `knowledge_search` | 检索 knowledge/ 规范提炼（7 篇） |
| `review_sql` | SQL 静态审查（14 条规则，分级 + 改写建议） |
| `advise_ddl` | 建表 DDL 评估（13 类检查） |
| `ddl_codegen` | 建表方案生成（4 场景合规模板，生成后自动 advise_ddl 自检） |
| `parse_explain` | EXPLAIN 输出量化解读（分区/主键裁剪率、键条件） |
| `build_diagnostics` | 慢 SQL 六步 SOP + 按 SOP 步骤标注的诊断 SQL（无需真实连接） |

## 使用方式

需要 Python 3.10+、PyYAML（requests 可选，缺失时自动退回 urllib）。

```bash
# 1) 离线模式（不调 LLM）：任务解析 -> 审查/评估/生成/解读 -> 知识库佐证 -> Markdown 报告
python agents/clickhouse-sql-optimizer/src/clickhouse_agent/cli.py \
  "SELECT * FROM dws.orders FINAL WHERE toDate(create_time) = '2026-09-01'" --offline

# 建表方案生成
python agents/clickhouse-sql-optimizer/src/clickhouse_agent/cli.py \
  "帮我建一张 cdc 入湖表，表名 ods.orders_cdc，按 order_id 去重保留最新" --offline

# 2) LLM 模式：完整工具调用回路（先在 config.yaml 配置端点或设环境变量）
export OPENAI_API_KEY=sk-...   # 或改 config.yaml 用智谱/DeepSeek 等兼容端点
python agents/clickhouse-sql-optimizer/src/clickhouse_agent/cli.py "慢查询 + DDL" --trace

# 可加 --out report.md 保存报告
```

```bash
# 运行测试
cd agents/clickhouse-sql-optimizer && python -m pytest tests -q
```

## 关联产物

- ZCode 技能：`.agents/skills/clickhouse-sql-optimizer/`（同一规范驱动：SKILL.md + 4 篇 references，含建表模板与六步 SOP）
