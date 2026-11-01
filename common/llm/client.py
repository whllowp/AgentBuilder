"""OpenAI 兼容 Chat Completions 客户端（零第三方强依赖，requests 可用时使用，否则退回 urllib）。"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

try:
    import requests  # type: ignore

    _HAS_REQUESTS = True
except ImportError:  # pragma: no cover - 环境兜底
    _HAS_REQUESTS = False


class LLMError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class LLMClient:
    """支持任何 OpenAI 兼容端点（OpenAI / DeepSeek / 智谱 GLM / vLLM 等）。

    api_key 解析顺序：显式传参 > api_key_env 指定的环境变量 > OPENAI_API_KEY。
    """

    def __init__(
        self,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o",
        api_key: str | None = None,
        api_key_env: str = "OPENAI_API_KEY",
        temperature: float = 0.2,
        timeout: float = 120.0,
        max_retries: int = 2,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or os.environ.get(api_key_env, "")
        self.temperature = temperature
        self.timeout = timeout
        self.max_retries = max_retries

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> LLMResponse:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        body = self._post(payload)
        choices = body.get("choices") or []
        if not choices:
            raise LLMError(f"响应中没有 choices: {body}")
        message = choices[0].get("message", {})

        tool_calls = []
        for tc in message.get("tool_calls") or []:
            function = tc.get("function", {})
            raw_args = function.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc.get("id", ""), name=function.get("name", ""), arguments=args))

        return LLMResponse(content=message.get("content"), tool_calls=tool_calls)

    def _post(self, payload: dict) -> dict:
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                if _HAS_REQUESTS:
                    resp = requests.post(url, headers=headers, data=data, timeout=self.timeout)
                    status, text = resp.status_code, resp.text
                else:  # pragma: no cover
                    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
                    with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                        status, text = resp.status, resp.read().decode("utf-8", "replace")
            except (requests.RequestException, urllib.error.URLError, OSError) as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise LLMError(f"请求失败: {exc}") from exc

            if status == 200:
                try:
                    return json.loads(text)
                except json.JSONDecodeError as exc:
                    raise LLMError(f"响应不是合法 JSON: {text[:300]}") from exc
            # 429 / 5xx 重试，其余 4xx 直接报错
            if status in (429, 500, 502, 503, 504) and attempt < self.max_retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise LLMError(f"HTTP {status}: {text[:500]}")

        raise LLMError(f"重试耗尽: {last_error}")
