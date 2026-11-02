# 代码评审对抗 Agent（sql-danger-adversary，防御性红队）

## 定位

对本仓库自有的高危操作检测引擎（`../sql-danger-reviewer/tools/danger_tools/danger_scan.py`）做对抗测试与加固：生成混淆/伪装攻击语料，统计检出率与误报率，把打穿样本归因到规则缺口并给出回补建议。**仅限测试自有资产**——产出用于加固规范与引擎，不得用于绕过任何他人环境的审计或护栏。

## 已完成的 10 轮迭代（结论）

- 被测：danger_scan（DGR-1xx~5xx）；红队：10 级递进攻击技术（T1 明文 → T10 误报对抗），62 个攻击样本。
- 引擎基线曾为 **检出率 82% / 误报率 36%**（注释断词、恒真伪装、动态 PREPARE、守卫误判共 14 处缺口）；
  回补后终态 **第 10 轮检出率 100%、误报率 0%**。
- 过程与逐轮加固记录：`reports/iteration-report.md` + `reports/hardening-log.json`。

## 实现结构

```
sql-danger-adversary/
├── config.yaml / prompts/system.md   # 工具开关与红队守则（授权边界）
├── tools/adversary_tools/
│   ├── attack_gen.py                 # 确定性攻击语料生成器（T1~T10，expect 标注）+ evaluate
│   └── __init__.py                   # build_registry（generate_attacks/evaluate_attacks/run_iteration）
├── src/sql_adversary_agent/          # Agent 本体（离线：语料→评估→缺口归因→报告）
├── harness/iterate.py                # 10 轮递进迭代 harness（读 hardening-log 生成报告）
├── reports/                          # iteration-report.md + hardening-log.json
├── tests/                            # pytest 20 用例（语料形状/评估器回归检测/Mock LLM）
└── examples/
```

注：`tools/__init__.py`、`src/.../_bootstrap.py`、`tests/conftest.py` 会把被测引擎目录加入 sys.path——这是**评测专用耦合**（类似测试依赖被测对象），生产代码不 import 对方 Agent。

## 攻击技术体系（T1~T10）

明文基线 → 大小写/空白混淆 → 注释断词（`DR/**/OP`）→ 标识符引用 → 恒真伪装（`WHERE 1=1`/`IS NOT NULL`/自引用 IN/`LIKE '%'`/OR 混真）→ CTE/包裹 → 事务装饰 → 三明治掩埋 → 动态拼装（execute/f-string/拼接/EXECUTE IMMEDIATE/PREPARE）→ 误报对抗（字面量演示/注释提及/EXPLAIN/tmp 豁免/键守卫）。

判定：漏报攻击需 verdict=block；误报攻击需 verdict=pass。

## 使用方式

```bash
# 10 轮迭代（验收线：第 10 轮 100%/0%，未达标 exit 1）
python agents/sql-danger-adversary/harness/iterate.py --rounds 10

# 离线对抗报告（全量或指定技术级，如 "5" = T1..T5）
python agents/sql-danger-adversary/src/sql_adversary_agent/cli.py --offline --out report.md

# LLM 模式（可创造新技术级攻击，需配置端点）
python agents/sql-danger-adversary/src/sql_adversary_agent/cli.py "对检测引擎加压" --trace

# 测试
cd agents/sql-danger-adversary && python -m pytest tests -q
```

## 关联产物

- 被测引擎与规范：`../sql-danger-reviewer/`
- ZCode 技能：`.agents/skills/sql-danger-adversary/`
