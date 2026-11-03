# 代码评审意见顾问 Agent（code-review-advisor）

## 定位

把"生硬的评审发现"转写成**合适的代码意见**（对事不对人、可执行、有依据、分级明确），并对人工/模型草稿做语气把关；同时给被评审者（committer/作者）提供回复模板。上游对接 code-reviewer 的结构化发现。**已实现 v0.1**：润色引擎（问题-影响-建议-依据 + nit 分级 + 开场收尾礼仪）+ 五类语气红线检查 + LLM/离线双模式。

## 使用方式

```bash
# 润色发现列表（JSON）为合适意见 + 作者回复三模板
python agents/code-review-advisor/src/review_advisor_agent/cli.py '<JSON>' --offline

# 草稿语气检查（有红线时 exit 1）
echo "这段写得也太垃圾了，你怎么又错了" | python agents/code-review-advisor/src/review_advisor_agent/cli.py - --offline

# 测试
cd agents/code-review-advisor && python -m pytest tests -q
```

## 实现结构

`tools/advisor_tools/comment_polish.py`（润色 + 语气检查）、`knowledge/review-etiquette.md`（礼仪与模板）、`src/review_advisor_agent/`（双模式 + CLI）、`tests/`（9 用例）、`examples/`（润色/语气两份示例）。

## 关联产物

ZCode 技能 `.agents/skills/code-review-advisor/`；上游 `../code-reviewer/`（结构化发现）。
