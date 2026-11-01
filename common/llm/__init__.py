"""OpenAI 兼容 LLM 客户端与测试 Mock。"""
from .client import LLMClient, LLMError, LLMResponse, ToolCall
from .mock import MockLLM

__all__ = ["LLMClient", "LLMError", "LLMResponse", "ToolCall", "MockLLM"]
