"""Tools that wrap the taskd REST API, with Ollama-native tool schemas."""
from __future__ import annotations

from .taskd_client import _client

# --- Tool implementations ---

def _create_project(name: str, description: str) -> str:
	client = _client()
	resp = client.post("/api/projects", json={"name": name, "description": description})
	client.close()
	if resp.status_code >= 400:
		return f"error: {resp.text}"
	data = resp.json()
	return f"created project '{data['name']}' (id: {data['id']})"


def _create_epic(project_id: str, name: str, description: str) -> str:
	client = _client()
	resp = client.post(f"/api/projects/{project_id}/epics", json={
		"name": name, "description": description,
	})
	client.close()
	if resp.status_code >= 400:
		return f"error: {resp.text}"
	data = resp.json()
	return f"created epic '{data['name']}' (id: {data['id']})"


def _create_task(
	project_id: str, title: str, description: str, kind: str, priority: str,
	epic_id: str | None = None, parent_id: str | None = None,
	labels: list[str] | None = None,
) -> str:
	body: dict = {
		"title": title, "description": description,
		"kind": kind, "priority": priority,
	}
	if epic_id:
		body["epic_id"] = epic_id
	if parent_id:
		body["parent_id"] = parent_id
	if labels:
		body["labels"] = labels
	client = _client()
	resp = client.post(f"/api/projects/{project_id}/tasks", json=body)
	client.close()
	if resp.status_code >= 400:
		return f"error: {resp.text}"
	data = resp.json()
	return f"created {data['kind']} '{data['title']}' (id: {data['id']})"


def _add_dependency(task_id: str, depends_on_id: str) -> str:
	client = _client()
	resp = client.post(f"/api/tasks/{task_id}/dependencies", json={"depends_on": depends_on_id})
	client.close()
	if resp.status_code >= 400:
		return f"error: {resp.text}"
	return f"added dependency: {task_id} blocked by {depends_on_id}"


def _create_label(name: str, color: str = "#6b7280") -> str:
	client = _client()
	resp = client.post("/api/labels", json={"name": name, "color": color})
	client.close()
	if resp.status_code >= 400:
		return f"error: {resp.text}"
	data = resp.json()
	return f"created label '{data['name']}' (id: {data['id']})"


def _list_project_tasks(project_id: str) -> str:
	client = _client()
	resp = client.get(f"/api/projects/{project_id}/tasks")
	client.close()
	if resp.status_code >= 400:
		return f"error: {resp.text}"
	tasks = resp.json()
	if not tasks:
		return "no tasks yet"
	lines = []
	for t in tasks:
		deps = ""
		if t.get("dependencies"):
			deps = f" (blocked by: {', '.join(t['dependencies'])})"
		lines.append(f"  [{t['id']}] {t['kind']}/{t['priority']}: {t['title']} [{t['status']}]{deps}")
	return "\n".join(lines)


def _list_project_epics(project_id: str) -> str:
	client = _client()
	resp = client.get(f"/api/projects/{project_id}/epics")
	client.close()
	if resp.status_code >= 400:
		return f"error: {resp.text}"
	epics = resp.json()
	if not epics:
		return "no epics yet"
	return "\n".join(f"  [{e['id']}] {e['name']} ({e['status']})" for e in epics)


# --- Registry: name -> (function, ollama tool schema) ---

TOOL_REGISTRY: dict[str, tuple] = {
	"create_project": (_create_project, {
		"type": "function",
		"function": {
			"name": "create_project",
			"description": "Create a new project in taskd.",
			"parameters": {
				"type": "object",
				"properties": {
					"name": {"type": "string", "description": "Project name"},
					"description": {"type": "string", "description": "Project description"},
				},
				"required": ["name", "description"],
			},
		},
	}),
	"create_epic": (_create_epic, {
		"type": "function",
		"function": {
			"name": "create_epic",
			"description": "Create an epic within a project.",
			"parameters": {
				"type": "object",
				"properties": {
					"project_id": {"type": "string", "description": "The project ID"},
					"name": {"type": "string", "description": "Epic name"},
					"description": {"type": "string", "description": "Epic description"},
				},
				"required": ["project_id", "name", "description"],
			},
		},
	}),
	"create_task": (_create_task, {
		"type": "function",
		"function": {
			"name": "create_task",
			"description": "Create a task within a project. Write thorough descriptions with context, requirements, acceptance criteria, and technical notes.",
			"parameters": {
				"type": "object",
				"properties": {
					"project_id": {"type": "string", "description": "The project ID"},
					"title": {"type": "string", "description": "Short actionable task title"},
					"description": {"type": "string", "description": "Detailed description with acceptance criteria, technical notes, and scope"},
					"kind": {"type": "string", "enum": ["story", "task", "spike", "bug", "chore"], "description": "Task kind"},
					"priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"], "description": "Task priority"},
					"epic_id": {"type": "string", "description": "Epic ID to assign to (optional)"},
					"parent_id": {"type": "string", "description": "Parent task ID for sub-tasks (optional)"},
					"labels": {"type": "array", "items": {"type": "string"}, "description": "Label names to apply (optional)"},
				},
				"required": ["project_id", "title", "description", "kind", "priority"],
			},
		},
	}),
	"add_dependency": (_add_dependency, {
		"type": "function",
		"function": {
			"name": "add_dependency",
			"description": "Add a dependency. The task cannot start until the dependency is done.",
			"parameters": {
				"type": "object",
				"properties": {
					"task_id": {"type": "string", "description": "The task that is blocked"},
					"depends_on_id": {"type": "string", "description": "The task that blocks it"},
				},
				"required": ["task_id", "depends_on_id"],
			},
		},
	}),
	"create_label": (_create_label, {
		"type": "function",
		"function": {
			"name": "create_label",
			"description": "Create a label for categorizing tasks.",
			"parameters": {
				"type": "object",
				"properties": {
					"name": {"type": "string", "description": "Label name"},
					"color": {"type": "string", "description": "Hex color code"},
				},
				"required": ["name"],
			},
		},
	}),
	"list_project_tasks": (_list_project_tasks, {
		"type": "function",
		"function": {
			"name": "list_project_tasks",
			"description": "List all tasks in a project to review what's been created.",
			"parameters": {
				"type": "object",
				"properties": {
					"project_id": {"type": "string", "description": "The project ID"},
				},
				"required": ["project_id"],
			},
		},
	}),
	"list_project_epics": (_list_project_epics, {
		"type": "function",
		"function": {
			"name": "list_project_epics",
			"description": "List all epics in a project.",
			"parameters": {
				"type": "object",
				"properties": {
					"project_id": {"type": "string", "description": "The project ID"},
				},
				"required": ["project_id"],
			},
		},
	}),
}


def get_tool_schemas() -> list[dict]:
	return [schema for _, schema in TOOL_REGISTRY.values()]


def execute_tool(name: str, args: dict) -> str:
	if name not in TOOL_REGISTRY:
		return f"error: unknown tool '{name}'"
	fn, _ = TOOL_REGISTRY[name]
	try:
		return fn(**args)
	except Exception as e:
		return f"error: {e}"
