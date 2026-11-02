# 代码评审 Agent（code-reviewer）

## 定位

AI 代码评审 Agent，设计参考阿里开源的 [alibaba/open-code-review](https://github.com/alibaba/open-code-review)（其前身为阿里内部官方 AI 代码评审助手）：**确定性工程管线 + LLM 深度评审**结合，产出**行级定位**的结构化评审意见。**已实现 v0.1**：diff 解析与文件筛选、实现-测试智能打包、glob 规则匹配（rule.json 覆盖/合并语义同源）、确定性静态检查、按严重度分组报告（low 丢弃备查）、CLI 双格式输出（critical 时 exit 1 可接 CI）。

## 与 open-code-review 的对应关系

| open-code-review 设计 | 本 Agent 实现 |
|------------------------|----------------|
| 精准文件筛选（锁文件/生成物/三方库过滤） | `diff_utils.py`（DEFAULT_FILTERS + 过滤统计透明化） |
| 智能打包（关联文件合并为评审单元、可并发 sub-agent） | `bundle.py`（实现-测试配对 + 同目录聚合，8 文件/1200 行上限） |
| 模板规则匹配（聚焦注意力） | `rule_engine.py`（glob 规则；`.opencodereview/rule.json` 优先级与 merge_system_rule 同源） |
| 行级评论定位 | hunk 头解析 → 新文件行号（start_line/end_line） |
| 评论结构（category/severity/suggestion_code/thinking） | `static_scan.py`（8 类 category、4 级 severity） |
| 报告丢弃疑似误报 low、按 severity 分组 | `group_report`（--keep-low 可保留） |
| 收集业务上下文 → 评审 → 报告 → 按需修复 | `prompts/system.md` 四步工作流（LLM 模式） |
| diff 评审 / 全量扫描两种模式 | 离线管线聚焦 diff；全量可把文件视作全新增行 |

## 实现结构

```
code-reviewer/
├── config.yaml / prompts/system.md    # 工具开关；LLM 模式四步工作流与评论 JSON schema
├── src/code_review_agent/             # Agent 本体（离线确定性管线 + LLM 回路 + CLI text/json）
├── tools/review_tools/
│   ├── diff_utils.py                  # 统一 diff 解析、文件筛选、行号映射
│   ├── bundle.py                      # 智能打包（实现-测试配对、同目录聚合、包上限）
│   ├── rule_engine.py                 # glob 规则匹配 + rule.json 覆盖/合并
│   ├── static_scan.py                 # 确定性检查（凭据/冲突/debugger/语言专项）+ 行级评论
│   └── __init__.py                    # build_registry（inspect_diff/static_scan/match_rules/knowledge_search）
├── knowledge/                         # 管线与评论结构 / 默认规则要点
├── tests/                             # pytest 28 用例
└── examples/                          # sample.diff + 报告（text/json）
```

## 使用方式

```bash
# 离线确定性管线（默认 text 报告；critical 时 exit 1 可接 CI）
git diff | python agents/code-reviewer/src/code_review_agent/cli.py - --offline
python agents/code-reviewer/src/code_review_agent/cli.py examples/sample.diff --offline --format json
python agents/code-reviewer/src/code_review_agent/cli.py examples/sample.diff --offline --keep-low --out report.md

# LLM 深度评审（语义层问题；先在 config.yaml 配置端点）
git diff | python agents/code-reviewer/src/code_review_agent/cli.py - --trace

# 测试
cd agents/code-reviewer && python -m pytest tests -q
```

## 与其他 Agent 的分工

- 破坏性 SQL/DDL 深检（全表 UPDATE/DELETE、DROP/TRUNCATE、mutation）→ `sql-danger-reviewer`（DGR-101~502）。
- 本 Agent 的 SQL 规则只做轻量提示并引导转交，不重复实现。

## 关联产物

- ZCode 技能：`.agents/skills/code-reviewer/`（SKILL.md + pipeline/rules 两篇 references）
