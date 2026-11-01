# [占位符] 本文件在 2026-11 E: 盘文件系统损坏中丢失，内容无法从会话恢复。
# 请从 git 历史 / 备份恢复原实现；恢复前调用将抛出 NotImplementedError。
"""FLIP-27 自定义 Source 骨架 + CDC/Kafka/File/DataGen 用法生成。原实现已丢失。"""
from __future__ import annotations


def generate_custom_source(source_name: str = "Custom", record_type: str = "String", package: str = "com.example.flink", bounded: bool = False) -> dict:
    raise NotImplementedError("source_codegen.py 原实现因磁盘损坏丢失，请从 git/备份恢复")


def generate_builtin_usage(kind: str, **kwargs) -> dict:
    raise NotImplementedError("source_codegen.py 原实现因磁盘损坏丢失，请从 git/备份恢复")
