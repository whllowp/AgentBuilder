---
title: 评审管线与评论结构（open-code-review 设计要点）
keywords: 管线 文件筛选 打包 配对 规则匹配 glob rule.json merge_system_rule 行级定位 severity category 评论结构 low 丢弃 报告 sarif json 修复
source: alibaba/open-code-review（SKILL.md / README.zh-CN / 仓库实现）设计要点的本仓库移植
---

# 评审管线与评论结构

## 确定性管线（LLM 之前）

1. **精准文件筛选**：锁文件/生成物/三方库/二进制默认过滤（diff_utils.DEFAULT_FILTERS），但保留统计与清单（透明可审计）；单文件 diff 超大（>2000 行）打"拆分"标记而非静默跳过。
2. **智能打包**：关联文件合并为同一评审单元——实现-测试配对（OrderService ↔ OrderServiceTest）、同目录聚合；包上限 8 文件/1200 新增行。每个包上下文隔离、可并发（对应其 sub-agent 并发）。
3. **规则匹配（模板引擎）**：按路径 glob 匹配规则文本；优先级 `--rule` > 仓库 `.opencodereview/rule.json` > `~/.opencodereview/rule.json` > 内置；首个用户规则默认**替换**内置，`merge_system_rule: true` 则合并。规则文本用于聚焦 LLM 注意力、规避噪声。
4. **确定性检查**（static_scan）：凭据/冲突标记/debugger/裸 except/吞异常/Executors/static SimpleDateFormat/可变默认参数等，行级定位。
5. **LLM 深度评审**：在确定性结论之上做语义评审（逻辑/边界/并发/测试缺失）。

## 评论结构（8 类 category / 4 级 severity）

```
{path, content, start_line, end_line, category, severity, existing_code?, suggestion_code?, thinking?}
```

- category：bug / security / performance / maintainability / test / style / documentation / other
- severity：critical（阻断修复）/ high（合入前应修）/ medium（建议）/ low（nit）
- 行号 = 新文件行号；定位失败置 0 并说明。
- 输出格式：text（人读，按 severity 分组）/ json（机器消费）/ sarif（可接 GitHub Code Scanning）。

## 报告策略

- 按 severity 分组展示 critical→high→medium；**丢弃疑似误报的 low 项**（附录单列备查，可 --keep-low 保留）——low 类（style nit）误报率高，降噪优先。
- 文件级统计：总数 / 评审 / 过滤，附过滤清单。
- 结论一句话：可合入 / 修复后可合入 / 阻断。

## 修复策略

仅在明确要求时修复，优先 critical/high/medium；改用户代码前确认。

## 两种模式

- diff 评审（默认）：`git diff` 输入，只评审变更行；
- 全量扫描：无 git 历史时对整文件评审（本 Agent 离线管线聚焦 diff 模式；全量可把文件视作全新增行）。
