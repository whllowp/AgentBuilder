# 高危操作代码检验 Agent（sql-danger-reviewer）

## 定位

在代码合入前拦截破坏性变更：全表 UPDATE/DELETE（无 WHERE 或恒真条件）、删库删表（DROP DATABASE/TABLE）、TRUNCATE、ALTER 破坏子句（DROP COLUMN/PARTITION）、ClickHouse mutation、动态拼装的破坏语句、rm -rf 危险删除。**已实现 v0.1**：DGR-1xx~5xx 规则引擎（对抗混淆免疫）+ LLM 工具回路 + 离线管线 + CI 可用的退出码（block → exit 1）。

知识底座：《高危操作代码检验规范.md》（Agent 根目录）——风险四级分级、规则目录、豁免与放行机制（tmp 命名 / safe 标记只降级 / 键等值守卫 / 审批四件套）、对抗（混淆）对策。经 10 轮红队对抗迭代验证：**检出率 100%、误报率 0%**（见 `../sql-danger-adversary/reports/iteration-report.md`）。

## 输入 / 输出

- 输入：SQL 脚本，或含 SQL 的应用/脚本代码（Python/Java 动态拼接、shell 命令）
- 输出（Markdown 报告 + 结构化结果）：
  - `verdict`：block（致命/高危，阻断合入）/ review（中危）/ pass
  - 分级发现：规则号（DGR-xxx）、级别、**原始文本证据**、建议
  - `requires_approval` + 放行四件套（审批-备份-回滚-窗口）
  - 改写建议（键等值 WHERE、RENAME 归档代替 DROP、轻量删除代替 mutation）

## 实现结构

```
sql-danger-reviewer/
├── 高危操作代码检验规范.md      # 规范原文（DGR-101~502 + 豁免 + 对抗对策）
├── config.yaml / prompts/system.md
├── src/sql_danger_agent/        # Agent 本体（LLM 回路 + 离线管线 + CLI，block 时 exit 1）
├── tools/danger_tools/
│   ├── danger_scan.py           # 检测引擎：字符串掩码、注释双规范化、恒真判定、动态SQL、脚本命令
│   └── __init__.py              # build_registry（danger_scan / knowledge_search / approval_checklist）
├── knowledge/                   # 规则目录 + 对抗手法（供检索）
├── tests/                       # pytest 26 用例（规则/豁免/混淆/误报/Mock LLM）
└── examples/
```

## 引擎对抗能力（规范第 3 章，全部免疫）

大小写/空白混淆、注释断词（`DR/**/OP`，双规范化并集匹配）、反引号标识符、恒真伪装（`1=1`/`true`/`IS NOT NULL`/自引用 IN/`LIKE '%'`/OR 组合）、CTE/子查询包裹、事务装饰（不降级）、三明治掩埋（逐条扫描）、动态拼装（execute/f-string/拼接/EXECUTE IMMEDIATE/PREPARE）、误报对抗（字面量/注释/EXPLAIN/tmp 豁免/键守卫 → 提示级放行）。

## 使用方式

```bash
# 离线评审（block 时退出码 1，可直接接入 CI）
python agents/sql-danger-reviewer/src/sql_danger_agent/cli.py "UPDATE dws.orders SET status=9 WHERE 1=1" --offline
cat hotfix.sql | python agents/sql-danger-reviewer/src/sql_danger_agent/cli.py - --offline --out report.md

# LLM 模式（config.yaml 配置端点或环境变量）
python agents/sql-danger-reviewer/src/sql_danger_agent/cli.py "待评审代码" --trace

# 测试
cd agents/sql-danger-reviewer && python -m pytest tests -q
```

## 关联产物

- 红队：`../sql-danger-adversary/`（10 轮对抗迭代 + harness + 报告）
- ZCode 技能：`.agents/skills/sql-danger-reviewer/`
