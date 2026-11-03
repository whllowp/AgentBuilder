# commit 对抗测试报告（code-reviewer）

被测：`code-reviewer/tools/review_tools/static_scan.py`
语料：T1..T10，deterministic 24 条 + 语义基准 9 条

## 对抗结论

- ✅ 未被打穿：确定性检出率 100%，误报率 0%，打穿 0 处
- 语义基准 9 条已按边界声明导出（LLM 模式消化，不冒充通过）。

## 打穿样本
- 无。建议 LLM 模式创造新技术级继续加压。

## 复现命令
```bash
python agents/code-review-adversary/harness/iterate.py --rounds 10
```
