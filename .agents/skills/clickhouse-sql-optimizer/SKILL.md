---
name: clickhouse-sql-optimizer
description: ClickHouse 建表方案生成、SQL 审查、慢 SQL 定位与优化技能。凡是用户提到 ClickHouse/CK 建表/设计表、慢查询定位、排序键/ORDER BY/分区/跳数索引/物化视图/投影、JOIN 或字典优化、ReplacingMergeTree 去重/FINAL、query_log/EXPLAIN 诊断——即便没有明说"优化"——都应使用本技能按《clickhouse开发规范》给出带依据的建表模板、改写建议与六步定位流程。
---

# ClickHouse SQL 优化

按仓库规范完成 ClickHouse 的建表方案生成、SQL/DDL 审查与慢 SQL 定位优化。规范的完整原文在
`agents/clickhouse-sql-optimizer/clickhouse开发规范.md`，提炼后的知识库在
`agents/clickhouse-sql-optimizer/knowledge/`（7 篇，含慢 SQL 六步 SOP）。

## 工作流

1. **识别输入类型**：
   - 建表需求描述（"帮我建一张表"+ 场景关键词）→ 读 `references/ddl-codegen.md`，按场景（append_log/cdc_upsert/collapsing/agg_rollup）生成合规 DDL，再按 DDL 检查清单自检；
   - `CREATE TABLE` → DDL 评估（读 `references/ddl-and-explain.md` 的 DDL 部分）；
   - EXPLAIN 输出（含 `Granules:`/`Parts:`/`Key Condition`）→ 执行计划解读（同上文件的 EXPLAIN 部分）；
   - SELECT/INSERT/ALTER → SQL 审查（读 `references/sql-review-rules.md`）；
   - "查询慢/超时"类问题 → 先走 `references/slow-query-sop.md` 六步 SOP（发现→取证→归因→改写→验证→固化）；
   - 混合输入逐类处理；只有现象没有语句时，先请用户给出 SQL、`SHOW CREATE TABLE` 或 EXPLAIN 输出。
2. **逐条规则检查**，记录级别（❌强制 / ⚠️建议 / ℹ️提示）、证据（命中的 SQL 片段）、建议、规范条目编号。
3. **给出可执行产物**：建表给完整 DDL（+MV/查询示例）；查询给改写示例（SQL 代码块）；每条建议附预期收益依据（granule/part 裁剪率、扫描列数），不接受"感觉会快"。
4. **给出验证手段**：`EXPLAIN indexes = 1` 与 `system.query_log`/`system.parts` 诊断 SQL（模板见 references）。

## 核心规则速查（完整版在 references）

| 主题 | 一句话规则 |
|------|-----------|
| ORDER BY | 低基数列在前、时间列在后，≤4 列；上线后不可改（100x 级影响） |
| 分区 | 数据管理手段而非加速手段；超过几十个分区多半过度（可慢 46x）；粒度对齐 TTL（≤7 天用日，否则月） |
| 查询 | 禁 `SELECT *`；必带 WHERE 且命中排序键前缀；键列不套函数（`toDate(ts)=d` → `ts>=d AND ts<d+1`） |
| 分页 | 禁大偏移 `LIMIT 100000,20` → keyset 分页 |
| JOIN | 小表放右、交互查询 ≤3~4 个；维表优先 `dictGet` 字典（约 3x）；大 JOIN 用 grace_hash |
| 去重 | FINAL 有查询时代价；高频路径用 MV+argMax 或 `LIMIT 1 BY`；Collapsing 必须 `SUM(Sign*x)` |
| 写入 | 批量 INSERT ≥数千行/间隔 ≥1s，否则 `async_insert=1`；禁单行 VALUES 循环 |
| 删除 | 日常用轻量 `DELETE FROM`；mutation 只放低峰批量 |
| 类型 | 金额 Decimal（禁 Float）、时间 DateTime、低基数 LowCardinality、避免 Nullable |
| 跳数索引 | 只加在非排序键的常过滤列：minmax/set/bloom_filter/tokenbf/ngrambf |
| 慢 SQL | 六步 SOP：发现（query_log）→ 取证（ProfileEvents）→ 归因（EXPLAIN 三指标决策树）→ 改写 → 验证（EXPLAIN ANALYZE）→ 固化（熔断/索引沉淀/告警） |

## 可选：调用本仓库的离线管线生成结构化报告

不需要 LLM 的规则管线已实现（94 个 pytest 用例覆盖），可直接运行：

```bash
python agents/clickhouse-sql-optimizer/src/clickhouse_agent/cli.py "<SQL / DDL / EXPLAIN / 建表需求描述>" --offline --out report.md
```

用户需要落盘的 Markdown 报告、或输入量大时用它；日常问答直接按上面的规则回答即可。

## 输出格式

按此 Markdown 结构输出（无发现的段落省略）：

```
## 建表方案（建表任务）
DDL 代码块 + 设计要点 + 自检结果
## 审查发现
| 级别 | 规则 | 证据 | 建议 |
## 优化建议
逐条：问题 → 改写示例（SQL 块）→ 预期收益依据
## 慢 SQL 定位与优化流程
六步 SOP 定制到当前问题
## 诊断与验证
EXPLAIN / system.* 验证 SQL
## 规范依据
引用《clickhouse开发规范.md》条目（如 规范 4.1-3）
```

## 约束

- 不臆造用户未提供的 schema：表结构未知时说明假设并请用户补 `SHOW CREATE TABLE`；建表方案的列按用户描述映射，未给的用注释占位并说明。
- 只产出建议 SQL/DDL，不执行任何对生产库的变更。
- 回答用中文，SQL 与标识符用英文。
