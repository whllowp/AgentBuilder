# code-reviewer 对抗迭代报告（10 轮）

红队：`agents/code-review-adversary`（commit 攻击技术 T1~T10）
被测：`agents/code-reviewer/tools/review_tools/static_scan.py`（确定性引擎；LLM 语义层另见基准集）

## 结论
- ✅ deterministic 攻击全轮 100%/0%
- 终态：确定性攻击检出率 100%、误报率 0%；语义基准 9 条导出至 llm-benchmark.md（由 LLM 模式消化，不自动判定）
- 开发迭代史：红队曾打穿 3 处（yaml 未加引号密钥、多行链式 Executors、测试路径假凭据误报），已回补：SECRET_UNQUOTED_RE、跨行 Executors 检测、测试路径凭据降 low（详见 hardening-log.json）

## 逐轮结果

| 轮 | 技术 | 检出率 | 误报率 | 打穿 | 语义基准 | 本轮加固 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 明文缺陷基线 | 100% | 0% | 0 | 0 | 基线：可机检项（凭据/debugger/冲突标记/裸 except/P3C 反模式）明文检出与良性放行 |
| 2 | 密钥伪装 | 100% | 0% | 0 | 0 | 回补 yaml 未加引号密钥（SECRET_UNQUOTED_RE：值≥8 位且含字母+数字）；测试路径假凭据降为 low（默认丢弃）防误报 |
| 3 | 调试语句伪装 | 100% | 0% | 0 | 0 | 调试语句变体（debugger ;）由 \b 词边界天然覆盖；测试路径 console/print 豁免已在基线 |
| 4 | 反模式变体 | 100% | 0% | 0 | 0 | 回补多行链式 Executors（拼接新增行源码检测，行号归到含 Executors 的行）；printStackTrace 带空格变体天然覆盖；非 static SimpleDateFormat 保持不报（局部变量无并发问题） |
| 5 | 大 diff 掩埋 | 100% | 0% | 0 | 0 | 大 diff 掩埋（30+ 良性行藏凭据/debugger）：逐行扫描天然覆盖 |
| 6 | 过滤/路径对抗 | 100% | 0% | 0 | 0 | 路径对抗：锁文件被过滤器跳过属预期（统计透明）；src 正常路径密钥检出 |
| 7 | 误报攻击 | 100% | 0% | 0 | 0 | 误报攻击（== 布尔比较/带负责人 TODO/干净 TS）：low 级按报告策略丢弃，verdict=pass |
| 8 | 多文件混合 | 100% | 0% | 0 | 0 | 多文件混合：逐文件扫描天然覆盖 |
| 9 | 语义 bug 基准 | 100% | 0% | 0 | 5 | 语义 bug（差一/浮点相等/资源泄漏/朴素时区/无界重试）：确定性引擎按设计不负责，导出 llm-benchmark.md 供 LLM 模式加压（诚实度量，不冒充通过） |
| 10 | 高级语义基准 | 100% | 0% | 0 | 9 | 高级语义基准（check-then-act/SQL 注入拼接/静默部分写/缓存击穿）：同上导出基准集 |

## 边界声明

- deterministic 攻击针对可机检项（凭据/调试/反模式/掩埋）——自动判定；
- 语义 bug（差一错误、并发、泄漏、注入）是 LLM 评审的责任区，导出为基准集不冒充通过。

## 复现
```bash
python agents/code-review-adversary/harness/iterate.py --rounds 10
```