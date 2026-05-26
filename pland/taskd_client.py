from __future__ import annotations

import os

import httpx

from .schema import Plan, topological_order

DEFAULT_URL = "http://localhost:3000"


def base_url() -> str:
	return os.environ.get("TASKD_URL", DEFAULT_URL)


def _client() -> httpx.Client:
	return httpx.Client(base_url=base_url(), timeout=30)


def commit_plan(plan: Plan) -> dict:
	"""Create the full project structure in taskd. Returns summary with real IDs."""
	client = _client()

	project = client.post("/api/projects", json={
		"name": plan.project_name,
		"description": plan.project_description,
	}).raise_for_status().json()
	project_id = project["id"]

	label_map: dict[str, str] = {}
	for planned_label in plan.labels:
		label = client.post("/api/labels", json={
			"name": planned_label.name,
			"color": planned_label.color,
		}).raise_for_status().json()
		label_map[planned_label.name] = label["id"]

	epic_map: dict[str, str] = {}
	for planned_epic in plan.epics:
		epic = client.post(f"/api/projects/{project_id}/epics", json={
			"name": planned_epic.name,
			"description": planned_epic.description,
		}).raise_for_status().json()
		epic_map[planned_epic.temp_id] = epic["id"]

	task_epic: dict[str, str] = {}
	for planned_epic in plan.epics:
		real_epic_id = epic_map[planned_epic.temp_id]
		for task in planned_epic.tasks:
			task_epic[task.temp_id] = real_epic_id

	ordered = topological_order(plan)
	task_map: dict[str, str] = {}

	for task in ordered:
		epic_id = task_epic[task.temp_id]
		parent_id = task_map.get(task.parent) if task.parent else None

		body: dict = {
			"title": task.title,
			"description": task.description,
			"epic_id": epic_id,
			"kind": task.kind,
			"priority": task.priority,
			"labels": task.labels,
		}
		if parent_id:
			body["parent_id"] = parent_id

		created = client.post(f"/api/projects/{project_id}/tasks", json=body).raise_for_status().json()
		task_map[task.temp_id] = created["id"]

	for task in ordered:
		if not task.depends_on:
			continue
		real_id = task_map[task.temp_id]
		for dep_temp_id in task.depends_on:
			dep_real_id = task_map[dep_temp_id]
			client.post(f"/api/tasks/{real_id}/dependencies", json={
				"depends_on": dep_real_id,
			}).raise_for_status()

	client.close()

	return {
		"project_id": project_id,
		"epic_count": len(epic_map),
		"task_count": len(task_map),
		"label_count": len(label_map),
		"task_map": task_map,
	}


def get_project_state(project_id: str) -> dict:
	"""Fetch current project state from taskd for the revise workflow."""
	client = _client()
	project = client.get(f"/api/projects/{project_id}").raise_for_status().json()
	epics = client.get(f"/api/projects/{project_id}/epics").raise_for_status().json()
	tasks = client.get(f"/api/projects/{project_id}/tasks").raise_for_status().json()
	client.close()
	return {"project": project, "epics": epics, "tasks": tasks}
