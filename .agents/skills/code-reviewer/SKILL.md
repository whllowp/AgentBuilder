---
name: code-reviewer
description: AI 代码评审技能（设计参考阿里开源 open-code-review）。凡是用户给出 git diff / PR / 代码变更片段要求"评审、review、把把关、看看有没有问题、能合入吗"，或要求产出行级评审意见——都必须用本技能：确定性管线（文件筛选→智能打包→规则匹配→行级定位）+ 结构化评论（8 类 category、4 级 severity、suggestion_code），low 级默认丢弃备查；含凭据/冲突标记/debugger/裸异常/线程池等确定性检查与 Java/JS/TS/Py/Go/SQL 专属规则。
---

# 代码评审（参考 alibaba/open-code-review）

设计参考 [alibaba/open-code-review](https://github.com/alibaba/open-code-review)：确定性工程管线 + LLM 深度评审，
输出**行级定位**的结构化意见。本仓库的可执行实现在 `agents/code-reviewer/`。

## 工作流（4 步）

1. **收集业务上下文**：用用户给出的变更目的/影响面；缺失时基于 diff 推断并明示假设。
2. **执行评审**：
   - 确定性部分优先跑仓库引擎（不要肉眼重复机检）：
     ```bash
     git diff | python agents/code-reviewer/src/code_review_agent/cli.py - --offline
     # 或 JSON：--format json；保留 low：--keep-low；critical 时 exit 1 可接 CI
     ```
   - 语义层（逻辑/边界/并发/测试缺失）由模型按规则文本聚焦评审：读 `references/pipeline.md`（管线与评论结构）与 `references/rules.md`（默认规则与 rule.json 定制）。
3. **报告**：按 severity 分组（critical→high→medium）；文件统计（评审/过滤）；**丢弃疑似误报的 low**（附录备查）；结尾一句话结论（可合入 / 修复后可合入 / 阻断）。
4. **修复**：仅在用户明确要求时给修复，优先 critical/high/medium。

## 评论结构（每条意见的形态）

```json
{"path": "src/x.java", "content": "意见（中文）", "start_line": 42, "end_line": 42,
 "category": "bug", "severity": "high", "existing_code": "原行", "suggestion_code": "改写", "thinking": "依据"}
```

- `category ∈ bug|security|performance|maintainability|test|style|documentation|other`
- `severity ∈ critical|high|medium|low`；行号用**新文件行号**；定位失败置 0。

## 关键原则

- 只评审变更行，不翻旧账；不确定的问题降级为提问而不是断言。
- 破坏性 SQL（全表 UPDATE/DELETE、DROP/TRUNCATE）深检转 sql-danger-reviewer 技能/Agent（DGR 规则）。
- 不编造行号与代码；意见中文、代码英文。

## 规则定制

`.opencodereview/rule.json`：`{"rules": [{"path": "src/**/*.java", "rule": "<专属规则>", "merge_system_rule": true}]}`
优先级 --rule > 仓库 rule.json > ~/.opencodereview/rule.json > 内置；命中用户规则默认替换内置，merge_system_rule=true 合并。
