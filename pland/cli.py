"""CLI entry point for pland."""
from __future__ import annotations

import argparse
import logging
import sys
import time

from .llm import chat, get_config
from .tools import execute_tool, get_tool_schemas

log = logging.getLogger("pland")


def _setup_logging(verbose: bool = False):
	level = logging.DEBUG if verbose else logging.INFO
	handler = logging.StreamHandler(sys.stderr)
	handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S"))
	logging.getLogger("pland").setLevel(level)
	logging.getLogger("pland").addHandler(handler)


def run_capture(args):
	from .workflows.capture import FINALIZE_PROMPT, SYSTEM_PROMPT

	config = get_config(args.provider, args.model)
	messages = [{"role": "system", "content": SYSTEM_PROMPT}]

	log.info("starting capture (provider=%s, model=%s)", config["provider"], config["model"])
	t0 = time.monotonic()

	resp = chat(config, messages)
	messages.append({"role": "assistant", "content": resp["content"]})
	log.debug("initial response in %.1fs", time.monotonic() - t0)
	print(f"\n{resp['content']}\n")

	turn = 0
	while True:
		try:
			user_input = input("> ").strip()
		except (EOFError, KeyboardInterrupt):
			print("\nAborted.")
			return

		if not user_input:
			continue

		turn += 1
		t1 = time.monotonic()

		if user_input.lower() in ("done", "done.", "/done"):
			messages.append({"role": "user", "content": FINALIZE_PROMPT})
			resp = chat(config, messages)
			prd = resp["content"]
			messages.append({"role": "assistant", "content": prd})
			log.info("finalized PRD in %.1fs (%d chars)", time.monotonic() - t1, len(prd))
			log.info("total capture time: %.1fs, %d turns", time.monotonic() - t0, turn)
			print(f"\n{prd}\n")

			if args.output:
				with open(args.output, "w") as f:
					f.write(prd)
				log.info("written to %s", args.output)
			return

		messages.append({"role": "user", "content": user_input})
		resp = chat(config, messages)
		messages.append({"role": "assistant", "content": resp["content"]})
		log.debug("turn %d response in %.1fs", turn, time.monotonic() - t1)
		print(f"\n{resp['content']}\n")


def run_tickets(args):
	import json
	from .workflows.tickets import PLAN_PROMPT

	if args.prd_file == "-":
		prd = sys.stdin.read()
	else:
		with open(args.prd_file) as f:
			prd = f.read()

	if not prd.strip():
		log.error("empty PRD")
		sys.exit(1)

	config = get_config(args.provider, args.model)
	log.info("starting tickets (provider=%s, model=%s, prd=%d chars)", config["provider"], config["model"], len(prd))
	t_total = time.monotonic()

	# Phase 1: Plan
	log.info("phase 1: planning...")
	t1 = time.monotonic()
	resp = chat(config, [
		{"role": "system", "content": PLAN_PROMPT},
		{"role": "user", "content": prd},
	])
	plan_text = resp["content"].strip()
	plan_time = time.monotonic() - t1
	log.info("phase 1 complete in %.1fs (%d chars response)", plan_time, len(plan_text))

	# Extract JSON
	if "{" in plan_text:
		start = plan_text.find("{")
		end = plan_text.rfind("}") + 1
		if start >= 0 and end > start:
			plan_text = plan_text[start:end]

	try:
		plan = json.loads(plan_text)
	except json.JSONDecodeError as e:
		log.error("failed to parse plan JSON: %s", e)
		log.debug("response: %s", plan_text[:500])
		sys.exit(1)

	epics = plan.get("epics", [])
	total_tasks = sum(len(e.get("tasks", [])) for e in epics)
	log.info("plan: %s — %d epics, %d tasks, %d labels",
		plan.get("project_name", "?"), len(epics), total_tasks, len(plan.get("labels", [])))

	if args.dry_run:
		print(json.dumps(plan, indent=2))
		log.info("dry run — nothing created (%.1fs total)", time.monotonic() - t_total)
		return

	# Phase 2: Execute
	log.info("phase 2: creating in taskd...")
	t2 = time.monotonic()
	ids: dict[str, str] = {}
	api_calls = 0

	def exec_and_track(name: str, tool_args: dict) -> str:
		nonlocal api_calls
		t = time.monotonic()
		result = execute_tool(name, tool_args)
		elapsed = time.monotonic() - t
		api_calls += 1
		if "(id: " in result:
			real_id = result.split("(id: ")[-1].rstrip(")")
			key = tool_args.get("title") or tool_args.get("name") or ""
			if key:
				ids[key] = real_id
		label = tool_args.get("title") or tool_args.get("name") or ""
		log.debug("  %s(%s) -> %s (%.0fms)", name, label, result, elapsed * 1000)
		return result

	# Create project
	project_result = exec_and_track("create_project", {
		"name": plan.get("project_name", "Untitled"),
		"description": plan.get("project_description", ""),
	})
	project_id = ids.get(plan.get("project_name", ""))
	if not project_id:
		log.error("failed to create project: %s", project_result)
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

	# Create tasks
	task_title_to_id: dict[str, str] = {}
	for epic in epics:
		epic_id = ids.get(epic["name"], "")
		for task in epic.get("tasks", []):
			exec_and_track("create_task", {
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

	exec_time = time.monotonic() - t2
	total_time = time.monotonic() - t_total

	log.info("phase 2 complete in %.1fs (%d API calls)", exec_time, api_calls)
	log.info("total: %.1fs (plan=%.1fs, exec=%.1fs)", total_time, plan_time, exec_time)

	print(f"\nCreated project '{plan.get('project_name')}' ({project_id})")
	print(f"  {len(plan.get('labels', []))} labels, {len(epics)} epics, {len(task_title_to_id)} tasks, {dep_count} dependencies")
	print(f"  {total_time:.1f}s total (plan={plan_time:.1f}s, exec={exec_time:.1f}s, {api_calls} API calls)")


def main():
	parser = argparse.ArgumentParser(prog="pland", description="LLM-powered project planner for taskd")
	parser.add_argument("--provider", default=None, help="LLM provider (anthropic, ollama)")
	parser.add_argument("--model", default=None, help="model name")
	parser.add_argument("-v", "--verbose", action="store_true", help="verbose logging")

	sub = parser.add_subparsers(dest="command", required=True)

	cap = sub.add_parser("capture", help="interactively build a PRD")
	cap.add_argument("--output", "-o", help="write PRD to file")

	tix = sub.add_parser("tickets", help="decompose a PRD into fleshed-out taskd tickets")
	tix.add_argument("prd_file", help="path to PRD file (use - for stdin)")
	tix.add_argument("--dry-run", action="store_true", help="show plan JSON without creating in taskd")

	args = parser.parse_args()
	_setup_logging(args.verbose)

	if args.command == "capture":
		run_capture(args)
	elif args.command == "tickets":
		run_tickets(args)


if __name__ == "__main__":
	main()
