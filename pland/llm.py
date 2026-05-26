"""Direct LLM API clients for Ollama and Anthropic. No LangChain."""
from __future__ import annotations

import os
import sys

import httpx


def get_config(provider: str | None = None, model: str | None = None) -> dict:
	provider = provider or os.environ.get("PLAND_PROVIDER", "ollama")
	if provider == "ollama":
		model = model or os.environ.get("PLAND_MODEL", "llama3.1:8b")
		base_url = os.environ.get("PLAND_OLLAMA_URL", "http://localhost:11434")
		return {"provider": "ollama", "model": model, "base_url": base_url}
	elif provider == "anthropic":
		model = model or os.environ.get("PLAND_MODEL", "claude-sonnet-4-20250514")
		api_key = os.environ.get("ANTHROPIC_API_KEY", "")
		if not api_key:
			raise ValueError("ANTHROPIC_API_KEY not set")
		return {"provider": "anthropic", "model": model, "api_key": api_key}
	else:
		raise ValueError(f"unknown provider: {provider}")


def chat(
	config: dict,
	messages: list[dict],
	tools: list[dict] | None = None,
) -> dict:
	"""Send a chat request and return the raw message dict from the response.

	Returns: {"role": "assistant", "content": "...", "tool_calls": [...]}
	"""
	if config["provider"] == "ollama":
		return _chat_ollama(config, messages, tools)
	elif config["provider"] == "anthropic":
		return _chat_anthropic(config, messages, tools)
	else:
		raise ValueError(f"unknown provider: {config['provider']}")


def _chat_ollama(config: dict, messages: list[dict], tools: list[dict] | None) -> dict:
	body: dict = {
		"model": config["model"],
		"messages": messages,
		"stream": False,
	}
	if tools:
		body["tools"] = tools

	resp = httpx.post(
		f"{config['base_url']}/api/chat",
		json=body,
		timeout=300,
	)
	resp.raise_for_status()
	data = resp.json()
	msg = data.get("message", {})
	return {
		"role": "assistant",
		"content": msg.get("content", ""),
		"tool_calls": msg.get("tool_calls", []),
	}


def _chat_anthropic(config: dict, messages: list[dict], tools: list[dict] | None) -> dict:
	# Extract system message
	system_text = ""
	chat_msgs = []
	for m in messages:
		if m["role"] == "system":
			system_text += m["content"] + "\n"
		else:
			chat_msgs.append(m)

	body: dict = {
		"model": config["model"],
		"max_tokens": 8192,
		"messages": chat_msgs,
	}
	if system_text:
		body["system"] = system_text.strip()
	if tools:
		body["tools"] = [_to_anthropic_tool(t) for t in tools]

	resp = httpx.post(
		"https://api.anthropic.com/v1/messages",
		headers={
			"x-api-key": config["api_key"],
			"anthropic-version": "2023-06-01",
			"content-type": "application/json",
		},
		json=body,
		timeout=300,
	)
	resp.raise_for_status()
	data = resp.json()

	content = ""
	tool_calls = []
	for block in data.get("content", []):
		if block["type"] == "text":
			content += block["text"]
		elif block["type"] == "tool_use":
			tool_calls.append({
				"id": block["id"],
				"function": {
					"name": block["name"],
					"arguments": block["input"],
				},
			})

	return {
		"role": "assistant",
		"content": content,
		"tool_calls": tool_calls,
	}


def _to_anthropic_tool(ollama_tool: dict) -> dict:
	fn = ollama_tool["function"]
	return {
		"name": fn["name"],
		"description": fn.get("description", ""),
		"input_schema": fn["parameters"],
	}


def agent_loop(
	config: dict,
	system_prompt: str,
	user_message: str,
	tools: list[dict],
	execute_tool,
	max_iterations: int = 50,
	on_tool_call=None,
	on_response=None,
) -> str:
	"""Run a ReAct-style agent loop. Returns the final text response."""
	messages = [
		{"role": "system", "content": system_prompt},
		{"role": "user", "content": user_message},
	]

	for i in range(max_iterations):
		resp = chat(config, messages, tools)

		# If there's text content and no tool calls, we're done
		if resp["content"] and not resp["tool_calls"]:
			if on_response:
				on_response(resp["content"])
			return resp["content"]

		# If there are tool calls, execute them
		if resp["tool_calls"]:
			# Add assistant message to history
			if config["provider"] == "ollama":
				messages.append({"role": "assistant", "content": resp["content"], "tool_calls": resp["tool_calls"]})
			else:
				# Anthropic needs the raw content blocks
				messages.append(resp)

			for tc in resp["tool_calls"]:
				fn = tc.get("function", tc)
				name = fn.get("name", "")
				args = fn.get("arguments", {})
				if isinstance(args, str):
					import json
					args = json.loads(args)

				if on_tool_call:
					on_tool_call(name, args)

				result = execute_tool(name, args)

				if config["provider"] == "ollama":
					messages.append({"role": "tool", "content": result})
				else:
					messages.append({
						"role": "user",
						"content": [{
							"type": "tool_result",
							"tool_use_id": tc["id"],
							"content": result,
						}],
					})
		elif resp["content"]:
			# Content but no tool calls — done
			if on_response:
				on_response(resp["content"])
			return resp["content"]
		else:
			# No content, no tool calls — stuck
			print("warning: empty response from LLM", file=sys.stderr)
			return ""

	print("warning: hit max iterations", file=sys.stderr)
	return ""


def chat_loop(
	config: dict,
	system_prompt: str,
	messages: list[dict] | None = None,
) -> list[dict]:
	"""Simple chat (no tools). Returns full message history."""
	if messages is None:
		messages = [{"role": "system", "content": system_prompt}]

	resp = chat(config, messages)
	messages.append({"role": "assistant", "content": resp["content"]})
	return messages
