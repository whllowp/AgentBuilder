"""规则引擎：参考 alibaba/open-code-review 的模板化规则匹配与 rule.json 覆盖/合并机制。

优先级（与 open-code-review 一致）：
1. 显式传入的规则文本（--rule 对应）
2. 仓库级 `.opencodereview/rule.json`
3. 用户级 `~/.opencodereview/rule.json`
4. 内置默认规则

首个命中的用户规则默认**替换**内置规则；条目 `merge_system_rule: true` 则与内置合并。
每条规则：{path: glob, rule: 规则文本, merge_system_rule?: bool}。
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path

RULE_FILE_RELPATH = ".opencodereview/rule.json"

# 规则文本常量（fnmatch 不支持 {} 花括号展开，同族后缀逐条挂同一文本）
_RULE_TEXTS = {
    "js": (
        "JavaScript/TypeScript：禁用 debugger；console.log 调试语句不得合入；比较使用 === / !==；"
        "禁用 var；异步必须处理 rejection（catch 或 try/await）；TS 禁用 any 扩散（新代码优先具体类型）。"
    ),
    "test": "测试：新增/修改的业务逻辑需伴随测试；测试需覆盖异常分支；断言要具体（避免仅断言不抛错）。",
    "config": "配置：敏感项不得明文入库（走密钥管理）；配置变更需评估对既有环境的影响与回滚方式。",
}

# 内置默认规则：按路径特征聚焦检查点（模板化、确定性匹配；LLM 模式下作为"专属规则文本"注入）
DEFAULT_RULES: list[dict] = [
    {
        "path": "**/*",
        "rule": (
            "通用：新增代码中不得引入硬编码凭据（password/secret/token/api_key）；不得引入冲突标记；"
            "调试语句（debugger/console.log/print 调试）不得合入；新增 TODO/FIXME 需带负责人与工单。"
        ),
    },
    {
        "path": "**/*.java",
        "rule": (
            "Java（参考《阿里巴巴 Java 开发手册》要点）：线程池必须手动 new ThreadPoolExecutor 并明确参数，"
            "禁用 Executors 快捷方法；SimpleDateFormat 等非线程安全对象不得声明为 static 共享；"
            "不得捕获 Exception 后吞掉（空 catch 或仅 e.printStackTrace）；命名遵循驼峰与常量全大写下划线；"
            "集合/POJO 序列化与 equals/hashCode 成对实现。"
        ),
    },
    {
        "path": "**/*.py",
        "rule": (
            "Python：不得使用裸 except / except Exception 吞异常；不得使用可变默认参数；"
            "不得把调试 print 合入（用 logging）；资源使用 with 管理；类型注解按项目既有风格补齐。"
        ),
    },
    {
        "path": "**/*.go",
        "rule": (
            "Go：error 必须处理（至少显式 _ 忽略并注释原因）；不得忽略 err 返回值；"
            "goroutine 需有退出机制；defer 在循环中需评估资源泄漏。"
        ),
    },
    {
        "path": "**/*.sql",
        "rule": (
            "SQL：变更含破坏性 DDL/DML（全表 UPDATE/DELETE、DROP/TRUNCATE）必须标注审批工单；"
            "查询避免 SELECT *；建表/索引变更评估锁表窗口。深度检查可交由 sql-danger-reviewer Agent。"
        ),
    },
]

for _pat in ("**/*.js", "**/*.ts", "**/*.jsx", "**/*.tsx", "**/*.mjs", "**/*.cjs"):
    DEFAULT_RULES.append({"path": _pat, "rule": _RULE_TEXTS["js"]})

DEFAULT_RULES.append({"path": "**/test*/**", "rule": _RULE_TEXTS["test"]})
for _pat in (
    "**/test_*.py", "**/*_test.py", "**/*_test.go",
    "**/*Test.java", "**/*Tests.java", "**/*Test.kt",
    "**/*.test.js", "**/*.test.ts", "**/*.test.tsx", "**/*.spec.ts", "**/*.spec.js",
):
    DEFAULT_RULES.append({"path": _pat, "rule": _RULE_TEXTS["test"]})

for _pat in ("**/*.yaml", "**/*.yml", "**/*.toml", "**/*.json", "**/*.properties"):
    DEFAULT_RULES.append({"path": _pat, "rule": _RULE_TEXTS["config"]})


def load_user_rules(repo_root: str | Path | None = None) -> tuple[list[dict], str]:
    """按 open-code-review 优先级加载用户规则：仓库级 > 用户级 > 无。返回 (规则列表, 来源说明)。"""
    candidates = []
    if repo_root:
        candidates.append((Path(repo_root) / RULE_FILE_RELPATH, "repo"))
    candidates.append((Path.home() / ".opencodereview" / "rule.json", "user"))
    for path, source in candidates:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                rules = data.get("rules", [])
                if isinstance(rules, list):
                    return rules, f"{source}:{path}"
            except (json.JSONDecodeError, OSError):
                continue
    return [], "builtin"


def match_rules(path: str, user_rules: list[dict] | None = None, repo_root: str | Path | None = None) -> dict:
    """对单个文件路径做模板规则匹配。返回 {path, rules: [规则文本...], source}。

    - 用户规则按优先级整体加载；命中用户条目时默认替换内置，条目 merge_system_rule=true 则合并；
    - 同一来源内多条命中取并集。
    """
    if user_rules is None:
        user_rules, _ = load_user_rules(repo_root)

    builtin_hits = [r["rule"] for r in DEFAULT_RULES if fnmatch.fnmatch(path, r["path"])]

    user_hits = [r for r in user_rules if isinstance(r, dict) and fnmatch.fnmatch(path, str(r.get("path", "")))]
    if not user_hits:
        return {"path": path, "rules": builtin_hits, "source": "builtin"}

    merged: list[str] = []
    for r in user_hits:
        text = str(r.get("rule", "")).strip()
        if not text:
            continue
        if r.get("merge_system_rule") and builtin_hits and not merged:
            merged.extend(builtin_hits)
        merged.append(text)
    return {"path": path, "rules": merged, "source": "user"}
