"""commit 对抗语料生成器：红队测试 code-reviewer 的确定性引擎（static_scan）。

两类攻击：
- deterministic：对 static_scan 可机检项做规避/伪装，判定标准明确（检出/误报可自动评估）；
- llm-benchmark：语义 bug（差一错误、并发、资源泄漏等）——确定性引擎按设计**不负责**，
  仅导出为 LLM 评审基准集（reports/llm-benchmark.md），不参与自动通过判定（诚实度量）。

用途限定（防御性红队）：仅测试本仓库自有评审引擎，用于回补规则；不得用于绕过他人评审体系。
"""
from __future__ import annotations

def _d(tier: int, technique: str, payload: str, expect: str, note: str = "") -> dict:
    return {"id": f"T{tier}-{abs(hash((technique, payload))) % 1000:03d}", "tier": tier,
            "technique": technique, "payload": payload, "expect": expect, "note": note,
            "kind": "deterministic"}


def _b(tier: int, technique: str, payload: str) -> dict:
    return {"id": f"B{tier}-{abs(hash((technique, payload))) % 1000:03d}", "tier": tier,
            "technique": technique, "payload": payload, "expect": None, "note": "LLM 语义基准（不自动判定）",
            "kind": "llm-benchmark"}


def _diff(path: str, lines: list[str]) -> str:
    body = "\n".join(f"+{l}" for l in lines)
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- a/dev/null\n+++ b/{path}\n"
        f"@@ -0,0 +1,{len(lines)} @@\n{body}\n"
    )


def _tier_attacks(tier: int) -> list[dict]:
    A: list[dict] = []

    if tier == 1:  # 明文基线：可机检缺陷应检出
        A.append(_d(1, "plain_secret", _diff("config.py", ['DB_PASSWORD = "prod-passw0rd-123"']), "danger"))
        A.append(_d(1, "plain_debugger", _diff("app.js", ["debugger;"]), "danger"))
        A.append(_d(1, "plain_conflict", _diff("a.txt", ["<<<<<<< HEAD"]), "danger"))
        A.append(_d(1, "plain_bare_except", _diff("w.py", ["try: run()", "except: pass"]), "danger"))
        A.append(_d(1, "plain_java_p3c", _diff(
            "Svc.java",
            ["private static SimpleDateFormat fmt = new SimpleDateFormat(\"yyyy\");",
             "ExecutorService pool = Executors.newFixedThreadPool(4);"]), "danger"))
        A.append(_d(1, "benign_clean", _diff("good.py", ["def add(a, b): return a + b"]), "benign"))
    elif tier == 2:  # 密钥伪装（确定性引擎职责范围内）
        A.append(_d(2, "secret_underscore_ident", _diff("cfg.py", ['DB_TOKEN = "tok-abcdef123456"']), "danger"))
        A.append(_d(2, "secret_yaml_style", _diff("app.yaml", ["api_key: sk-abcdefgh12345678"]), "danger"))
        A.append(_d(2, "secret_short_value_ok", _diff("cfg.py", ['TOKEN = "x"']), "benign", "值过短不构成凭据"))
        A.append(_d(2, "secret_in_test_path_ok", _diff("tests/test_cfg.py", ['TOKEN = "fake-token-12345678"']), "benign", "测试路径假凭据"))
    elif tier == 3:  # 调试语句伪装
        A.append(_d(3, "debugger_spacing", _diff("app.js", ["debugger ;"]), "danger"))
        A.append(_d(3, "console_in_test_ok", _diff("__tests__/a.test.js", ["console.log('case1');"]), "benign"))
        A.append(_d(3, "print_in_test_ok", _diff("test_x.py", ["print('debug in test')"]), "benign"))
    elif tier == 4:  # Java 反模式变体
        A.append(_d(4, "executors_multiline", _diff(
            "P.java", ["pool = Executors", "        .newCachedThreadPool();"]), "danger", "链式调用拆行"))
        A.append(_d(4, "printstacktrace_variant", _diff("P.java", ["e.printStackTrace ();"]), "danger"))
        A.append(_d(4, "sdf_nonstatic_ok", _diff("P.java", ["SimpleDateFormat f = new SimpleDateFormat(\"yyyy\");"]), "benign", "局部变量无并发问题"))
    elif tier == 5:  # 大 diff 掩埋（可机检项藏在大量良性行中间）
        noise = [f"def helper_{i}(): return {i}" for i in range(30)]
        A.append(_d(5, "bury_secret", _diff("big.py", noise + ['INTERNAL_SECRET = "sk-live-9f3e2d1c8b7a"'] + noise), "danger"))
        A.append(_d(5, "bury_debugger", _diff("big.js", [f"const v{i} = {i};" for i in range(30)] + ["debugger;"]), "danger"))
    elif tier == 6:  # 多文件/过滤器对抗
        A.append(_d(6, "real_code_in_lock_path", (
            "diff --git a/package-lock.json b/package-lock.json\n--- a/package-lock.json\n+++ b/package-lock.json\n"
            "@@ -1,0 +1,1 @@\n+\"evil\": true\n"), "benign",
            "锁文件被过滤器跳过属预期（统计透明），对抗点：路径伪装成生成物"))
        A.append(_d(6, "src_disguise_normal", _diff("src/app/helpers/util.py", ['API_SECRET = "sk-1234567890abc"']), "danger", "src 下正常路径"))
    elif tier == 7:  # 误报攻击（良性不得报）
        A.append(_d(7, "fp_equals_math", _diff("m.js", ["return a + b == c;"]), "benign", "== 在布尔表达式，可能合法？不——JS 规则按 low 且默认丢弃，verdict 应为 pass"))
        A.append(_d(7, "fp_todo_with_owner", _diff("t.py", ["# TODO(zhang): support retry #1234"]), "benign", "带负责人的 TODO 是 low"))
        A.append(_d(7, "fp_clean_ts", _diff("a.ts", ["const x: number = 1;"]), "benign"))
    elif tier == 8:  # 组合：一个 commit 多文件混合可机检问题
        combo = (_diff("c1.py", ['except:', 'PASSWORD = "p-assw0rd-777"'])
                 + _diff("c2.js", ["debugger;"]))
        A.append(_d(8, "multi_file_mix", combo, "danger", "两文件各藏一处"))
    elif tier == 9:  # 语义 bug 基准（LLM 评审的责任区，不自动判定）
        A.append(_b(9, "off_by_one", _diff("o.py", ["for i in range(len(items)):", "    process(items[i + 1])"])))
        A.append(_b(9, "float_equality", _diff("f.py", ["if total == 0.3: settle()"])))
        A.append(_b(9, "resource_leak", _diff("r.py", ["f = open('x')", "data = f.read()"])))
        A.append(_b(9, "tz_naive", _diff("t.py", ["ts = datetime.now()"])))
        A.append(_b(9, "unbounded_retry", _diff("u.py", ["while True:", "    try: fetch(); break", "    except: continue"])))
    elif tier == 10:  # 高级语义基准 + 声明边界
        A.append(_b(10, "concurrency_check_act", _diff("c.java", ["if (count > 0) { decrement(); }"])))
        A.append(_b(10, "sql_injection_concat", _diff("s.py", ["cursor.execute(\"SELECT * FROM t WHERE id = \" + user_id)"])))
        A.append(_b(10, "silent_partial_write", _diff("w.py", ["for row in rows:", "    sink.write(row)"])))
        A.append(_b(10, "cache_stampede", _diff("ch.py", ["def get(k):", "    v = cache.get(k)", "    if v is None:", "        v = db_load(k); cache.set(k, v)", "    return v"])))
    return A


def build_corpus(max_tier: int = 10) -> list[dict]:
    corpus: list[dict] = []
    for tier in range(1, max_tier + 1):
        corpus.extend(_tier_attacks(tier))
    return corpus


def evaluate(corpus: list[dict], scanner) -> dict:
    """对 deterministic 类攻击评估 static_scan；llm-benchmark 仅收集导出。"""
    from review_tools.diff_utils import parse_diff  # 评测专用耦合：被测方在 code-reviewer/tools

    results = []
    for atk in corpus:
        if atk["kind"] == "llm-benchmark":
            results.append({**atk, "verdict": "benchmark", "passed": None})
            continue
        parsed = parse_diff(atk["payload"])
        # 与 code-reviewer 报告策略一致：low 级默认丢弃（疑似误报备查），不构成命中
        findings = [f for f in scanner(parsed) if f["severity"] != "low"]
        has_issue = bool(findings)
        if atk["expect"] == "danger":
            passed = has_issue
        else:
            passed = not has_issue
        results.append({**atk, "verdict": "hit" if has_issue else "miss",
                        "findings_n": len(findings), "passed": passed})
    det = [r for r in results if r["kind"] == "deterministic"]
    bench = [r for r in results if r["kind"] == "llm-benchmark"]
    recall = sum(1 for r in det if r["expect"] == "danger" and r["passed"]) / max(
        sum(1 for r in det if r["expect"] == "danger"), 1)
    fp = 1 - (sum(1 for r in det if r["expect"] == "benign" and r["passed"]) / max(
        sum(1 for r in det if r["expect"] == "benign"), 1))
    return {
        "results": results,
        "det_total": len(det),
        "det_pass": sum(1 for r in det if r["passed"]),
        "recall": round(recall, 4),
        "fp_rate": round(fp, 4),
        "benchmark_n": len(bench),
        "misses": [r for r in det if not r["passed"]],
    }


__all__ = ["build_corpus", "evaluate", "_tier_attacks"]
