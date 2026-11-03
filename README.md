# Agent Builder

数据开发领域多个专用 Agent 的开发仓库。

> ⚠️ 2026-11 磁盘损坏说明：E: 盘曾发生文件系统损坏，本仓库几乎全部文件丢失后从会话上下文重建。
> clickhouse-sql-optimizer、common、_template、SKILL 已完整重建并测试通过；flink-operator-developer
> 与 postgres-sql-optimizer 仅恢复了部分原文（缺失文件以明确标注的占位符代替），如有 git/备份请以其为准恢复。

## Agent 一览

| 目录 | Agent | 职责 |
|------|-------|------|
| `agents/postgres-sql-optimizer` | PostgreSQL SQL 优化 Agent | 分析 EXPLAIN 输出、索引建议、SQL 改写、统计信息诊断（磁盘损坏，待恢复） |
| `agents/clickhouse-sql-optimizer` | ClickHouse SQL 优化 Agent | **已实现 v0.2**：SQL 审查（14 条规则）、建表方案生成（4 场景）与 DDL 评估（13 类检查）、慢 SQL 定位六步 SOP + 诊断 SQL、EXPLAIN 量化解读。知识底座《clickhouse开发规范.md》v1.1；另附 ZCode 技能 `.agents/skills/clickhouse-sql-optimizer/` |
| `agents/flink-operator-developer` | Flink 算子开发 Agent | 生成/审查 DataStream、Table API 算子与 UDF（磁盘损坏，部分恢复） |
| `agents/code-reviewer` | 代码评审 Agent | **已实现 v0.1**：参考阿里 open-code-review——确定性管线（文件筛选/实现-测试智能打包/glob 规则匹配/行级定位）+ LLM 深度评审；结构化评论（8 类 category、4 级 severity、suggestion_code），low 丢弃备查，CLI text/json、critical 时 exit 1 可接 CI |
| `agents/code-review-advisor` | 评审意见顾问 Agent | **已实现 v0.1**：把评审发现润色成"合适意见"（问题-影响-建议-依据 + nit 分级 + 回复三模板），五类语气红线检查（攻击性/人身/绝对化/质问/翻旧账） |
| `agents/code-review-adversary` | commit 对抗红队 Agent | **已实现 v0.1**：commit 级规避/伪装攻击测试 code-reviewer（10 级技术，10 轮迭代 deterministic 100%/0%），语义 bug 导出 LLM 基准集 |
| `agents/perf-capacity-planner` | 性能容量规划 Agent | **已实现 v0.1**：CK/Kafka/Flink/通用容量模型（公式+假设+敏感性），水位 50/70 规则与压测验证闭环 |
| `agents/bigdata-developer` | 大数据开发 Agent | **已实现 v0.1**：Hive 分区/拉链表、Flink SQL、Airflow/DolphinScheduler 模板生成（幂等/增量/重试/对账）+ 8 条 ETL 规则审查 |
| `agents/sql-danger-reviewer` | 高危操作代码检验 Agent | **已实现 v0.1**：拦截全表 UPDATE/DELETE、删库删表、TRUNCATE、ALTER 破坏子句、mutation、动态拼装、rm -rf（DGR-1xx~5xx 分级 + 豁免 + 放行四件套），对抗混淆免疫（10 轮红队验证 100%/0%），CI 可用退出码 |
| `agents/sql-danger-adversary` | 代码评审对抗 Agent（防御性红队） | **已实现 v0.1**：10 级递进攻击语料（混淆/断词/恒真/CTE/事务/三明治/动态/误报对抗）+ 10 轮迭代 harness，检测引擎从基线 82%/36% 加固至 100%/0%，报告见其 `reports/` |
| `agents/_template` | 新 Agent 模板 | 复制此目录快速搭建新 Agent |

## 目录结构

```
Agent-builder/
├── agents/                  # 各 Agent（每个 Agent 一个独立目录）
│   ├── _template/           # 新 Agent 脚手架模板
│   ├── postgres-sql-optimizer/
│   ├── clickhouse-sql-optimizer/
│   ├── code-reviewer/
│   ├── code-review-advisor/
│   ├── code-review-adversary/
│   ├── perf-capacity-planner/
│   ├── bigdata-developer/
│   ├── sql-danger-reviewer/
│   ├── sql-danger-adversary/
│   └── flink-operator-developer/
├── .agents/skills/          # ZCode 技能（clickhouse / code-reviewer / code-review-advisor / code-review-adversary / perf-capacity-planner / bigdata-developer / sql-danger-reviewer / sql-danger-adversary）
├── common/                  # 跨 Agent 公共层（Python 包）
│   ├── agentcore/           # Agent 基类、执行循环、工具协议（ToolRegistry）
│   ├── llm/                 # OpenAI 兼容 LLM 客户端（requests/urllib 双实现）+ Mock
│   └── tools/               # 通用工具（knowledge_search 知识库检索）
├── knowledge/               # 跨 Agent 共享的知识库（规则、案例、文档）
├── datasets/                # 测试数据与评测基准（表结构、慢查询样本等）
├── scripts/                 # 初始化、评测、发布脚本
└── docs/                    # 设计文档、架构决策记录
```

### 单个 Agent 目录约定

```
agents/<agent-name>/
├── README.md        # Agent 定位、输入输出、使用方式
├── config.yaml      # 模型、工具开关、环境配置
├── prompts/         # 系统提示词（system.md 及各阶段提示词）
├── src/             # Agent 业务逻辑代码
├── tools/           # 该 Agent 专属工具（如 EXPLAIN 解析器）
├── knowledge/       # 领域知识（优化规则、最佳实践、典型案例）
├── tests/           # 单元测试与集成测试
└── examples/        # 输入输出示例
```

## 新增 Agent

1. 复制 `agents/_template` 为 `agents/<新名称>`（小写英文 + 中划线）。
2. 修改 `config.yaml` 与 `prompts/system.md`。
3. 在本 README 的 Agent 一览表中登记。

## 约定

- Agent 之间不直接 import 对方代码，公共能力一律下沉到 `common/`。
- 提示词、知识文档用 Markdown 维护，与代码分离，便于独立迭代和评审。
- 每个功能合入前须附带 `tests/` 用例与 `examples/` 示例。
