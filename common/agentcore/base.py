"""Agent 执行循环：系统提示词 + 用户输入 + 工具调用回路。"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..llm.client import LLMClient
from .tools import ToolRegistry, ToolCallRecord, dumps_for_llm


@dataclass
class AgentResult:
    answer: str
    tool_trace: list[ToolCallRecord] = field(default_factory=list)
    iterations: int = 0


class BaseAgent:
    def __init__(
        self,
        llm: LLMClient,
        system_prompt: str,
        tools: ToolRegistry | None = None,
        max_iterations: int = 8,
    ):
        self.llm = llm
        self.system_prompt = system_prompt
        self.tools = tools or ToolRegistry()
        self.max_iterations = max_iterations

    def run(self, prompt: str) -> AgentResult:
        messages: list[dict] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": prompt},
        ]
        schemas = self.tools.schemas() if self.tools.names() else None
        trace: list[ToolCallRecord] = []
        last_answer = ""

        for iteration in range(1, self.max_iterations + 1):
            response = self.llm.chat(messages, tools=schemas)

            if not response.has_tool_calls:
                last_answer = response.content or ""
                return AgentResult(answer=last_answer, tool_trace=trace, iterations=iteration)

            messages.append(
                {
                    "role": "assistant",
                    "content": response.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": tc.name, "arguments": _json_args(tc.arguments)},
                        }
                        for tc in response.tool_calls
                    ],
                }
            )
            for call in response.tool_calls:
                result = self.tools.call(call.name, call.arguments)
                record = ToolCallRecord(
                    name=call.name,
                    arguments=call.arguments,
                    ok=bool(result.get("ok")) if isinstance(result, dict) else True,
                    output=result.get("output") if isinstance(result, dict) else result,
                    error=result.get("error") if isinstance(result, dict) else None,
                )
                trace.append(record)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": dumps_for_llm(result),
                    }
                )

        return AgentResult(
            answer=last_answer or "(达到最大工具调用轮数，未能给出最终回答)",
            tool_trace=trace,
            iterations=self.max_iterations,
        )


def _json_args(arguments: dict) -> str:
    import json

    return json.dumps(arguments, ensure_ascii=False, default=str)
