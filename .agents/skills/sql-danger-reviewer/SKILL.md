---
name: sql-danger-reviewer
description: 高危操作代码检验技能。凡是评审/检查 SQL 或数据代码中的破坏性变更——全表 UPDATE/DELETE（无 WHERE 或 WHERE 1=1）、DROP DATABASE/TABLE、TRUNCATE、ALTER DROP COLUMN/PARTITION、ClickHouse mutation、动态拼装的破坏语句、rm -rf——甚至用户只是贴了一段 SQL 问"能上线吗"——都必须用本技能按 DGR 规则给出 block/review/pass 结论与放行四件套。混淆形态（大小写、注释断词 DR/**/OP、恒真条件、CTE/事务包裹、三明治掩埋、f-string 动态拼装）同等拦截。
---

# 高危操作代码检验

按仓库规范《高危操作代码检验规范.md》（`agents/sql-danger-reviewer/高危操作代码检验规范.md`）拦截破坏性变更。规则目录与对抗手法详见 `references/danger-rules.md`；可执行的检测引擎在 `agents/sql-danger-reviewer/tools/danger_tools/danger_scan.py`。

## 工作流

1. **机器扫描优先**：能运行仓库引擎就不要肉眼替代（引擎已免疫混淆，10 轮对抗 100%/0%）：
   ```bash
   python -c "import sys; sys.path.insert(0,'agents/sql-danger-reviewer/tools'); from danger_tools.danger_scan import scan_code; import json; print(json.dumps(scan_code('''<代码>'''), ensure_ascii=False, indent=1))"
   ```
   或直接跑 Agent 报告：`python agents/sql-danger-reviewer/src/sql_danger_agent/cli.py "<代码>" --offline`
2. **规则核对**：读 `references/danger-rules.md` 确认分级、豁免与对抗对策，不要凭直觉定级。
3. **输出**：verdict（block/review/pass）+ 分级明细（规则号/证据原文/建议）+ 改写建议 + 放行四件套（审批-备份-回滚-窗口）。

## 关键原则

- 任一致命/高危 → **block**；`-- safe:` 注释只降一级、不解除非豁免 DROP 的阻断。
- 豁免路径：`tmp_`/`_staging` 前缀 DROP/TRUNCATE、EXPLAIN 前缀、键等值守卫（`WHERE id=5`）→ 提示级放行。
- 恒真即无守卫：`1=1` / `true` / `id IS NOT NULL` / 自引用 `IN (SELECT id FROM 同表)` / `LIKE '%'`；OR 任一恒真即恒真。
- 全部语句扫完再下结论；证据引用原始文本（非规范化后）。

## 约束

- 只评审不执行；不编造表结构等未知上下文。
- 中文回答，代码与标识符英文。
