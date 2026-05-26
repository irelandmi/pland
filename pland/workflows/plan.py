"""Plan workflow: decompose a PRD into a structured project plan.

Single LLM call to produce structured JSON, validate, and commit to taskd.
"""
from __future__ import annotations

import json
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from ..llm import get_model
from ..schema import Plan, format_preview, validate_plan
from ..taskd_client import commit_plan

PLAN_SCHEMA = """\
Return a JSON object with this exact schema (no markdown fences, just raw JSON):
{
  "project_name": "string",
  "project_description": "string",
  "epics": [
    {
      "temp_id": "epic-1",
      "name": "string",
      "description": "string",
      "tasks": [
        {
          "temp_id": "task-1",
          "title": "string",
          "description": "string",
          "kind": "story|task|spike|bug|chore",
          "priority": "low|medium|high|urgent",
          "parent": null,
          "depends_on": ["task-N"],
          "labels": ["label-name"]
        }
      ]
    }
  ],
  "labels": [
    { "name": "string", "color": "#hex" }
  ]
}

Rules:
- Use temp_ids like "epic-1", "task-1", "task-2" for cross-references
- parent and depends_on reference temp_ids within this plan
- No circular dependencies
- kind: story, task, spike, bug, chore
- priority: low, medium, high, urgent
- Group related tasks into epics
- Use stories for user-facing features, tasks for implementation, spikes for research
- Decompose into small actionable tasks (2-8 hours each)
- Set dependencies where one task genuinely blocks another
- Use parent for task hierarchies (story -> sub-tasks)"""


class PlanState(BaseModel):
	prd: str
	plan: Plan | None = None
	errors: list[str] = Field(default_factory=list)
	preview: str = ""
	committed: bool = False
	commit_result: dict = Field(default_factory=dict)
	dry_run: bool = False
	auto_confirm: bool = False
	confirmed: bool = False
	provider: str | None = None
	model: str | None = None


def generate(state: PlanState) -> dict:
	llm = get_model(state.provider, state.model)
	messages = [
		SystemMessage(content=f"You are a project planner.\n\n{PLAN_SCHEMA}"),
		HumanMessage(content=f"Decompose this PRD into a project plan:\n\n{state.prd}"),
	]
	response = llm.invoke(messages)
	text = response.content.strip() if isinstance(response.content, str) else str(response.content)

	# Strip markdown fences
	if text.startswith("```"):
		start = text.find("{")
		end = text.rfind("}") + 1
		if start >= 0 and end > start:
			text = text[start:end]

	try:
		plan = Plan.model_validate_json(text)
	except Exception as e:
		return {"errors": [f"failed to parse LLM response: {e}"]}

	return {"plan": plan}


def validate(state: PlanState) -> dict:
	if state.plan is None:
		return {}
	errors = validate_plan(state.plan)
	preview = format_preview(state.plan) if not errors else ""
	return {"errors": errors, "preview": preview}


def route_after_validate(state: PlanState) -> Literal["confirm", "__end__"]:
	if state.errors:
		return "__end__"
	if state.dry_run:
		return "__end__"
	if state.auto_confirm:
		return "confirm"
	return "confirm"


def commit(state: PlanState) -> dict:
	if state.plan is None:
		return {"errors": ["no plan to commit"]}
	if not state.confirmed and not state.auto_confirm:
		return {}
	try:
		result = commit_plan(state.plan)
		return {"committed": True, "commit_result": result}
	except Exception as e:
		return {"errors": [f"commit failed: {e}"]}


def build_plan_graph():
	g = StateGraph(PlanState)
	g.add_node("generate", generate)
	g.add_node("validate", validate)
	g.add_node("confirm", commit)

	g.set_entry_point("generate")
	g.add_edge("generate", "validate")
	g.add_conditional_edges("validate", route_after_validate, {
		"confirm": "confirm",
		"__end__": END,
	})
	g.add_edge("confirm", END)

	return g.compile(interrupt_before=["confirm"], checkpointer=MemorySaver())
