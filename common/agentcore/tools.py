"""Agent 工具协议与注册表（OpenAI function-calling 风格）。"""
from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolCallRecord:
    """一次工具调用的留痕，用于调试与评测。"""
    name: str
    arguments: dict
    ok: bool
    output: Any = None
    error: str | None = None


class Tool:
    def __init__(self, name: str, description: str, parameters: dict, func: Callable[..., Any]):
        if not name.replace("_", "").isalnum():
            raise ValueError(f"工具名不合法: {name}")
        self.name = name
        self.description = description
        self.parameters = parameters
        self.func = func

    def to_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def invoke(self, arguments: dict | None) -> Any:
        arguments = arguments or {}
        required = self.parameters.get("required", [])
        missing = [k for k in required if k not in arguments]
        if missing:
            raise ValueError(f"缺少必填参数: {missing}")
        # 只透传声明的属性，避免模型注入多余参数
        props = self.parameters.get("properties", {})
        accepted = {k: v for k, v in arguments.items() if k in props}
        sig = inspect.signature(self.func)
        if not any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
            accepted = {k: v for k, v in accepted.items() if k in sig.parameters}
        return self.func(**accepted)


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}

    def register(self, name: str, description: str, parameters: dict, func: Callable[..., Any]) -> Tool:
        if name in self._tools:
            raise KeyError(f"工具已注册: {name}")
        tool = Tool(name, description, parameters, func)
        self._tools[name] = tool
        return tool

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict]:
        return [t.to_schema() for t in self._tools.values()]

    def call(self, name: str, arguments: dict | None) -> Any:
        """执行工具；异常不抛出，返回 {'ok': False, 'error': ...} 让对话继续。"""
        try:
            tool = self._tools[name]
        except KeyError:
            return {"ok": False, "error": f"未知工具: {name}"}
        try:
            return {"ok": True, "output": tool.invoke(arguments)}
        except Exception as exc:  # noqa: BLE001 —— 工具错误要回传给模型而不是中断
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def dumps_for_llm(value: Any, limit: int = 8000) -> str:
    """把工具输出序列化为塞进对话的消息文本，超长截断。"""
    try:
        text = json.dumps(value, ensure_ascii=False, indent=1, default=str)
    except (TypeError, ValueError):
        text = str(value)
    if len(text) > limit:
        text = text[:limit] + f"\n...(已截断，原始长度 {len(text)} 字符)"
    return text
