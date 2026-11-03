---
name: perf-capacity-planner
description: 性能容量规划技能。凡是用户问"要多大盘/多少分区/多少并行度/多少线程和连接池"——ClickHouse 存量与主键内存、Kafka 分区数与存储、Flink 并行度 slots 与 RocksDB 内存、接口 QPS→线程池——以及水位阈值（50%预警/70%扩容）、容量评审、扩容方案——都应使用本技能：公式+假设+敏感性三件套输出，拒绝黑盒数字。
---

# 性能容量规划

把业务量级换算成资源结论，附公式、假设与水位阈值。可执行实现在 `agents/perf-capacity-planner/`。

## 工作流

1. 计算优先走工具（不心算）：
   ```bash
   python agents/perf-capacity-planner/src/capacity_agent/cli.py "ClickHouse 日增 2 亿行，行宽 200B，保留 90 天，双副本" --offline
   ```
   支持 clickhouse / kafka / flink / generic（QPS→线程连接池）四类。
2. 每个结论必须包含：**公式**（可复核）、**假设**（默认系数列明并给实测修正法）、**水位**（50% 预警 / 70% 扩容 + 结构性水位：分区>1000/持续反压/lag 趋势）、**验证方法**（影子流量压测，首周偏差>30% 修正系数）、**敏感性**（哪个参数翻倍结果翻倍）。
3. 系数被追问时查 `agents/perf-capacity-planner/knowledge/capacity-models.md`（经验系数表：压缩比 5:1、单分区 10MB/s、单 slot 5000 rec/s、RocksDB ×3、Little's Law）。

## 核心系数速查

| 引擎 | 关键公式 | 默认系数 |
|------|----------|----------|
| ClickHouse | 存储=日行×行宽×TTL/压缩×副本×余量×磁盘冗余；主键内存≈行数/8192×键宽×2 | 压缩 5:1、余量 1.3、磁盘冗余 2 |
| Kafka | 分区=吞吐MBps×余量/单分区上限；存储=吞吐×保留×副本×1.1 | 单分区 10MB/s、余量 2 |
| Flink | 并行度=max(吞吐/单slot, √键基数)；RocksDB 内存=状态×3 | 单 slot 5000 rec/s |
| 通用 | 线程≈QPS×时延×1.2（Little's Law） | 时延 50ms |

## 约束

- 参数缺失按默认并列入假设，不编造业务量级；机型选型标注"资源量推导"需结合运维标准。
