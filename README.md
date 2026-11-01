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
| `agents/_template` | 新 Agent 模板 | 复制此目录快速搭建新 Agent |

## 目录结构

```
Agent-builder/
├── agents/                  # 各 Agent（每个 Agent 一个独立目录）
│   ├── _template/           # 新 Agent 脚手架模板
│   ├── postgres-sql-optimizer/
│   ├── clickhouse-sql-optimizer/
│   └── flink-operator-developer/
├── .agents/skills/          # ZCode 技能（clickhouse-sql-optimizer）
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
