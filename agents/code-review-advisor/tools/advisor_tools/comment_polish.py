"""评审意见润色与语气检查：把"生硬的发现"转写成合适的代码评审意见。

两类能力：
1. polish(findings) —— 输入结构化发现（code-reviewer 的评论 JSON 或 {title, evidence, severity} 列表），
   按"问题-影响-建议-依据"结构 + 评审礼仪措辞生成合适意见（nit 标注、提问式表达不确定性）；
2. tone_check(draft) —— 对人工/模型草稿做语气检查：攻击性词汇、绝对化、人身指代、命令式，
   给出替换建议。
"""
from __future__ import annotations

import json
import re

# 语气检查：攻击性/绝对化/人身指代 → 替换建议
_TONE_RULES = [
    (re.compile(r"(愚蠢|垃圾|脑残|无语|离谱|乱写|low|太差)", re.IGNORECASE), "攻击性评价", "改为描述事实与影响：'这段逻辑在 X 场景下会 Y'"),
    (re.compile(r"(你|你们)[^，。；,;！!\n]{0,8}(又错|错了|不对|不行|没写|写错)", re.IGNORECASE), "人身指向", "对事不对人：'这处实现' 而非 '你'"),
    (re.compile(r"(必须|一定|绝对|肯定)"), "绝对化", "改为 '建议' 或说明依据；除非是安全/数据正确性问题"),
    (re.compile(r"(怎么会|为什么不等|难道|居然)", re.IGNORECASE), "反问质问", "改为中性提问：'这里是否考虑过 X？'"),
    (re.compile(r"(我早说过|早就该|说了多少次)", re.IGNORECASE), "翻旧账", "聚焦当前变更本身"),
]

# 意见结构模板（问题-影响-建议-依据）
_TEMPLATES = {
    "critical": "**[阻断] {title}**：{evidence}。影响：{impact}。建议：{suggestion}（依据：{ref}）——合入前需要解决。",
    "high": "**[应修] {title}**：{evidence}。建议：{suggestion}（依据：{ref}）。如时间紧张，可在回复中说明并拆 follow-up 工单。",
    "medium": "**[建议] {title}**：{evidence}。可考虑：{suggestion}。不阻塞合入，但建议本轮处理。",
    "low": "**[nit] {title}**：{evidence}。{suggestion} ——可改可不改，后续统一处理也行。",
}

_OPENERS = ("总体看这个变更方向没问题，以下是几点建议：",)
_CLOSERS = ("以上按优先级排列；有不同意的地方欢迎讨论，我可以补充更多上下文。",)

_IMPACT_FALLBACK = {
    "bug": "可能导致运行时错误或数据不正确",
    "security": "存在凭据泄露/安全风险",
    "performance": "可能在大流量下成为瓶颈",
    "maintainability": "会增加后续维护成本",
    "test": "回归风险缺少防护",
    "style": "与项目既有风格不一致",
    "documentation": "文档与行为可能脱节",
    "other": "存在需要确认的问题",
}


def _norm_finding(f: dict) -> dict:
    """兼容 code-reviewer 评论与通用 {title,...} 两种输入。"""
    return {
        "title": f.get("title") or f.get("content") or "问题",
        "evidence": (f.get("existing_code") or f.get("evidence") or "").strip() or "见标注行",
        "severity": (f.get("severity") or "medium").lower(),
        "category": (f.get("category") or "other").lower(),
        "suggestion": (f.get("suggestion_code") or f.get("suggestion") or "请补充具体改法").strip().rstrip("。"),
        "ref": f.get("thinking") or f.get("spec_ref") or f.get("rule_id") or "评审规则",
    }


def polish_findings(findings: list[dict] | str) -> dict:
    """输入结构化发现（list 或 JSON 字符串），输出润色后的评审意见文本与逐条映射。"""
    if isinstance(findings, str):
        try:
            findings = json.loads(findings)
        except json.JSONDecodeError:
            return {"ok": False, "error": "findings 不是合法 JSON 数组"}
    if not isinstance(findings, list) or not findings:
        return {"ok": False, "error": "未发现待润色的意见（findings 为空）"}

    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    items = sorted((_norm_finding(f) for f in findings if isinstance(f, dict)),
                   key=lambda x: sev_order.get(x["severity"], 9))
    lines = [_OPENERS[0], ""]
    polished = []
    for it in items:
        text = _TEMPLATES.get(it["severity"], _TEMPLATES["medium"]).format(
            title=it["title"].rstrip("。"),
            evidence=f"`{it['evidence'][:60]}`" if it["evidence"] else "见标注行",
            impact=_IMPACT_FALLBACK.get(it["category"], "见意见描述"),
            suggestion=it["suggestion"],
            ref=it["ref"],
        )
        polished.append({"severity": it["severity"], "text": text})
        lines.append(f"- {text}")
        lines.append("")
    lines.append(_CLOSERS[0])
    return {
        "ok": True,
        "count": len(polished),
        "polished": polished,
        "review_text": "\n".join(lines),
        "reply_templates": _reply_templates(items),
    }


def _reply_templates(items: list[dict]) -> list[str]:
    """给被评审者（committer/作者）的回复模板：接受/部分接受/反驳三类。"""
    return [
        "接受：'{title}' 已在 <commit/PR 链接> 修复，感谢指出。".format(title=items[0]["title"] if items else "…"),
        "部分接受：'{title}' 本轮修复主问题，剩余拆 follow-up：<工单链接>。".format(title=items[0]["title"] if items else "…"),
        "说明背景：'{title}' 之所以这样写是因为 <原因>；已补充测试/注释证明当前行为正确，若仍有顾虑可以再讨论。".format(title=items[0]["title"] if items else "…"),
    ]


def tone_check(draft: str) -> dict:
    """对评审意见草稿做语气检查，返回违规项与改写建议。"""
    issues = []
    for pattern, label, fix in _TONE_RULES:
        for m in pattern.finditer(draft or ""):
            start = max(m.start() - 20, 0)
            ctx = draft[start : m.end() + 20].replace("\n", " ")
            issues.append({"type": label, "matched": m.group(0), "context": ctx.strip(), "fix": fix})
    return {
        "ok": not issues,
        "issues": issues,
        "summary": ("语气检查通过：对事不对人、可执行、无攻击性措辞" if not issues
                    else f"发现 {len(issues)} 处语气问题（{', '.join(sorted({i['type'] for i in issues}))}），已给替换建议"),
    }
