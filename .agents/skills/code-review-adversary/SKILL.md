---
name: code-review-adversary
description: commit 对抗红队技能（防御性）。当用户想测试/加固 code-reviewer 的评审能力——生成"看起来干净但有问题"的 commit、评估检出率与误报率、给规则回补建议、跑 10 轮迭代——使用本技能。仅限测试本仓库自有评审引擎，不得用于绕过他人代码评审体系。
---

# commit 对抗（防御性红队）

被测：`agents/code-reviewer/tools/review_tools/static_scan.py`。攻击技术与判定标准详见 `agents/code-review-adversary/`。

## 授权边界（硬约束）

1. 只测试本仓库自有的评审引擎；攻击样本带 expect 标注（danger=漏报攻击 / benign=误报攻击）。
2. 打穿缺口的下一步是回补 static_scan 规则，不是利用缺口。
3. 语义 bug（差一错误/并发/泄漏/注入）归 llm-benchmark：导出为 LLM 评审基准集，**不冒充自动判定通过**。

## 工作流

1. 生成与评估：
   ```bash
   python agents/code-review-adversary/harness/iterate.py --rounds 10   # 验收线：deterministic 全轮 100%/0%
   python agents/code-review-adversary/src/cr_adversary_agent/cli.py --offline
   ```
2. 攻击技术 T1~T10：明文缺陷 → 密钥伪装（下划线标识符/yaml 未加引号/测试路径假凭据）→ 调试语句变体 → 反模式变体（多行链式）→ 大 diff 掩埋 → 过滤/路径对抗 → 误报攻击 → 多文件混合 → 语义基准 → 高级语义基准。
3. 打穿归因到机制（正则/报告策略/过滤器），回补后重跑 harness；加固历史见 `reports/hardening-log.json`。

## 判定标准

- 漏报攻击：须命中非 low 级发现；误报攻击：须无 critical/high/medium（low 按报告策略豁免）。

## 约束

- 每个结论带 payload 证据；语义基准集在 `reports/llm-benchmark.md`，供 LLM 模式加压。
