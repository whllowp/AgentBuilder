---
name: sql-danger-adversary
description: 代码评审对抗技能（防御性红队）：当用户想测试、加固、挑战本仓库的高危操作检测能力（sql-danger-reviewer / danger_scan）时使用——生成混淆/伪装攻击语料（大小写、注释断词、恒真 WHERE、CTE/事务/三明治包裹、动态拼装、良性伪装）、评估检出率与误报率、给出规则回补建议、跑 10 轮递进迭代。仅限测试自有检测引擎，不得用于绕过他人环境的审计或护栏。
---

# 代码评审对抗（防御性红队）

被测对象：`agents/sql-danger-reviewer/tools/danger_tools/danger_scan.py`（DGR 规则引擎）。
攻击技术体系与判定标准详见 `references/attack-techniques.md`。

## 授权边界（硬约束）

1. 只测试本仓库自有的检测引擎与其规则。
2. 产出的攻击样本一律带 expect 标注（danger=漏报攻击 / benign=误报攻击），用于回补规则。
3. 发现缺口的下一步是**回补规范与引擎**，不是利用缺口；不得协助绕过任何他人环境的审计/护栏。

## 工作流

1. **生成攻击**：用仓库语料生成器（确定性、覆盖 T1~T10）或自行构造新技术（必须标注 technique 与 expect）：
   ```bash
   python -c "import sys; sys.path.insert(0,'agents/sql-danger-adversary/tools'); sys.path.insert(0,'agents/sql-danger-reviewer/tools'); from adversary_tools.attack_gen import build_corpus; from danger_tools.danger_scan import scan_code; from adversary_tools.attack_gen import evaluate; import json; print(json.dumps(evaluate(build_corpus(10), scan_code)['misses'], ensure_ascii=False, indent=1))"
   ```
2. **评估**：漏报攻击需 verdict=block（致命/高危）；误报攻击需 verdict=pass（提示级允许）。
3. **归因**：把打穿样本归因到机制层（正则/守卫分析/掩码/降级路径），对应 DGR 编号给回补建议。
4. **迭代验证**：`python agents/sql-danger-adversary/harness/iterate.py --rounds 10`（验收线：第 10 轮 100%/0%）；完整历史见 `agents/sql-danger-adversary/reports/`。

## 输出

`## 对抗结论`（检出率/误报率/打穿数）→ `## 打穿样本`（payload+期望+实际+归因）→ `## 回补建议`（DGR 条目级）→ `## 复现命令`。

## 约束

- 每个结论必须有 payload 证据；不凭感觉评价检测器强弱。
- 中文回答，payload 用英文代码。
