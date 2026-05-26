from __future__ import annotations

import os

from langchain_core.language_models import BaseChatModel


def get_model(provider: str | None = None, model: str | None = None) -> BaseChatModel:
	provider = provider or os.environ.get("PLAND_PROVIDER", "anthropic")
	if provider == "anthropic":
		from langchain_anthropic import ChatAnthropic
		model = model or os.environ.get("PLAND_MODEL", "claude-sonnet-4-20250514")
		return ChatAnthropic(model=model)  # type: ignore[call-arg]
	elif provider == "ollama":
		from langchain_ollama import ChatOllama
		model = model or os.environ.get("PLAND_MODEL", "llama3.1:8b")
		base_url = os.environ.get("PLAND_OLLAMA_URL", "http://localhost:11434")
		return ChatOllama(model=model, base_url=base_url)  # type: ignore[call-arg]
	else:
		raise ValueError(f"unknown provider: {provider}")
