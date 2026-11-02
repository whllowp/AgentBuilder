"""攻击语料生成器与评估器测试。"""
from adversary_tools.attack_gen import build_corpus, evaluate
from danger_tools.danger_scan import scan_code


def test_corpus_shape():
    corpus = build_corpus(10)
    assert len(corpus) >= 60
    tiers = {a["tier"] for a in corpus}
    assert tiers == set(range(1, 11))
    for a in corpus:
        assert a["expect"] in ("danger", "benign")
        assert a["technique"] and a["payload"]


def test_each_tier_has_attacks():
    for t in range(1, 11):
        assert build_corpus(t)[-1]["tier"] == t
        assert any(a["tier"] == t for a in build_corpus(t))


def test_ids_unique():
    corpus = build_corpus(10)
    ids = [a["id"] for a in corpus]
    assert len(ids) == len(set(ids))


def test_full_corpus_evaluated_green():
    stats = evaluate(build_corpus(10), scan_code)
    assert stats["recall"] == 1.0
    assert stats["fp_rate"] == 0.0
    assert stats["misses"] == []


def test_evaluate_detects_a_regression():
    """人为给一个未加固的哑扫描器，evaluate 必须能报出缺口。"""
    def dumb_scanner(_):
        return {"ok": True, "verdict": "pass", "findings": []}

    stats = evaluate([{"id": "X", "tier": 1, "technique": "plain",
                       "payload": "DROP TABLE dws.orders", "expect": "danger", "note": ""}], dumb_scanner)
    assert stats["recall"] == 0.0 and len(stats["misses"]) == 1
