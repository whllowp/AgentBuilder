"""测试用脚本化 Mock LLM：按顺序吐出预设响应。"""
from __future__ import annotations

from .client import LLMResponse


class MockLLM:
    def __init__(self, script: list[LLMResponse]):
        self.script = list(script)
        self.calls: list[dict] = []

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        if not self.script:
            return LLMResponse(content="(脚本耗尽)")
        return self.script.pop(0)
