"""Capture workflow: conversational PRD building.

The graph loops between the user and LLM until the user signals they're done,
then the LLM produces a structured PRD summary.
"""
from __future__ import annotations

from typing import Annotated, Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt
from pydantic import BaseModel, Field

from ..llm import get_model

SYSTEM_PROMPT = """\
You are a product requirements analyst helping the user define their project.

Your job:
1. Ask clarifying questions about scope, users, features, non-functional requirements, and priorities.
2. Help them think through edge cases and dependencies.
3. Keep responses concise — one or two questions at a time.
4. When the user says "done", produce a comprehensive PRD summary.

Do NOT generate a project plan or task breakdown — just the requirements document."""

FINALIZE_PROMPT = """\
The user is done providing input. Produce a final, comprehensive PRD that covers everything discussed.

Format it as a clear requirements document with sections:
- Overview
- Goals & Non-goals
- User Stories / Features
- Non-functional Requirements
- Open Questions (if any remain)

Be thorough but concise."""


class CaptureState(BaseModel):
	messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
	prd: str = ""
	done: bool = False
	provider: str | None = None
	model: str | None = None


def converse(state: CaptureState) -> dict:
	llm = get_model(state.provider, state.model)
	msgs = [SystemMessage(content=SYSTEM_PROMPT)] + list(state.messages)
	response = llm.invoke(msgs)
	return {"messages": [response]}


def user_input(state: CaptureState) -> dict:
	value = interrupt("waiting for user input")
	return {"messages": [HumanMessage(content=value)]}


def finalize(state: CaptureState) -> dict:
	llm = get_model(state.provider, state.model)
	msgs = [SystemMessage(content=SYSTEM_PROMPT)] + list(state.messages) + [
		HumanMessage(content=FINALIZE_PROMPT),
	]
	response = llm.invoke(msgs)
	return {"prd": response.content, "done": True, "messages": [response]}


def route_after_user(state: CaptureState) -> Literal["finalize", "converse"]:
	last = state.messages[-1] if state.messages else None
	if isinstance(last, HumanMessage):
		text = last.content.strip().lower() if isinstance(last.content, str) else ""
		if text in ("done", "done.", "/done"):
			return "finalize"
	return "converse"


def build_capture_graph():
	g = StateGraph(CaptureState)
	g.add_node("converse", converse)
	g.add_node("user_input", user_input)
	g.add_node("finalize", finalize)

	g.set_entry_point("converse")
	g.add_edge("converse", "user_input")
	g.add_conditional_edges("user_input", route_after_user, {
		"converse": "converse",
		"finalize": "finalize",
	})
	g.add_edge("finalize", END)

	return g.compile(checkpointer=MemorySaver())
