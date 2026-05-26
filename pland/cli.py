"""CLI entry point for pland."""
from __future__ import annotations

import argparse
import sys

from langchain_core.messages import HumanMessage
from langgraph.types import Command


def run_capture(args):
	from .workflows.capture import build_capture_graph

	graph = build_capture_graph()
	config = {"configurable": {"thread_id": "capture-1"}}
	state = {"provider": args.provider, "model": args.model}

	def print_latest_ai(result):
		msgs = result.get("messages", [])
		for msg in reversed(msgs):
			if hasattr(msg, "type") and msg.type == "ai":
				print(f"\n{msg.content}\n")
				return

	# Initial invocation — LLM sends first message
	result = graph.invoke(state, config)
	print_latest_ai(result)

	# Conversation loop
	while not result.get("done", False):
		try:
			user_input = input("> ").strip()
		except (EOFError, KeyboardInterrupt):
			print("\nAborted.")
			return

		if not user_input:
			continue

		result = graph.invoke(Command(resume=user_input), config)
		print_latest_ai(result)

	if result.get("prd"):
		print("---")
		print("PRD captured. You can pipe this into `pland plan`:")
		if args.output:
			with open(args.output, "w") as f:
				f.write(result["prd"])
			print(f"  Written to {args.output}")
		else:
			print("  Use --output <file> to save, or copy from above.")


def run_plan(args):
	from .schema import format_preview
	from .workflows.plan import build_plan_graph

	if args.prd_file == "-":
		prd = sys.stdin.read()
	else:
		with open(args.prd_file) as f:
			prd = f.read()

	if not prd.strip():
		print("error: empty PRD", file=sys.stderr)
		sys.exit(1)

	graph = build_plan_graph()
	config = {"configurable": {"thread_id": "plan-1"}}
	state = {
		"prd": prd,
		"dry_run": args.dry_run,
		"auto_confirm": args.yes,
		"provider": args.provider,
		"model": args.model,
	}

	print("Generating plan...", file=sys.stderr)
	result = graph.invoke(state, config)

	if result.get("errors"):
		print("Errors:", file=sys.stderr)
		for e in result["errors"]:
			print(f"  - {e}", file=sys.stderr)
		sys.exit(1)

	if result.get("preview"):
		print(result["preview"])
		print()

	if args.dry_run:
		print("(dry run — nothing created)", file=sys.stderr)
		return

	if result.get("committed"):
		r = result["commit_result"]
		print(f"Created project {r['project_id']}: {r['epic_count']} epics, {r['task_count']} tasks, {r['label_count']} labels")
		return

	# Graph paused at confirm — ask user
	if not args.yes:
		try:
			answer = input("Create this project? [y/N] ").strip()
		except (EOFError, KeyboardInterrupt):
			print("\nAborted.")
			return
		if answer.lower() != "y":
			print("Aborted.")
			return

	result = graph.invoke(
		Command(resume=None, update={"confirmed": True}),
		config,
	)

	if result.get("errors"):
		print("Errors:", file=sys.stderr)
		for e in result["errors"]:
			print(f"  - {e}", file=sys.stderr)
		sys.exit(1)

	if result.get("committed"):
		r = result["commit_result"]
		print(f"Created project {r['project_id']}: {r['epic_count']} epics, {r['task_count']} tasks, {r['label_count']} labels")


def run_revise(args):
	from .workflows.revise import build_revise_graph

	graph = build_revise_graph()
	config = {"configurable": {"thread_id": "revise-1"}}
	state = {
		"project_id": args.project,
		"provider": args.provider,
		"model": args.model,
	}

	result = graph.invoke(state, config)

	if result.get("errors"):
		print("Errors:", file=sys.stderr)
		for e in result["errors"]:
			print(f"  - {e}", file=sys.stderr)
		sys.exit(1)

	# Print LLM's initial assessment
	for msg in result.get("messages", []):
		if hasattr(msg, "content") and msg.type == "ai":
			print(f"\n{msg.content}\n")

	# Conversation loop
	while not result.get("done", False) and not result.get("committed", False):
		try:
			user_input = input("> ").strip()
		except (EOFError, KeyboardInterrupt):
			print("\nAborted.")
			return

		if not user_input:
			continue

		result = graph.invoke(
			Command(resume=HumanMessage(content=user_input)),
			config,
		)

		if result.get("errors"):
			print("Errors:", file=sys.stderr)
			for e in result["errors"]:
				print(f"  - {e}", file=sys.stderr)
			if not result.get("revision"):
				sys.exit(1)

		for msg in result.get("messages", []):
			if hasattr(msg, "content") and msg.type == "ai":
				print(f"\n{msg.content}\n")

		# If graph paused at apply, confirm
		if result.get("revision") and not result.get("committed"):
			rev = result["revision"]
			print("Revision plan:")
			if rev.add_tasks:
				print(f"  Add {len(rev.add_tasks)} tasks")
			if rev.update_tasks:
				print(f"  Update {len(rev.update_tasks)} tasks")
			if rev.add_dependencies:
				print(f"  Add {len(rev.add_dependencies)} dependencies")
			if rev.remove_dependencies:
				print(f"  Remove {len(rev.remove_dependencies)} dependencies")

			if not args.yes:
				try:
					answer = input("Apply revision? [y/N] ").strip()
				except (EOFError, KeyboardInterrupt):
					print("\nAborted.")
					return
				if answer.lower() != "y":
					print("Aborted.")
					return

			result = graph.invoke(Command(resume=None), config)

			if result.get("errors"):
				print("Errors:", file=sys.stderr)
				for e in result["errors"]:
					print(f"  - {e}", file=sys.stderr)
			if result.get("committed"):
				print("Revision applied.")


def main():
	parser = argparse.ArgumentParser(prog="pland", description="LLM-powered project planner for taskd")
	parser.add_argument("--provider", default=None, help="LLM provider (anthropic, ollama)")
	parser.add_argument("--model", default=None, help="model name")

	sub = parser.add_subparsers(dest="command", required=True)

	cap = sub.add_parser("capture", help="interactively build a PRD")
	cap.add_argument("--output", "-o", help="write PRD to file")

	plan = sub.add_parser("plan", help="decompose a PRD into a taskd project")
	plan.add_argument("prd_file", help="path to PRD file (use - for stdin)")
	plan.add_argument("--dry-run", action="store_true", help="preview without creating")
	plan.add_argument("--yes", "-y", action="store_true", help="skip confirmation")

	rev = sub.add_parser("revise", help="revise an existing project plan")
	rev.add_argument("--project", "-p", required=True, help="taskd project ID")
	rev.add_argument("--yes", "-y", action="store_true", help="skip confirmation")

	args = parser.parse_args()

	if args.command == "capture":
		run_capture(args)
	elif args.command == "plan":
		run_plan(args)
	elif args.command == "revise":
		run_revise(args)


if __name__ == "__main__":
	main()
