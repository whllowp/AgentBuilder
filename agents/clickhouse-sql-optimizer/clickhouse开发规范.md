# ClickHouse 开发规范

> 版本：v1.1（2026-11）
> 适用范围：ClickHouse 23.x ~ 26.x，OLAP 分析场景的建表、写入、查询与运维。
> 参考来源：ClickHouse 官方文档与官方博客最佳实践（ORDER BY/分区/跳数索引/JOIN/去重/系统表）、Altinity 知识库、社区实践。
> 变更：v1.1 增加慢 SQL 定位六步 SOP（5.1）与建表场景模板（附录 7.5）。

规则级别定义：

| 级别 | 含义 |
|------|------|
| 【强制】 | 必须遵守，违反会造成性能、稳定性或正确性问题 |
| 【建议】 | 应当遵守，多数场景收益明显 |
| 【可选】 | 按场景取舍，需说明理由 |

---

## 1. 总则

1. 【强制】ClickHouse 是列存 OLAP 引擎，**不是**事务型数据库。点查（按主键查单行）、高频小事务更新、强一致多表事务不是它的战场；这类需求走 MySQL/PostgreSQL 或 KV 存储。
2. 【强制】一切优化的第一性原理：**让查询读更少的列、更少的行（granule）、更少的 part**。排序键、分区、跳数索引、投影、物化视图都是围绕这三个"更少"服务的。
3. 【强制】批量思维：写入要批量，查询要大批扫描（而不是循环发小查询）。应用层"for 循环 + 单条 INSERT/SELECT"的模式一律禁止。
4. 【建议】优化前先测量：`system.query_log` + `EXPLAIN` 定位瓶颈（I/O、CPU、网络、内存），再动手；优化后回归对比 `ProfileEvents` 与 `elapsed`。完整流程见 5.1 六步 SOP。

---

## 2. 建表规范

### 2.1 库表与命名

1. 【强制】库名、表名、列名使用小写英文 + 下划线，不用中文、不用数据库保留字；临时/中间表以 `tmp_` 或 `_staging` 前缀并在用完 24h 内删除。
2. 【强制】所有表必须有注释（`COMMENT`），列有业务含义的也要注释。ClickHouse 的 schema 演进虽灵活，但删列/改类型代价高，注释是最便宜的文档。
3. 【建议】同一业务域的表集中在同一数据库，便于权限与 TTL 统一管理。

### 2.2 表引擎选择

1. 【强制】默认使用 `MergeTree` 家族。选型顺序：

| 场景 | 引擎 | 关键参数 |
|------|------|----------|
| 追加写、无去重需求 | `MergeTree` | — |
| 同主键保留最新版本（CDC 入湖、Upsert） | `ReplacingMergeTree` | `[version_col]`、`is_deleted`（配合 `FINAL` / `argMax`） |
| 行数增减语义（聚合态回撤） | `CollapsingMergeTree(Sign)` / `VersionedCollapsingMergeTree(Sign, Ver)` | Sign 取值 ±1 |
| 预聚合汇总（配合物化视图） | `SummingMergeTree` / `AggregatingMergeTree` | 聚合列用 `AggregateFunction` 状态类型 |
| 有 TTL 的明细大表 | `MergeTree + TTL ... DELETE` | 分区按月/周对齐 TTL 粒度 |

2. 【强制】生产明细表禁用 `Kafka`/`RabbitMQ`/`Buffer` 等引擎直接落地：Kafka 引擎表只作为摄入管道（配合 MV 落地到 MergeTree），Buffer 引擎在异常重启时丢数据。
3. 【强制】`Distributed` 表仅作为分片入口：DDL 在本地表（`ON CLUSTER`），查询走 `Distributed`；禁止往 `Distributed` 表高频小批量写入（应写本地表或走负载均衡的批量通道）。
4. 【建议】副本用 `ReplicatedMergeTree` 家族 + `KeeperCoordinator`，禁止单副本上生产。
5. 【建议】不知道怎么起手时，用附录 7.5 的场景模板（明细日志 / CDC 去重 / 回撤 / 预聚合）作为骨架再改列。

### 2.3 ORDER BY / PRIMARY KEY（最重要的一条）

1. 【强制】`ORDER BY` 必须显式声明；按"查询过滤频率 × 过滤选择性"设计，不做默认 `tuple()`。
   设计原则（官方称之为"单一最重要的优化"，对的决定可使查询快 100 倍以上）：
   - **低基数列在前，高基数/时间列在后**：`(tenant_id, event_type, event_date)`，而不是 `(event_date, tenant_id)`，更不能以 UUID/随机 ID 打头。
   - 排序键就是"维度 → 时间"的漏斗：等值/IN 过滤的维度列放前面，范围过滤的时间列放最后。
   - 排序键列同时是稀疏主键（默认每 8192 行一个索引标记），列数一般 ≤ 4，过长会稀释前缀压缩收益并拖慢合并。
2. 【强制】`PRIMARY KEY` 是 `ORDER BY` 的前缀子集（可以只取前几列以减小内存中的稀疏索引），不允许出现 ORDER BY 之外的列。
3. 【强制】`ReplacingMergeTree` 的去重键 = `ORDER BY` 列。业务主键（如 order_id）必须在 ORDER BY 中，否则去重语义错误。
4. 【建议】高频点查（按 id 精确查）场景，可在 ORDER BY 首列放 id，把表当"宽 KV"用；或使用 `minmax` 跳数索引。
5. 【禁止】上线后随意改 ORDER BY——只能建新表迁移（`INSERT INTO new SELECT ...`），代价极大。设计阶段就要拿真实查询模式评审。

### 2.4 分区（PARTITION BY）

1. 【强制】分区是**数据管理手段**（TTL 删除、按分区搬数），不是首要的查询加速手段。官方经验："分区超过几十个，多半是过度分区"。
2. 【强制】分区键粒度：
   - 有按天 TTL 的日志表：`toYYYYMMDD(event_date)` 或 `toMonday(...)`，但单表日增量需 ≥ 数百万行；小表按月 `toYYYYMM`。
   - 无 TTL、数据量 < 10 亿行的表：**不分区**（`PARTITION BY tuple()`）往往是更优解——parts 之间不跨分区合并，过度分区导致 part 碎片、后台合并压力与查询打开大量 part 文件的开销（官方实测过度分区可慢 40 倍以上）。
   - 经验法则：TTL ≤ 7 天 → 按日分区；其余按月。
3. 【强制】单表活跃分区数监控阈值：> 1000 告警；查询应命中分区裁剪（EXPLAIN 中 `Parts: N/M`，N 远小于 M）。
4. 【建议】分区键与排序键不要重复：分区列通常不必再进 ORDER BY 首位（分区裁剪已处理），但时间范围查询若不在分区键上，必须进 ORDER BY 尾部。

### 2.5 数据类型

1. 【强制】能用定长数值不用 String：状态、枚举用 `Enum8/Enum16` 或 `LowCardinality(String)`。
2. 【强制】`LowCardinality(String)` 用于去重值 < 1 万的字符串列（官方建议 < 10k）；基数不确定的维度列先观察 `uniqExact` 再决定。
3. 【强制】金额、费率用 `Decimal(18, x)`，禁止 `Float64` 存钱。
4. 【强制】整型按值域收窄：`UInt8`（状态）、`UInt32`（id）、`Int64`（时间戳毫秒）等；禁止一律 `Int64/UInt64`。
5. 【强制】时间统一 `DateTime64(3)` 或 `DateTime`（带时区声明 `COMMENT 'Asia/Shanghai'` 或列定义中指定）；禁止用 String/UInt64 存时间。
6. 【建议】**避免 Nullable**：Nullable 会额外挂一个 UInt8 null 位图文件，拖慢查询与压缩。用默认值（`0`、`''`、`1970-01-01`）+ 业务哨兵值区分。仅外部对接无法约束时使用。
7. 【建议】大文本检索列：24.x+ 优先 `String + tokenbf_v1/ngrambf_v1` 跳数索引或倒排索引（`inverted`，v26.2 GA）；JSON 用 `JSON` 类型（控制 `max_dynamic_paths`），不要整包 String 存了再 `JSONExtract`。
8. 【建议】数组/Map 列配 `INDEX ... each_row` 系跳数索引（24.1+ 的 `mapKeys` 裁剪）。

### 2.6 编码与压缩

1. 【建议】按列特征配置 CODEC：数值时间序列 `DoubleDelta, ZSTD`；枚举/低基数 `LowCardinality` 自带字典；默认 `ZSTD(1)`，冷数据表 `CODEC(ZSTD(3))`。
2. 【建议】TTL 冷热分层：`TTL ts + INTERVAL 30 DAY CODEC(ZSTD(3))`，热数据保持默认压缩。

### 2.7 跳数索引（DATA SKIP INDEX）

1. 【强制】跳数索引只加在**不在排序键中但常被过滤**的列；排序键前缀列上再加索引是浪费。
2. 【强制】选型表：

| 索引类型 | 适用列 | 示例 |
|----------|--------|------|
| `minmax` | 数值/时间，按块单调或局部有序 | `INDEX idx_amt amount TYPE minmax GRANULARITY 2` |
| `set(N)` | 低基数等值/IN 过滤，N≥列基数时全存（`set(0)` 自动） | `INDEX idx_city city TYPE set(100)` |
| `bloom_filter()` | 高基数等值、数值、数组 contains | `INDEX idx_uid user_id TYPE bloom_filter(0.01)` |
| `tokenbf_v1` | 分词文本 `LIKE '%token%'` | 日志 message 列 |
| `ngrambf_v1` | 子串 `LIKE '%片段%'` | 无空格文本、URL |
| `inverted` | 全文（v26.2 GA） | 新版文本检索首选 |

3. 【强制】`GRANULARITY` 从 1（每 granule 一个索引块）起评测试，默认 1；跳数索引是"读时跳过"，写放大与合并成本需评估，单表索引数建议 ≤ 5。
4. 【建议】用 `EXPLAIN indexes=1` 验证索引实际过滤效果（`granules` 列），无效索引删掉。

### 2.8 TTL 与生命周期

1. 【强制】明细大表必须声明 TTL（或明确说明永久保留），TTL 删除粒度 = 分区粒度时效率最高（整分区 drop）。
2. 【建议】汇总层 TTL 长于明细层；冷数据降副本数、提高压缩级别。
3. 【强制】`ALTER ... DELETE/UPDATE`（mutation）不进 TTL 通道：mutation 是后台重写整个 part，禁止用于高频/日常数据修正。

### 2.9 去重语义（ReplacingMergeTree 实践）

1. 【强制】合并是异步的：查询时**不能假设已去重**。取最新值的可选方案按优先级：
   - 定期聚合报表：物化视图 + `argMax`（1 part 下 0.4s vs FINAL 0.48s；多 part 下 1.0s vs FINAL 1.5s，官方 1.5 亿行实测）；
   - `SELECT ... FROM t FINAL`：语义最简单，但查询时读更多数据、部分场景禁用下推，只用于低频后台任务；
   - `argMax(col, version)` 手写；
   - `OPTIMIZE TABLE t FINAL`：强制合并去重，重操作，只在批量导入后离线执行。
2. 【强制】`ReplacingMergeTree(version)` 必须提供单调递增版本列（`updated_at` 或 seq），否则"最后写入"无定义；软删场景配 `is_deleted` 列。
3. 【建议】配合 `min_age_to_force_merge_seconds = 600`（parts 超过 10 分钟后强制合并收敛），减少查询时 FINAL 的代价。

---

## 3. 数据写入规范

1. 【强制】**批量写入**：单次 INSERT 至少数千至数十万行（或 1~50MB），频率 ≥ 1 秒间隔；"小批量 + 高频"会制造海量小 part，打爆后台合并与内存。禁止应用循环单条 INSERT。
2. 【强制】无法改造客户端批量时，开启 `async_insert = 1, wait_for_async_insert = 1`，由服务端攒批；监控 `system.asynchronous_insert_log` 与 `system.parts`。
3. 【强制】禁止 `INSERT INTO ... VALUES` 逐行、禁止从 GUI 手工频繁插入生产表。
4. 【建议】导入文件优先 Parquet/ORC（官方实测 79s vs JSON 105s），ClickPipes/Kafka 摄入走官方连接器。
5. 【强制】删除/更新：
   - 日常少量删除用 `DELETE FROM t WHERE ...`（轻量删除 lightweight delete）；
   - 大批量重写用 mutation（`ALTER TABLE ... DELETE`），放在低峰，用 `mutations_sync=0` 异步 + `system.mutations` 监控；
   - 禁止把 mutation 当常规 API 高频调用。
6. 【强制】DDL 变更（加列、TTL、索引）用 `ON CLUSTER` + `settings alter_sync`，变更窗口错开写入高峰；改列类型/删列走"新表 + 迁移 + 切换"。
7. 【建议】写入的 `INSERT SELECT` 大任务显式设 `max_insert_block_size`、`max_memory_usage`，并在 `INSERT` 尾部带 `SETTINGS` 而非改全局。

---

## 4. 查询编写规范

### 4.1 基本要求

1. 【强制】**禁止 `SELECT *`**：列存按列计费，读的列越少越快。明确列出所需列（官方 10x 级差异常见）。
2. 【强制】大表查询必须带 WHERE，且过滤条件尽量命中排序键前缀或分区键；无过滤的全表聚合必须经评审（走预聚合表）。
3. 【强制】**不要对排序键/分区列套函数**：`WHERE toDate(ts) = '2026-09-01'` 无法用索引与裁剪（v24.x 部分场景可自动消除，但不依赖），改写为半开区间 `ts >= '2026-09-01' AND ts < '2026-09-02'`。同理 `toYYYYMM(partition_col)`、`substr(key,...)`、`col + 1`。
4. 【强制】分页禁止 `LIMIT 100000, 20` 大偏移：用 keyset 分页（`WHERE (id, ts) > (last_id, last_ts) ORDER BY id, ts LIMIT 20`）或 `ORDER BY ... LIMIT ... OFFSET` 小偏移。
5. 【建议】重过滤条件下推：ClickHouse 自动 `PREWHERE`（`optimize_move_to_prewhere` 默认开），但手工 `PREWHERE` 可强制把最强过滤列先行处理——过滤掉 90%+ 行的高选择性条件是 PREWHERE 候选。
6. 【建议】`LIMIT` 尽量带 `ORDER BY`（确定性），并用 `LIMIT n BY`、`SAMPLE`（采样表声明 `SAMPLE BY` 后）做探索查询。
7. 【建议】`count(DISTINCT x)` 基数 > 1 亿时评估 `uniq()`（近似，误差 <1%，内存恒定）、`uniqCombined()`；`quantile` 用 `quantileTDigest`。
8. 【强制】字符串前导通配 `LIKE '%xxx%'` 是全块扫描：走 `tokenbf_v1/ngrambf_v1` 索引列，或 `hasToken()`、倒排索引（`match()`）。

### 4.2 JOIN 规范

1. 【强制】小表放右表（hash join 默认右表建哈希表）；JOIN 前对两表都先过滤/聚合收敛行数与列数（v24.4+ 谓词下推已大幅自动优化，仍应显式收敛）。
2. 【强制】实时/交互查询 JOIN 数 ≤ 3~4（官方建议上限）；更多表先在 ETL 层预关联（宽表）或用字典。
3. 【强制】维度表（小、更新慢、等值关联）优先 **字典**：`dictGet('dim_dict', 'attr', key)` 比 JOIN 快约 3 倍（官方实测 JOIN 2.3s → dictGet 0.86s），且天然规避 JOIN 算法选择问题。注意：字典源有重复键时**静默取最后一条**，构建前必须去重。
4. 【建议】大右表场景显式选算法：`join_algorithm = 'grace_hash'`（分页溢出磁盘）或 `partial_merge`（左大右更大），避免默认 hash 撑爆内存。
5. 【建议】`GLOBAL JOIN`（`Distributed` 表下推到本地执行）防右表全量分发；`IN (SELECT ...)` 子查询同理用 `GLOBAL IN`。
6. 【建议】关联键类型必须一致（UInt64 vs String 隐式转换会破坏 hash 分发）。

### 4.3 去重查询

1. 【建议】`FINAL` 只用于小结果集/低频查询；高频报表在 MV 层 `argMax` 物化最新值。
2. 【建议】`LIMIT 1 BY key ORDER BY version DESC` 取每键最新行，比 FINAL 便宜（配合排序键 (key, version)）。
3. 【强制】CollapsingMergeTree 查询必须带 `Sign` 求和：`SUM(Sign * amount)`，漏写是正确性事故。

### 4.4 资源与设置

1. 【强制】生产查询必须设超时 `max_execution_time`；交互查询加 `max_bytes_before_external_group_by/sort` 或直接限制 `max_memory_usage`。
2. 【建议】高并发小结果集报表开启 query cache（`use_query_cache = 1`，23.x+）；重复仪表盘查询收益大。
3. 【建议】只读账号 + `max_rows_to_read`/`max_execution_time` 配额，把"事故查询"挡在门外。
4. 【强制】`SETTINGS` 写在查询级，禁止为单条查询改全局 profile。

---

## 5. 性能优化方案（诊断 → 手段）

### 5.1 慢 SQL 定位与优化六步 SOP

> 详版（含全部 SQL）见知识库 `slow-query-troubleshooting.md`；Agent 工具 `build_diagnostics` 可直接生成按步骤标注的诊断 SQL。

1. **发现**：`system.query_log`（`type='QueryFinish'`，`query_duration_ms > 5000`）找慢查询；看 `read_rows/read_bytes`——扫描亿级行才慢=索引问题，扫描小仍慢=锁/资源问题。
2. **取证**：`ProfileEvents` 分类瓶颈：`FileOpen`/`OSReadChars` 高=I/O 型；`OCPUWait` 高=CPU 型；`ContextLock` 高=排队型；`external_aggregation=1`=溢出磁盘型。
3. **归因**：`EXPLAIN indexes=1` 三指标决策树：
   - `Parts N/M` 高（>0.5）→ WHERE 缺分区列条件；
   - `Granules N/M` 高（>0.3）或 Key Condition 缺失/unknown → 过滤未命中排序键前缀或键列被函数包裹；
   - 裁剪都好但 read_bytes 大 → 列裁剪（SELECT *）；
   - 裁剪好、列少、仍慢 → 聚合/JOIN/去重本身贵（uniq/字典/argMax）；
   - 表级：`system.parts` part>10 碎片、`system.mutations` 堆积。
4. **改写**：按 5.2 优先级从上到下套手段，每条附预期收益依据。
5. **验证**：`EXPLAIN ANALYZE` 对比改写前后 `elapsed`/`read_rows`/`read_bytes`（相同 max_threads）；上线后观察 P95。
6. **固化**：查询级熔断（`max_execution_time`/`max_rows_to_read`）、只读账号配额、高频模式沉淀为索引/投影/MV（EXPLAIN 验证后保留）、duration>5s 告警与 part 碎片巡检。

### 5.2 优化手段清单（按投入产出排序）

| 优先级 | 手段 | 适用症状 |
|--------|------|----------|
| 1 | 补 WHERE / 命中排序键前缀 | 全表扫描、Granules=N/M 接近 1 |
| 2 | 列裁剪（去 SELECT *） | read_bytes 远大于结果 |
| 3 | 改写键列函数为区间 | Key Condition 为空/unknown |
| 4 | 跳数索引（minmax/set/bloom/tokenbf） | 非键列高选择性过滤 |
| 5 | 分区裁剪（WHERE 带分区列） | Parts 全读 |
| 6 | 投影 Projection（排序副本/预聚合） | 同表多查询模式冲突 |
| 7 | 物化视图预聚合 | 固定报表、重复聚合 |
| 8 | 字典替代维度 JOIN | JOIN 慢、维度小表 |
| 9 | argMax MV 替代 FINAL | ReplacingMergeTree 查询慢 |
| 10 | query cache | 高并发重复报表 |
| 11 | grace_hash/partial_merge JOIN | 大 JOIN OOM |
| 12 | 降采样/采样（SAMPLE） | 探索分析 |

### 5.3 投影（Projection）vs 物化视图（MV）

1. 【建议】**投影**：同一张表内建"另类排序副本"或预聚合，查询自动匹配（`force_optimize_projection = 1` 可强制校验），适合一表多查询模式；代价：写放大、part 内维护。
2. 【建议】**物化视图**：跨表落地预聚合结果，触发于 INSERT（UPDATE/DELETE 不传播，JOIN 只随左表触发——这是正确性边界）。
3. 【强制】二选一原则：查询模式不稳定、要物化到独立表供多消费者 → MV；仅换排序/轻量聚合、希望对查询透明 → 投影。禁止两者叠加在相同查询模式上。

### 5.4 资源层

1. 【建议】`max_threads` 匹配 CPU 而非无脑调大（小查询 4~8 足够）；`max_block_size`/`min_insert_block_size` 保持默认除非有实测。
2. 【建议】标记查询（`query_id`、`log_comment`）贯穿排查链路。

---

## 6. 常见陷阱（案例库）

| # | 陷阱 | 症状 | 处置 |
|---|------|------|------|
| 1 | 高频小 INSERT | parts 爆炸、`Too many parts` 报错 | 攒批 / async_insert |
| 2 | ORDER BY 首列是时间/UUID | 查询扫全表（稀疏索引失效） | 重排 ORDER BY（新表迁移） |
| 3 | 按天分区 + 单日数据量小 | part 碎片、合并堆积、查询慢 40x | 取消分区或改月分区 |
| 4 | `WHERE toDate(ts)=...` | Key Condition unknown | 半开区间改写 |
| 5 | 查询漏了 Sign | CollapsingMergeTree 数据不对 | `SUM(Sign*x)` |
| 6 | 字典源有重复键 | 维度值"随机"错乱 | 字典构建前去重 |
| 7 | mutation 当删除 API | 后台重写堆积、磁盘打满 | 轻量删除 / TTL |
| 8 | FINAL 大查询 | 内存暴涨、超时 | argMax MV / LIMIT 1 BY |
| 9 | Distributed 直写高频小批 | 分片间数据倾斜、parts 多 | 写本地表或批量通道 |
| 10 | Nullable 满天飞 | 压缩率低、查询变慢 | 默认值替代 |
| 11 | LIKE '%x%' 无索引 | 全扫 | tokenbf/ngrambf/inverted |
| 12 | JOIN 键类型不一致 | 退化为全量传输 | CAST 对齐类型 |

---

## 7. 附录

### 7.1 常用诊断 SQL

```sql
-- TOP 慢查询
SELECT event_time, query_duration_ms, read_rows, read_bytes,
       formatReadableSize(read_bytes) AS rb, query
FROM system.query_log
WHERE type = 'QueryFinish' AND event_date >= yesterday()
ORDER BY query_duration_ms DESC LIMIT 20;

-- 分区 part 碎片检查
SELECT database, table, count() AS parts, sum(rows) AS rows
FROM system.parts WHERE active
GROUP BY database, table
HAVING parts > 100 ORDER BY parts DESC;

-- mutation 堆积
SELECT database, table, mutation_id, is_done, latest_fail_reason
FROM system.mutations WHERE is_done = 0;
```

### 7.2 常用 EXPLAIN

```sql
EXPLAIN SELECT ...;                       -- 默认 PLAN
EXPLAIN PLAN indexes = 1 SELECT ...;      -- 显示 granule/part 裁剪
EXPLAIN PIPELINE SELECT ...;              -- 执行管道/并行度
EXPLAIN ANALYZE SELECT ...;               -- 真实执行统计
```

### 7.3 关联设置速查

| 设置 | 用途 |
|------|------|
| `async_insert`, `wait_for_async_insert` | 服务端攒批 |
| `optimize_move_to_prewhere` | 过滤下推（默认开） |
| `force_optimize_projection` | 强制投影命中校验 |
| `join_algorithm` | hash/parallel_hash/grace_hash/partial_merge/full_sorting |
| `max_execution_time`, `max_rows_to_read` | 查询熔断 |
| `use_query_cache` | 查询缓存 |
| `min_age_to_force_merge_seconds` | 强制合并收敛 part |
| `mutations_sync` | mutation 同步/异步 |

### 7.4 版本特性备注

- v23.x：query cache、轻量删除 GA 化推进。
- v24.3/24.4：新分析器（analyzer）默认，JOIN 谓词下推（最高 10x）。
- v24.12：两表 JOIN 顺序自动重排；24.1+ each_row 数组/map 跳数索引。
- v25.x：3+ 表 JOIN 重排优化。
- v26.2：倒排索引（inverted）GA，`JSON` 类型持续增强。

### 7.5 建表场景模板（与 Agent 工具 `ddl_codegen` 对应）

四个场景的完整模板由 Agent 的 `ddl_codegen` 工具生成（结构合规，替换占位列即可用）：

| 场景 | 引擎/结构 | 关键点 |
|------|-----------|--------|
| `append_log` 追加写明细 | MergeTree + 月分区 + TTL + bloom_filter 跳数索引 | 排序键 (维度…, 时间)；分区粒度对齐 TTL |
| `cdc_upsert` CDC 入湖 | ReplacingMergeTree(updated_at) + is_deleted + min_age_to_force_merge | 去重键=ORDER BY；版本列单调；高频取最新用 argMax MV |
| `collapsing` 增减回撤 | CollapsingMergeTree(sign) | 查询必须 SUM(Sign*x)；乱序用 Versioned |
| `agg_rollup` 预聚合 | AggregatingMergeTree + MV（TO 目标表）+ 查询示例 | AggregateFunction 状态列；读取端 *Merge；POPULATE 丢增量 |

用法示例：

```bash
python agents/clickhouse-sql-optimizer/src/clickhouse_agent/cli.py \
  "帮我建一张 CDC 入湖表，表名 ods.orders_cdc，业务主键 order_id" --offline
```
