from __future__ import annotations

from pydantic import BaseModel, Field


class PlannedLabel(BaseModel):
	name: str
	color: str = "#6b7280"


class PlannedTask(BaseModel):
	temp_id: str
	title: str
	description: str = ""
	kind: str = "task"
	priority: str = "medium"
	parent: str | None = None
	depends_on: list[str] = Field(default_factory=list)
	labels: list[str] = Field(default_factory=list)


class PlannedEpic(BaseModel):
	temp_id: str
	name: str
	description: str = ""
	tasks: list[PlannedTask] = Field(default_factory=list)


class Plan(BaseModel):
	project_name: str
	project_description: str = ""
	epics: list[PlannedEpic] = Field(default_factory=list)
	labels: list[PlannedLabel] = Field(default_factory=list)


class PRD(BaseModel):
	"""Accumulated requirements document built during the capture workflow."""
	title: str = ""
	content: str = ""
	sections: list[str] = Field(default_factory=list)


VALID_KINDS = {"story", "task", "spike", "bug", "chore"}
VALID_PRIORITIES = {"low", "medium", "high", "urgent"}


def validate_plan(plan: Plan) -> list[str]:
	errors: list[str] = []

	if not plan.project_name:
		errors.append("project_name is empty")
	if not plan.epics:
		errors.append("plan has no epics")

	all_task_ids: set[str] = set()
	epic_ids: set[str] = set()
	label_names = {l.name for l in plan.labels}

	for epic in plan.epics:
		if epic.temp_id in epic_ids:
			errors.append(f"duplicate epic temp_id: {epic.temp_id}")
		epic_ids.add(epic.temp_id)
		for task in epic.tasks:
			if task.temp_id in all_task_ids:
				errors.append(f"duplicate task temp_id: {task.temp_id}")
			all_task_ids.add(task.temp_id)

	for epic in plan.epics:
		for task in epic.tasks:
			if task.kind not in VALID_KINDS:
				errors.append(f"{task.temp_id}: invalid kind '{task.kind}'")
			if task.priority not in VALID_PRIORITIES:
				errors.append(f"{task.temp_id}: invalid priority '{task.priority}'")
			if task.parent and task.parent not in all_task_ids:
				errors.append(f"{task.temp_id}: parent '{task.parent}' not found")
			for dep in task.depends_on:
				if dep not in all_task_ids:
					errors.append(f"{task.temp_id}: dependency '{dep}' not found")
				if dep == task.temp_id:
					errors.append(f"{task.temp_id}: depends on itself")
			for label in task.labels:
				if label not in label_names:
					errors.append(f"{task.temp_id}: label '{label}' not defined")

	if _has_cycle(plan):
		errors.append("dependency cycle detected")

	return errors


def _has_cycle(plan: Plan) -> bool:
	adj: dict[str, list[str]] = {}
	for epic in plan.epics:
		for task in epic.tasks:
			adj[task.temp_id] = list(task.depends_on)

	visited: set[str] = set()
	in_stack: set[str] = set()

	def dfs(node: str) -> bool:
		if node in in_stack:
			return True
		if node in visited:
			return False
		visited.add(node)
		in_stack.add(node)
		for dep in adj.get(node, []):
			if dfs(dep):
				return True
		in_stack.discard(node)
		return False

	return any(dfs(n) for n in adj if n not in visited)


def topological_order(plan: Plan) -> list[PlannedTask]:
	all_tasks = {t.temp_id: t for e in plan.epics for t in e.tasks}

	in_degree: dict[str, int] = {tid: 0 for tid in all_tasks}
	for task in all_tasks.values():
		deps = list(task.depends_on)
		if task.parent and task.parent in all_tasks:
			deps.append(task.parent)
		for dep in deps:
			if dep in in_degree:
				in_degree[task.temp_id] += 1

	queue = sorted(tid for tid, deg in in_degree.items() if deg == 0)
	order: list[str] = []

	dependents: dict[str, list[str]] = {tid: [] for tid in all_tasks}
	for task in all_tasks.values():
		deps = list(task.depends_on)
		if task.parent and task.parent in all_tasks:
			deps.append(task.parent)
		for dep in deps:
			if dep in dependents:
				dependents[dep].append(task.temp_id)

	while queue:
		node = queue.pop(0)
		order.append(node)
		for dep in dependents.get(node, []):
			in_degree[dep] -= 1
			if in_degree[dep] == 0:
				queue.append(dep)
				queue.sort()

	return [all_tasks[tid] for tid in order if tid in all_tasks]


def format_preview(plan: Plan) -> str:
	total_tasks = sum(len(e.tasks) for e in plan.epics)
	total_deps = sum(len(t.depends_on) for e in plan.epics for t in e.tasks)

	lines = [
		f"Project: {plan.project_name}",
	]
	if plan.project_description:
		lines.append(f"  {plan.project_description}")
	lines.append("")
	lines.append(f"{len(plan.epics)} epics, {total_tasks} tasks, {total_deps} dependencies, {len(plan.labels)} labels")
	lines.append("")

	for epic in plan.epics:
		lines.append(f"  [{epic.temp_id}] {epic.name} ({len(epic.tasks)} tasks)")
		for task in epic.tasks:
			meta = [task.kind, task.priority]
			if task.parent:
				meta.append(f"parent:{task.parent}")
			if task.depends_on:
				meta.append(f"deps:{','.join(task.depends_on)}")
			if task.labels:
				meta.append(f"labels:{','.join(task.labels)}")
			lines.append(f"    [{task.temp_id}] {task.title} ({', '.join(meta)})")

	return "\n".join(lines)
