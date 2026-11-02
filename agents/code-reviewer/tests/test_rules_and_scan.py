"""规则引擎（glob 匹配 / rule.json 覆盖与合并）与静态扫描测试。"""
from review_tools.rule_engine import match_rules
from review_tools.static_scan import group_report, scan_diff
from review_tools.diff_utils import parse_diff


def _diff(path, lines):
    body = "\n".join(f"+{l}" for l in lines)
    return (
        f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
        f"@@ -1,0 +1,{len(lines)} @@\n{body}\n"
    )


# ---------------- 规则匹配 ----------------

def test_builtin_rules_by_language():
    assert any("Java" in r for r in match_rules("src/A.java")["rules"])
    assert any("TypeScript" in r or "JavaScript" in r for r in match_rules("src/a.ts")["rules"])
    assert any("Python" in r for r in match_rules("app/run.py")["rules"])
    assert any("SQL" in r for r in match_rules("sql/init.sql")["rules"])
    assert any("测试" in r for r in match_rules("src/test_x.py")["rules"])


def test_user_rule_replaces_builtin_by_default():
    user = [{"path": "**/*.java", "rule": "CUSTOM-JAVA-RULE"}]
    r = match_rules("src/A.java", user_rules=user)
    assert r["source"] == "user"
    assert r["rules"] == ["CUSTOM-JAVA-RULE"]


def test_user_rule_merge_with_builtin():
    user = [{"path": "**/*.java", "rule": "CUSTOM-JAVA-RULE", "merge_system_rule": True}]
    r = match_rules("src/A.java", user_rules=user)
    assert "CUSTOM-JAVA-RULE" in r["rules"]
    assert any("Java" in x for x in r["rules"])  # 内置仍保留


def test_no_match_returns_empty():
    r = match_rules("docs/README.md", user_rules=[])
    assert r["rules"] == [] or all("Java" not in x for x in r["rules"])


# ---------------- 静态扫描 ----------------

def test_secret_critical():
    comments = scan_diff(parse_diff(_diff("config/app.py", ['API_KEY = "sk-12345678-abcd"'])))
    assert any(c["severity"] == "critical" and c["category"] == "security" for c in comments)


def test_conflict_marker_critical():
    comments = scan_diff(parse_diff(_diff("a.txt", ["<<<<<<< HEAD"])))
    assert any(c["severity"] == "critical" and "冲突" in c["content"] for c in comments)


def test_debugger_high_and_console_low():
    comments = scan_diff(parse_diff(_diff("app/main.js", ["debugger;", "console.log('x');"])))
    assert any(c["severity"] == "high" and "debugger" in c["content"] for c in comments)
    assert any(c["severity"] == "low" and "console.log" in c["content"] for c in comments)


def test_python_bare_except_and_mutable_default():
    comments = scan_diff(parse_diff(_diff("app/w.py", ["except:", "def f(x=[]): pass"])))
    assert any(c["severity"] == "high" and "裸 except" in c["content"] for c in comments)
    assert any(c["severity"] == "medium" and "可变默认参数" in c["content"] for c in comments)


def test_python_swallowed_exception():
    d = _diff("app/s.py", ["try:", "    run()", "except Exception:", "    pass"])
    comments = scan_diff(parse_diff(d))
    assert any(c["severity"] == "high" and "吞异常" in c["content"] for c in comments)


def test_java_p3c_rules():
    lines = [
        "private static SimpleDateFormat fmt = new SimpleDateFormat(\"yyyy\");",
        "ExecutorService pool = Executors.newFixedThreadPool(4);",
        "} catch (Exception e) { e.printStackTrace(); }",
    ]
    comments = scan_diff(parse_diff(_diff("src/A.java", lines)))
    assert any("SimpleDateFormat" in c["content"] for c in comments)
    assert any("Executors" in c["content"] for c in comments)
    assert any("printStackTrace" in c["content"] for c in comments)


def test_todo_without_owner_is_low():
    comments = scan_diff(parse_diff(_diff("a.py", ["# TODO fix this"])))
    assert any(c["severity"] == "low" and "TODO" in c["content"] for c in comments)


def test_line_localization():
    comments = scan_diff(parse_diff(_diff("config/app.py", ["x = 1", 'API_KEY = "sk-12345678"'])))
    secret = next(c for c in comments if c["category"] == "security")
    assert secret["start_line"] == 2 and secret["end_line"] == 2


def test_report_drops_low_by_default():
    comments = scan_diff(parse_diff(_diff("app/main.js", ["console.log('x');"])))
    rep = group_report(comments, keep_low=False)
    assert rep["kept"] == [] and len(rep["dropped_low"]) == 1
    rep2 = group_report(comments, keep_low=True)
    assert len(rep2["kept"]) == 1


def test_clean_diff_no_comments():
    comments = scan_diff(parse_diff(_diff("app/good.py", ["def add(a, b): return a + b"])))
    assert comments == []
