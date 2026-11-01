# Flink 算子开发 Agent

> ⚠️ 2026-11 磁盘损坏恢复说明：E: 盘文件系统损坏导致本目录文件丢失。以下文件按会话中读过的原文恢复：
> README.md、config.yaml、prompts/system.md、src/flink_operator_agent/{agent,config,cli,_bootstrap}.py、
> tools/flink_tools/{__init__,knowledge_search}.py、tests/conftest.py。
> 其余文件（analyzer.py、source_codegen.py、code_validator.py、templates/、knowledge/、tests/test_*.py、
> examples/、ali规范.md、prompts/review.md）已丢失，当前为带说明的占位符，请从 git/备份恢复。

## 定位

Flink 作业开发助手：根据需求描述与源表/目标表结构，生成并审查 Flink 算子与 UDF 代码（DataStream API / Table API & SQL），覆盖常见的数据转换、窗口聚合、维表关联场景。

知识底座为两套规范：

1. **Apache Flink 1.17 官方 Data Sources 文档**（FLIP-27 新 Source API、Split Reader API、事件时间与 Watermark）
2. **阿里生产规范**（`ali规范.md`，提炼为 `knowledge/ali-production-spec.md` 与 `knowledge/ali-backpressure-tuning.md`）：fromSource 入口、并行度与外部分区对齐、数据库摄入 CDC 优先、withIdleness/Watermark Alignment 防空闲分区、状态精简与 RocksDB、外部 I/O 异步化、Unaligned Checkpoint、反压排查 SOP 等。

阿里规范已落实到：系统提示词（`prompts/system.md` 阿里规范章节）、代码模板（骨架含 `pauseOrResumeSplits` 钩子、Unaligned Checkpoint、状态精简注释；Kafka 模板含并行度对齐与 withIdleness 指引；新增 MySQL CDC 模板）、静态审查（`code_validator.py` 新增 8 条阿里规则）、离线报告（生产与监控建议段）。

## 输入 / 输出

- 输入：
  - 需求描述（转换逻辑、窗口语义、输出目标）
  - 源/_sink 表结构与连接器配置（Kafka、JDBC、CK 等）
  - Flink 版本与部署模式
- 输出：
  - 可运行的算子/UDF 代码（Java 或 Python）
  - 作业拓扑说明与关键配置（并行度、状态 TTL、水位线、重启策略）
  - 代码审查意见（反压风险、状态膨胀、序列化开销、exactly-once 语义）

## 实现结构

```
flink-operator-developer/
├── config.yaml                 # LLM 端点 / 工具开关 / Flink 版本
├── prompts/
│   ├── system.md               # 系统提示词（角色、Flink 1.17 规范、工作流程、输出格式）
│   └── review.md               # 代码审查清单（占位，待恢复）
├── src/flink_operator_agent/   # Agent 本体（Python 3.10+，无第三方强依赖）
│   ├── agent.py                # FlinkOperatorAgent：LLM 工具回路 + 离线管线
│   ├── analyzer.py             # 规则式需求解析（占位，待恢复）
│   ├── config.py / cli.py / _bootstrap.py
├── tools/flink_tools/          # Agent 可调用的工具
│   ├── knowledge_search.py     # 知识库关键词检索（标题/关键词/正文加权）
│   ├── source_codegen.py       # FLIP-27 自定义 Source 骨架 + CDC/Kafka/File/DataGen 用法（占位，待恢复）
│   ├── code_validator.py       # 静态审查（占位，待恢复）
│   └── templates/*.java.tmpl   # 代码模板（占位，待恢复）
├── knowledge/                  # 官方文档提炼 + 阿里规范提炼（占位，待恢复）
├── tests/                      # pytest（conftest 已恢复；test_* 待恢复）
└── examples/                   # 离线管线生成的示例报告（待恢复）
```

依赖的公共层：`common/agentcore`（Agent 执行循环、工具协议）、`common/llm`（OpenAI 兼容客户端、Mock）。

## 使用方式

需要 Python 3.10+、PyYAML（requests 可选，缺失时自动退回 urllib）。

```bash
# 1) 离线模式（不调 LLM）：规则解析 -> 生成骨架 -> 静态审查 -> Markdown 报告
#    （当前 analyzer/source_codegen/code_validator 为占位符，需先从备份恢复）
python agents/flink-operator-developer/src/flink_operator_agent/cli.py \
  "实现一个自定义 MQTT Source，无界流式，事件时间乱序" --offline

# 2) LLM 模式：完整工具调用回路（先在 config.yaml 配置端点或设环境变量）
export OPENAI_API_KEY=sk-...
python agents/flink-operator-developer/src/flink_operator_agent/cli.py \
  "用 KafkaSource 消费 orders topic，事件时间乱序 5 秒" --trace
```
