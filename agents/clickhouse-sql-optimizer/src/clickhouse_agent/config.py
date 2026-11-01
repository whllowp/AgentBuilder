"""Agent 配置加载（config.yaml）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class LLMSettings:
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o"
    api_key: str = ""
    api_key_env: str = "OPENAI_API_KEY"
    temperature: float = 0.2
    timeout: float = 120.0
    max_retries: int = 2


@dataclass
class AgentConfig:
    agent_dir: Path
    name: str = "clickhouse-sql-optimizer"
    version: str = "0.1.0"
    clickhouse_version: str = "24.x"
    spec_file: str = "clickhouse开发规范.md"
    max_iterations: int = 8
    llm: LLMSettings = field(default_factory=LLMSettings)
    tools: dict = field(default_factory=dict)

    @property
    def knowledge_dir(self) -> Path:
        return self.agent_dir / "knowledge"

    @property
    def prompts_dir(self) -> Path:
        return self.agent_dir / "prompts"

    @classmethod
    def load(cls, agent_dir: str | Path) -> "AgentConfig":
        agent_dir = Path(agent_dir).resolve()
        raw = {}
        config_path = agent_dir / "config.yaml"
        if config_path.exists():
            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

        agent = raw.get("agent", {})
        llm = raw.get("llm", {})
        runtime = raw.get("runtime", {})
        llm_settings = LLMSettings(
            base_url=llm.get("base_url", LLMSettings.base_url),
            model=llm.get("model", LLMSettings.model),
            api_key=llm.get("api_key", ""),
            api_key_env=llm.get("api_key_env", LLMSettings.api_key_env),
            temperature=float(llm.get("temperature", 0.2)),
            timeout=float(llm.get("request_timeout", 120.0)),
            max_retries=int(llm.get("max_retries", 2)),
        )
        return cls(
            agent_dir=agent_dir,
            name=agent.get("name", cls.name),
            version=str(agent.get("version", cls.version)),
            clickhouse_version=str(runtime.get("clickhouse_version", cls.clickhouse_version)),
            spec_file=runtime.get("spec_file", cls.spec_file),
            max_iterations=int(llm.get("max_iterations", 8)),
            llm=llm_settings,
            tools=raw.get("tools", {}) or {},
        )
