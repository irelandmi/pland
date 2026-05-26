"""CLI entry point for pland."""
from __future__ import annotations

import argparse
import sys

from .llm import agent_loop, chat, get_config
from .tools import execute_tool, get_tool_schemas


def run_capture(args):
	from .workflows.capture import FINALIZE_PROMPT, SYSTEM_PROMPT

	config = get_config(args.provider, args.model)
	messages = [{"role": "system", "content": SYSTEM_PROMPT}]

	# Initial LLM message
	resp = chat(config, messages)
	messages.append({"role": "assistant", "content": resp["content"]})
	print(f"\n{resp['content']}\n")

	# Conversation loop
	while True:
		try:
			user_input = input("> ").strip()
		except (EOFError, KeyboardInterrupt):
			print("\nAborted.")
			return

		if not user_input:
			continue

		if user_input.lower() in ("done", "done.", "/done"):
			messages.append({"role": "user", "content": FINALIZE_PROMPT})
			resp = chat(config, messages)
			prd = resp["content"]
			messages.append({"role": "assistant", "content": prd})
			print(f"\n{prd}\n")

			if args.output:
				with open(args.output, "w") as f:
					f.write(prd)
				print(f"Written to {args.output}")
			return

		messages.append({"role": "user", "content": user_input})
		resp = chat(config, messages)
		messages.append({"role": "assistant", "content": resp["content"]})
		print(f"\n{resp['content']}\n")


def run_tickets(args):
	import json
	from .workflows.tickets import EXEC_SYSTEM, PLAN_PROMPT

	if args.prd_file == "-":
		prd = sys.stdin.read()
	else:
		with open(args.prd_file) as f:
			prd = f.read()

	if not prd.strip():
		print("error: empty PRD", file=sys.stderr)
		sys.exit(1)

	config = get_config(args.provider, args.model)

	# Phase 1: Plan (no tools, LLM reads full PRD and produces JSON plan)
	print("Phase 1: Planning...", file=sys.stderr)
	resp = chat(config, [
		{"role": "system", "content": PLAN_PROMPT},
		{"role": "user", "content": prd},
	])
	plan_text = resp["content"].strip()

	# Extract JSON from response (may be wrapped in markdown or preamble text)
	if "{" in plan_text:
		start = plan_text.find("{")
		end = plan_text.rfind("}") + 1
		if start >= 0 and end > start:
			plan_text = plan_text[start:end]

	try:
		plan = json.loads(plan_text)
	except json.JSONDecodeError as e:
		print(f"error: failed to parse plan JSON: {e}", file=sys.stderr)
		print(plan_text[:500], file=sys.stderr)
		sys.exit(1)

	# Preview
	epics = plan.get("epics", [])
	total_tasks = sum(len(e.get("tasks", [])) for e in epics)
	print(f"  {plan.get('project_name', '?')}: {len(epics)} epics, {total_tasks} tasks", file=sys.stderr)

	if args.dry_run:
		print(json.dumps(plan, indent=2))
		return

	# Phase 2: Execute (tool calls with short messages)
	print("Phase 2: Creating in taskd...", file=sys.stderr)
	tools = get_tool_schemas()
	ids: dict[str, str] = {}  # title/name -> real ID

	def exec_and_track(name: str, tool_args: dict) -> str:
		result = execute_tool(name, tool_args)
		# Extract ID from result like "created project 'X' (id: abc-123)"
		if "(id: " in result:
			real_id = result.split("(id: ")[-1].rstrip(")")
			key = tool_args.get("title") or tool_args.get("name") or ""
			if key:
				ids[key] = real_id
		label = tool_args.get("title") or tool_args.get("name") or ""
		print(f"  -> {name}({label}) = {result}", file=sys.stderr)
		return result

	# Create project
	project_result = exec_and_track("create_project", {
		"name": plan.get("project_name", "Untitled"),
		"description": plan.get("project_description", ""),
	})
	project_id = ids.get(plan.get("project_name", ""))
	if not project_id:
		print(f"error: failed to create project: {project_result}", file=sys.stderr)
		sys.exit(1)

	# Create labels
	for label in plan.get("labels", []):
		exec_and_track("create_label", {
			"name": label["name"],
			"color": label.get("color", "#6b7280"),
		})

	# Create epics
	for epic in epics:
		exec_and_track("create_epic", {
			"project_id": project_id,
			"name": epic["name"],
			"description": epic.get("description", ""),
		})

	# Create tasks (need to resolve epic IDs and parent IDs)
	task_title_to_id: dict[str, str] = {}
	for epic in epics:
		epic_id = ids.get(epic["name"], "")
		for task in epic.get("tasks", []):
			result = exec_and_track("create_task", {
				"project_id": project_id,
				"title": task["title"],
				"description": task.get("description", ""),
				"kind": task.get("kind", "task"),
				"priority": task.get("priority", "medium"),
				"epic_id": epic_id or None,
				"labels": task.get("labels"),
			})
			if task["title"] in ids:
				task_title_to_id[task["title"]] = ids[task["title"]]

	# Wire up dependencies
	dep_count = 0
	for epic in epics:
		for task in epic.get("tasks", []):
			task_id = task_title_to_id.get(task["title"])
			if not task_id:
				continue
			for dep_title in task.get("depends_on", []):
				dep_id = task_title_to_id.get(dep_title)
				if dep_id:
					exec_and_track("add_dependency", {
						"task_id": task_id,
						"depends_on_id": dep_id,
					})
					dep_count += 1

	# Summary
	print(f"\nCreated project '{plan.get('project_name')}' ({project_id})")
	print(f"  {len(plan.get('labels', []))} labels, {len(epics)} epics, {len(task_title_to_id)} tasks, {dep_count} dependencies")


def main():
	parser = argparse.ArgumentParser(prog="pland", description="LLM-powered project planner for taskd")
	parser.add_argument("--provider", default=None, help="LLM provider (anthropic, ollama)")
	parser.add_argument("--model", default=None, help="model name")

	sub = parser.add_subparsers(dest="command", required=True)

	cap = sub.add_parser("capture", help="interactively build a PRD")
	cap.add_argument("--output", "-o", help="write PRD to file")

	tix = sub.add_parser("tickets", help="decompose a PRD into fleshed-out taskd tickets")
	tix.add_argument("prd_file", help="path to PRD file (use - for stdin)")
	tix.add_argument("--dry-run", action="store_true", help="show plan JSON without creating in taskd")

	args = parser.parse_args()

	if args.command == "capture":
		run_capture(args)
	elif args.command == "tickets":
		run_tickets(args)


if __name__ == "__main__":
	main()
