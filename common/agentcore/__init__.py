"""Agent 执行核心：BaseAgent 执行循环、ToolRegistry 工具协议。"""
from .base import AgentResult, BaseAgent
from .tools import Tool, ToolCallRecord, ToolRegistry, dumps_for_llm

__all__ = ["AgentResult", "BaseAgent", "Tool", "ToolCallRecord", "ToolRegistry", "dumps_for_llm"]
