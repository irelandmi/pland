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
You are a senior product requirements analyst conducting a requirements gathering session.

Your approach:
- Ask 1-2 sharp, specific questions per turn. Never more.
- Systematically cover: users & personas, core workflows, UI/UX details, data model, \
integrations, real-time requirements, non-functional requirements, visual design.
- When a user gives a vague or short answer, push back and ask for specifics. \
Don't accept "yes" or "small scale" without a follow-up like "How many concurrent \
users?" or "What does 'small' mean — 5 projects or 50?"
- Track what you've covered and what you haven't. Mention gaps explicitly: \
"We haven't discussed X yet — let's cover that."
- NEVER summarize, draft, or produce any document mid-conversation.
- NEVER say "great" or "sounds good" — stay focused on uncovering requirements.
- Your tone is professional and direct, not chatty."""

FINALIZE_PROMPT = """\
Produce a comprehensive Product Requirements Document based on everything discussed. \
This must be a real PRD, not a feature list.

Required sections:

## 1. Overview
What this product is, who it's for, and the core problem it solves.

## 2. Goals & Non-goals
Explicit list of what's in scope and what's deliberately excluded.

## 3. User Personas
Who uses this and what their workflows look like.

## 4. User Stories
Concrete user stories in "As a [role], I want [action] so that [benefit]" format. \
Include acceptance criteria for each.

## 5. UI/UX Requirements
Layout, navigation, visual design language (specific colors, typography, animations, \
effects). Describe key screens and interactions.

## 6. Data Model & Integrations
What entities exist, how they relate, and what external systems are integrated.

## 7. Real-time Behavior
How live updates work (SSE, WebSocket), what gets updated in real-time, latency expectations.

## 8. Non-functional Requirements
Performance targets, browser support, accessibility, security considerations.

## 9. Open Questions
Unresolved items that need further discussion.

Be thorough and specific. Reference concrete details from the conversation."""


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
