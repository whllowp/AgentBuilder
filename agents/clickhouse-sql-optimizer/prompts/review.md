# SQL / DDL 复查清单（LLM 模式二阶段复查用）

对一阶段产出（审查发现 + 改写建议 / 建表方案）逐项核对：

## SQL 审查

- [ ] `SELECT *` 已消除，列清单最小化
- [ ] WHERE 命中排序键前缀 / 分区列；键列上无函数包裹（toDate/toYYYYMM/substr/算术）
- [ ] 时间条件为半开区间（`>= d AND < d+1`），非等值函数
- [ ] 分页无大 OFFSET（keyset 分页）
- [ ] JOIN：小表在右、两侧先收敛行数/列数、数量 ≤ 3~4、键类型一致；维表场景已评估字典
- [ ] FINAL：仅低频；高频路径给出 argMax MV / LIMIT 1 BY 替代
- [ ] `LIKE '%x%'` 有对应 tokenbf/ngrambf/inverted 索引建议
- [ ] `count(DISTINCT)` 高基数场景给出 uniq/uniqCombined 替代
- [ ] 资源防护：max_execution_time / max_rows_to_read 建议已给出

## DDL 审查 / 建表方案

- [ ] 引擎选型正确（去重/回撤/聚合语义匹配业务）
- [ ] ORDER BY 低基数在前、时间在后；PRIMARY KEY 是前缀
- [ ] 分区粒度与 TTL 对齐，无过度分区
- [ ] 无 Nullable 滥用；金额 Decimal；时间 DateTime；低基数 LowCardinality
- [ ] 跳数索引在非键过滤列上，类型选型正确
- [ ] ReplacingMergeTree 有单调版本列；Collapsing 有 Sign 且查询带 SUM(Sign*x)
- [ ] 生成的建表方案已通过 advise_ddl 自检（无 error 级问题）

## 建议质量

- [ ] 每条建议有预期收益依据（granule/part 裁剪率、扫描量）
- [ ] 改写示例完整可执行，未编造用户 schema 中不存在的列
- [ ] 迁移类建议（改 ORDER BY/分区）说明了代价与步骤
- [ ] 慢查询问题给出了六步 SOP 的定制路径与验证 SQL
