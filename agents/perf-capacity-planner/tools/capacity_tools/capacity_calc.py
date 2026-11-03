"""性能容量计算器：ClickHouse 存储 / Kafka 分区吞吐 / Flink 并行度与状态 / 通用 QPS→线程连接池。

输出三件套（防"黑盒数字"）：
- formula：所用公式（可复核）；
- assumptions：全部假设与默认系数（用户未给即按默认，必须列出）；
- thresholds：水位与扩容阈值（50% 预警 / 70% 扩容），以及敏感性提示（哪个参数对结果最敏感）。
"""
from __future__ import annotations

# 经验系数（均可在入参覆盖；来源见 knowledge/capacity-models.md）
DEFAULTS = {
    "ck": {"compression": 5.0, "headroom": 1.3, "disk_redundancy": 2.0, "key_width_bytes": 32},
    "kafka": {"per_partition_mbps": 10.0, "headroom": 2.0, "replication": 3},
    "flink": {"records_per_slot": 5000.0, "rocksdb_factor": 3.0, "heap_per_tm_gb": 4.0},
    "generic": {"latency_s": 0.05, "pool_factor": 1.2, "headroom": 2.0},
}


def _gb(x: float) -> float:
    return round(x / 1024 ** 3, 2)


def plan_clickhouse(rows_per_day: float, avg_row_bytes: float, ttl_days: int = 90,
                    compression: float | None = None, replicas: int = 1, partitions_per_month: int = 1) -> dict:
    d = DEFAULTS["ck"]
    comp = compression or d["compression"]
    assumptions = [
        f"压缩比 {comp}:1（默认 {d['compression']}，列存 ZSTD 经验值；实测用 system.parts 的压缩比修正）",
        f"增长余量 ×{d['headroom']}（应对业务增长与临时空间）",
        f"磁盘冗余 ×{d['disk_redundancy']}（合并期旧+新 part 并存）",
        f"副本数 {replicas}",
    ]
    raw_per_day = rows_per_day * avg_row_bytes
    total_rows = rows_per_day * ttl_days
    storage = raw_per_day * ttl_days / comp * replicas * d["headroom"] * d["disk_redundancy"]
    # 主键稀疏索引内存：每 8192 行一个 mark，两份（primary + 一级缓存近似）
    marks = total_rows / 8192
    pk_mem = marks * d["key_width_bytes"] * 2
    return {
        "engine": "clickhouse",
        "formula": (
            "存储(字节) = 日行数 × 行宽 × TTL天 / 压缩比 × 副本 × 增长余量 × 磁盘冗余；"
            "主键内存 ≈ (总行数/8192) × 键宽 × 2"
        ),
        "assumptions": assumptions,
        "results": {
            "raw_per_day_gb": _gb(raw_per_day),
            "compressed_per_day_gb": _gb(raw_per_day / comp),
            "total_storage_gb": _gb(storage),
            "total_storage_tb": round(_gb(storage) / 1024, 3),
            "total_rows": total_rows,
            "pk_index_mem_mb": round(pk_mem / 1024 ** 2, 1),
            "partitions_total": max(1, ttl_days // 30) * partitions_per_month * replicas,
        },
        "recommendations": [
            f"数据盘规划 ≥ {_gb(storage)} GB（含冗余；SSD 优先，冷数据可分层）",
            f"活跃分区数 ≈ {max(1, ttl_days // 30) * partitions_per_month}，>1000 触发过度分区告警",
            "每副本内存 ≥ 主键内存 ×3（索引 + 解压块 + 查询缓冲）",
            f"水位：磁盘 50% 预警、70% 扩容或下调 TTL；分区数翻倍即复查（知识库 capacity-models）",
        ],
        "sensitivity": "结果对 avg_row_bytes 与 ttl_days 线性敏感：行宽或保留期翻倍 → 存储翻倍；压缩比对结果成反比敏感。",
    }


def plan_kafka(msgs_per_sec: float, avg_msg_bytes: float = 1024.0, retention_hours: int = 72,
               per_partition_mbps: float | None = None, replication: int | None = None) -> dict:
    d = DEFAULTS["kafka"]
    pp = per_partition_mbps or d["per_partition_mbps"]
    rep = replication if replication is not None else d["replication"]
    throughput_bps = msgs_per_sec * avg_msg_bytes
    throughput_mb = throughput_bps / 1024 ** 2
    partitions = max(3, int(throughput_mb * d["headroom"] / pp) + 1)
    storage = throughput_bps * retention_hours * 3600 * rep * 1.1
    return {
        "engine": "kafka",
        "formula": (
            "分区数 = ceil(吞吐MBps × 余量 / 单分区吞吐上限)；"
            "存储 = 吞吐Bps × 保留秒 × 副本 × 1.1"
        ),
        "assumptions": [
            f"单分区吞吐上限 {pp} MB/s（默认 {d['per_partition_mbps']}，顺序写经验值）",
            f"吞吐余量 ×{d['headroom']}（峰值/再平衡期）",
            f"副本 {rep}",
        ],
        "results": {
            "throughput_mb_per_sec": round(throughput_mb, 2),
            "partitions_recommended": partitions,
            "storage_gb": _gb(storage),
            "msgs_per_day": round(msgs_per_sec * 86400),
        },
        "recommendations": [
            f"分区数 {partitions}（≥3 保证再平衡能力；消费端并行度上限=分区数）",
            f"集群盘 ≥ {_gb(storage)} GB；水位 50% 预警 / 70% 扩盘或缩保留期",
            "单条消息 >100KB 考虑外置引用（对象存储），避免大消息拖垮分区",
        ],
        "sensitivity": "分区数对 msgs_per_sec 线性敏感；存储对保留期与副本数线性敏感。",
    }


def plan_flink(records_per_sec: float, state_size_gb: float = 0.0, key_cardinality: float = 0.0,
               records_per_slot: float | None = None) -> dict:
    d = DEFAULTS["flink"]
    rps = records_per_slot or d["records_per_slot"]
    by_throughput = int(records_per_sec / rps) + 1
    by_key = int(key_cardinality ** 0.5) + 1 if key_cardinality > 0 else 1  # 经验：并行度 ≈ sqrt(键基数) 起步
    parallelism = max(by_throughput, by_key)
    slots = parallelism
    tm_count = max(1, (slots + 7) // 8)  # 每 TM 8 slot
    rocksdb_mem = state_size_gb * d["rocksdb_factor"]
    return {
        "engine": "flink",
        "formula": (
            "并行度 = max(吞吐/单slot吞吐, sqrt(键基数))；slots=并行度；"
            "TM 数 = ceil(slots/8)；RocksDB 内存 ≈ 状态大小 × 3"
        ),
        "assumptions": [
            f"单 slot 吞吐 {rps} rec/s（默认 {d['records_per_slot']}；算子复杂需实测下调）",
            f"每 TM {8} slot、堆 {d['heap_per_tm_gb']} GB",
            f"RocksDB 放大系数 ×{d['rocksdb_factor']}（含块缓存与 memtable）",
        ],
        "results": {
            "parallelism": parallelism,
            "slots": slots,
            "tm_count": tm_count,
            "total_cores": slots,
            "rocksdb_mem_gb": round(rocksdb_mem, 1),
            "total_mem_gb": round(tm_count * d["heap_per_tm_gb"] + rocksdb_mem, 1),
        },
        "recommendations": [
            f"并行度 {parallelism}（吞吐路 {by_throughput} / 键基数路 {by_key}，取大）",
            "Kafka 源并行度 ≤ Topic 分区数； keyed 状态 >10GB 用 RocksDB + 增量 checkpoint",
            "CPU 水位 >70% 或反压持续 → 加并行度（先确认源分区余量）",
        ],
        "sensitivity": "并行度对 records_per_sec 线性、对键基数开方敏感；内存对状态大小 ×3 敏感。",
    }


def plan_generic(qps: float, latency_s: float | None = None) -> dict:
    d = DEFAULTS["generic"]
    lat = latency_s or d["latency_s"]
    threads = int(qps * lat * d["pool_factor"]) + 1
    return {
        "engine": "generic",
        "formula": "线程数 ≈ QPS × 平均时延(s) × 余量；连接池 ≈ 线程数（下游连接 ≥ 该值）",
        "assumptions": [f"平均时延 {lat}s（默认 {d['latency_s']}）", f"余量 ×{d['pool_factor']}", f"容量目标 ×{d['headroom']}（峰值）"],
        "results": {
            "threads": threads,
            "connection_pool": threads,
            "capacity_at_peak_qps": round(qps * d["headroom"]),
        },
        "recommendations": [
            f"线程池/连接池 ≥ {threads}（含峰值 ×{d['headroom']} 目标则 ≥ {int(threads * d['headroom'])}）",
            "下游数据库连接数需同步评估；超时与熔断必须配置（避免线程耗尽雪崩）",
            "水位：CPU 50% 预警 / 70% 扩容；P99 时延翻倍即复测",
        ],
        "sensitivity": "线程数对 QPS 与时延线性敏感；时延恶化 2 倍 → 需要线程翻倍。",
    }


def plan(spec: dict) -> dict:
    """按 spec['engine'] 分发（kwargs 按目标函数签名过滤，跨引擎字段不透传）；未知引擎报错。"""
    import inspect

    engine = str(spec.get("engine", "")).lower()
    fn = {"clickhouse": plan_clickhouse, "ck": plan_clickhouse, "kafka": plan_kafka,
          "flink": plan_flink, "generic": plan_generic, "api": plan_generic, "服务": plan_generic}.get(engine)
    if fn is None:
        return {"ok": False, "error": f"未知引擎: {engine}，可选 clickhouse/kafka/flink/generic"}
    params = inspect.signature(fn).parameters
    kwargs = {k: v for k, v in spec.items() if k != "engine" and k in params}
    return fn(**kwargs)


__all__ = ["plan", "plan_clickhouse", "plan_kafka", "plan_flink", "plan_generic", "DEFAULTS"]
