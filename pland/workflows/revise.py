"""Revise workflow: amend plans based on spike findings or changing requirements.

Fetches current project state from taskd, takes user input about what changed
(spike results, new requirements, scope changes), and produces a delta plan
with new tasks, modified tasks, or removed tasks.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from ..llm import get_model
from ..taskd_client import get_project_state

SYSTEM_PROMPT = """\
You are a project plan revision assistant. The user has an existing project in taskd
and wants to revise the plan based on new information (completed spikes, changing
requirements, scope adjustments).

You have access to the current project state. Help the user decide what to change,
then produce a revision plan."""

REVISION_SCHEMA = """\
When the user is ready, produce a JSON revision plan:
{
  "add_tasks": [
    {
      "epic": "epic name or ID",
      "title": "string",
      "description": "string",
      "kind": "story|task|spike|bug|chore",
      "priority": "low|medium|high|urgent",
      "depends_on_existing": ["existing-task-id"],
      "labels": ["label-name"]
    }
  ],
  "update_tasks": [
    {
      "id": "existing-task-id",
      "title": "new title (optional)",
      "description": "new description (optional)",
      "priority": "new priority (optional)",
      "status": "cancelled (to remove from plan)"
    }
  ],
  "add_dependencies": [
    { "task": "task-id", "depends_on": "other-task-id" }
  ],
  "remove_dependencies": [
    { "task": "task-id", "depends_on": "other-task-id" }
  ]
}

Return ONLY this JSON when finalizing. No markdown fences."""


class RevisionPlan(BaseModel):
	add_tasks: list[dict] = Field(default_factory=list)
	update_tasks: list[dict] = Field(default_factory=list)
	add_dependencies: list[dict] = Field(default_factory=list)
	remove_dependencies: list[dict] = Field(default_factory=list)


class ReviseState(BaseModel):
	project_id: str
	project_state: dict = Field(default_factory=dict)
	messages: Annotated[list[BaseMessage], add_messages] = Field(default_factory=list)
	revision: RevisionPlan | None = None
	committed: bool = False
	errors: list[str] = Field(default_factory=list)
	done: bool = False
	provider: str | None = None
	model: str | None = None


def fetch_state(state: ReviseState) -> dict:
	try:
		project_state = get_project_state(state.project_id)
	except Exception as e:
		return {"errors": [f"failed to fetch project: {e}"]}

	project = project_state["project"]
	tasks = project_state["tasks"]
	epics = project_state["epics"]

	summary_lines = [f"Project: {project['name']} ({project['id']})"]
	summary_lines.append(f"Epics: {len(epics)}")
	summary_lines.append(f"Tasks: {len(tasks)}")
	summary_lines.append("")
	for task in tasks:
		status = task.get("status", "?")
		kind = task.get("kind", "?")
		summary_lines.append(f"  [{task['id'][:12]}] {kind}/{status}: {task['title']}")

	summary = "\n".join(summary_lines)

	intro = SystemMessage(content=f"{SYSTEM_PROMPT}\n\nCurrent project state:\n{summary}\n\n{REVISION_SCHEMA}")
	return {"project_state": project_state, "messages": [intro]}


def converse(state: ReviseState) -> dict:
	llm = get_model(state.provider, state.model)
	response = llm.invoke(state.messages)
	return {"messages": [response]}


def finalize(state: ReviseState) -> dict:
	llm = get_model(state.provider, state.model)
	msgs = state.messages + [
		HumanMessage(content="Produce the final revision plan JSON now."),
	]
	response = llm.invoke(msgs)
	text = response.content.strip() if isinstance(response.content, str) else str(response.content)

	if text.startswith("```"):
		start = text.find("{")
		end = text.rfind("}") + 1
		if start >= 0 and end > start:
			text = text[start:end]

	try:
		revision = RevisionPlan.model_validate_json(text)
	except Exception as e:
		return {"errors": [f"failed to parse revision: {e}"], "messages": [response]}

	return {"revision": revision, "done": True, "messages": [response]}


def apply_revision(state: ReviseState) -> dict:
	if state.revision is None:
		return {"errors": ["no revision to apply"]}

	import httpx
	from ..taskd_client import base_url

	client = httpx.Client(base_url=base_url(), timeout=30)
	errors: list[str] = []

	for task_update in state.revision.update_tasks:
		task_id = task_update.pop("id", None)
		if not task_id:
			errors.append("update_tasks entry missing 'id'")
			continue
		try:
			client.patch(f"/api/tasks/{task_id}", json=task_update).raise_for_status()
		except Exception as e:
			errors.append(f"failed to update {task_id}: {e}")

	for new_task in state.revision.add_tasks:
		epic = new_task.pop("epic", None)
		depends_on_existing = new_task.pop("depends_on_existing", [])
		try:
			if epic:
				new_task["epic_id"] = epic
			created = client.post(
				f"/api/projects/{state.project_id}/tasks",
				json=new_task,
			).raise_for_status().json()
			for dep_id in depends_on_existing:
				client.post(
					f"/api/tasks/{created['id']}/dependencies",
					json={"depends_on": dep_id},
				).raise_for_status()
		except Exception as e:
			errors.append(f"failed to create task: {e}")

	for dep in state.revision.add_dependencies:
		try:
			client.post(
				f"/api/tasks/{dep['task']}/dependencies",
				json={"depends_on": dep["depends_on"]},
			).raise_for_status()
		except Exception as e:
			errors.append(f"failed to add dependency: {e}")

	for dep in state.revision.remove_dependencies:
		try:
			client.delete(
				f"/api/tasks/{dep['task']}/dependencies/{dep['depends_on']}",
			).raise_for_status()
		except Exception as e:
			errors.append(f"failed to remove dependency: {e}")

	client.close()

	if errors:
		return {"errors": errors}
	return {"committed": True}


def route_after_user(state: ReviseState) -> Literal["finalize", "converse"]:
	last = state.messages[-1] if state.messages else None
	if isinstance(last, HumanMessage):
		text = last.content.strip().lower() if isinstance(last.content, str) else ""
		if text in ("done", "done.", "/done"):
			return "finalize"
	return "converse"


def build_revise_graph():
	g = StateGraph(ReviseState)
	g.add_node("fetch_state", fetch_state)
	g.add_node("converse", converse)
	g.add_node("user_input", lambda s: s)
	g.add_node("finalize", finalize)
	g.add_node("apply", apply_revision)

	g.set_entry_point("fetch_state")
	g.add_edge("fetch_state", "converse")
	g.add_edge("converse", "user_input")
	g.add_conditional_edges("user_input", route_after_user, {
		"converse": "converse",
		"finalize": "finalize",
	})
	g.add_edge("finalize", "apply")
	g.add_edge("apply", END)

	return g.compile(interrupt_before=["user_input", "apply"], checkpointer=MemorySaver())
