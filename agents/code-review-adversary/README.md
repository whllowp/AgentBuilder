# commit 对抗红队 Agent（code-review-adversary，防御性）

## 定位

对本仓库自有的 code-reviewer 确定性引擎（`static_scan.py`）做 commit 级对抗测试：生成"看起来干净但有问题"的 diff（密钥伪装/调试变体/多行反模式/大 diff 掩埋/误报陷阱），评估检出率与误报率，归因缺口并回补；语义 bug 导出为 LLM 评审基准集（诚实度量，不冒充自动判定）。**仅限测试自有资产。**

## 10 轮迭代结论

- deterministic 攻击终态 **100% 检出 / 0% 误报**（曾打穿 3 处并回补：yaml 未加引号密钥、多行链式 Executors、测试路径假凭据误报）；
- 语义基准 9 条导出至 `reports/llm-benchmark.md`（差一错误/浮点相等/资源泄漏/朴素时区/无界重试/check-then-act/SQL 注入拼接/静默部分写/缓存击穿）。

## 使用方式

```bash
python agents/code-review-adversary/harness/iterate.py --rounds 10   # 验收线：全轮 100%/0%，未达标 exit 1
python agents/code-review-adversary/src/cr_adversary_agent/cli.py --offline
cd agents/code-review-adversary && python -m pytest tests -q
```

## 实现结构

`tools/cr_adversary_tools/commit_attack.py`（T1~T10 语料 + evaluate，low 按报告策略豁免）、`harness/iterate.py`（10 轮 + 报告 + 基准导出）、`reports/`（iteration-report / llm-benchmark / hardening-log）、`tests/`（5 用例）、`examples/`。评测专用耦合：bootstrap 引用被测引擎路径（生产代码不 import 对方）；包名用 `cr_adversary_tools` 与 sql-danger-adversary 的 `adversary_tools` 区分。

## 关联产物

ZCode 技能 `.agents/skills/code-review-adversary/`；被测 `../code-reviewer/`。
