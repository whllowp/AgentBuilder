---
title: 常见性能陷阱与案例（12 例）
keywords: 陷阱 案例 Too many parts 小批量插入 async_insert ORDER BY 时间戳 过度分区 mutation FINAL Sign 字典重复键 Nullable LIKE Distributed 类型不一致
source: 《clickhouse开发规范.md》第 6 节案例库
---

# 常见性能陷阱与案例

## 案例 1：高频小 INSERT → Too many parts

症状：`Too many parts ...` 报错、后台合并堆积。
处置：应用攒批（≥ 数千行/批，间隔 ≥ 1s）；无法改造则 `async_insert=1, wait_for_async_insert=1`；监控 `system.asynchronous_insert_log` 与 `system.parts`。

## 案例 2：ORDER BY 首列是时间戳/UUID → 稀疏索引失效

症状：所有查询 Granules N/M ≈ 1（全表扫）。
处置：重排为低基数在前 `(tenant_id, event_type, event_date)`；只能新表迁移 + `INSERT SELECT`。

## 案例 3：按天分区 + 单日数据量小 → part 碎片

症状：分区 part 数多、合并慢、查询打开文件多（官方实测慢 46x）。
处置：取消分区（数据 < 10 亿）或改月分区，分区粒度对齐 TTL。

## 案例 4：WHERE 对键列套函数 → 裁剪失效

症状：`Key Condition: (unknown)`、Parts 全读。
处置：`toDate(ts)=d` 改 `ts>=d AND ts<d+1` 半开区间。

## 案例 5：CollapsingMergeTree 查询漏 Sign → 数据不对

症状：行数对不上、金额忽大忽小。
处置：必须 `SUM(Sign * amount)`；乱序用 VersionedCollapsingMergeTree。

## 案例 6：字典源重复键 → 维度值错乱

症状：dictGet 结果"随机"取旧值。
处置：字典构建 SELECT 先去重（字典静默保留最后一条）。

## 案例 7：mutation 当删除 API → 磁盘打满

症状：`system.mutations` 堆积、磁盘翻倍（重写整个 part）。
处置：日常少量删除用 `DELETE FROM`（轻量删除）；批量重写放低峰 + mutations_sync=0。

## 案例 8：FINAL 大查询 → 内存暴涨超时

处置：MV + argMax 预物化最新值；或 `LIMIT 1 BY key ORDER BY version DESC`；`min_age_to_force_merge_seconds=600` 收敛 part。

## 案例 9：直写 Distributed 高频小批 → 分片倾斜 parts 爆炸

处置：批量写本地表（随机分片）或负载均衡批量通道；查询走 Distributed。

## 案例 10：Nullable 滥用 → 压缩差查询慢

症状：额外 UInt8 null 位图文件、扫描变慢。
处置：默认值（0、''、epoch）+ 哨兵值；只在无法约束的外部数据用 Nullable。

## 案例 11：LIKE '%x%' 无索引 → 全块扫描

处置：tokenbf_v1/ngrambf_v1 跳数索引、`hasToken()`、v26.2+ inverted 倒排索引。

## 案例 12：JOIN 键类型不一致 → 退化传输

症状：join 时网络/内存异常放大。
处置：CAST 对齐两表关联键类型；Distributed 下用 GLOBAL JOIN。
