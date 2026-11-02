# 评审管线与评论结构

来源：alibaba/open-code-review 设计要点（本仓库移植版），详见 `agents/code-reviewer/knowledge/pipeline-and-schema.md`。

## 确定性管线（LLM 之前）

1. **精准文件筛选**：锁文件（package-lock/yarn.lock/go.sum…）、生成物（.min.js/.map/*.pb.go）、三方目录（vendor/node_modules/dist）、二进制默认过滤；统计与清单保留（透明）。单文件 diff > 2000 行打"拆分"标记不静默跳过。
2. **智能打包**：实现-测试配对（OrderService ↔ OrderServiceTest / test_x.py ↔ x.py）+ 同目录聚合；包上限 8 文件 / 1200 新增行；每包即一个可并发的评审单元。
3. **规则匹配（模板引擎）**：路径 glob → 规则文本（内置 Java/JS/TS/Py/Go/SQL/测试/配置 + 通用）；用户 rule.json 覆盖/合并语义与 open-code-review 一致。
4. **确定性检查**（新增行，行级定位）：凭据(critical)、冲突标记(critical)、debugger(high)、裸 except/吞异常(high)、空 catch(high)、Executors 线程池(medium)、static SimpleDateFormat(medium)、可变默认参数(medium)、e.printStackTrace(medium)。
5. **LLM 深度评审**：语义问题（逻辑错误、边界、并发、测试缺失），规则文本聚焦注意力。

## 评论结构与语义

- 字段：path / content / start_line / end_line / category / severity / existing_code? / suggestion_code? / thinking?
- 行号 = 新文件行号（diff hunk 头 `@@ -a,b +c,d @@` 的 c 起算，只数新增与上下文行）；失败置 0。
- category：bug / security / performance / maintainability / test / style / documentation / other
- severity：critical（阻断）/ high（合入前应修）/ medium（建议）/ low（nit）

## 报告策略

- 按 severity 分组展示；**low 默认丢弃**（误报率高，附录单列备查，--keep-low 保留）。
- 文件统计：总数 / 评审 / 过滤 + 过滤清单。
- 结论：⛔ 阻断（有 critical）/ ⚠️ 修复后可合入（有 high）/ ✅ 可合入。
- 输出格式 text（人读）/ json（机器消费；sarif 思路同源，可接 CI）。
