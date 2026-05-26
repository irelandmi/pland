"""Test the capture workflow prompts by simulating the conversation
from the user's session and evaluating PRD quality."""
from __future__ import annotations

import sys

from langchain_core.messages import HumanMessage, SystemMessage
from pland.llm import get_model

# The real conversation the user had
USER_MESSAGES = [
	"to create a cyberpunk kanban ui for project management",
	"developers but also product/project managers. it just needs to be in a familiar kanban style with a good interface of what is going on as it orchestrates ai agents.",
	"its more about providing realtime view and inspection of an ongoing ai agent swarm",
	"it has some logging, it should be able to inspect artifacts produced and link into git commits/PRs along with produced screenshots. as well as view the project epics/spikes/tasks/bugs",
	"yes",
	"small scale",
]

PRD_QUALITY_CRITERIA = [
	"user stories",
	"non-functional",
	"cyberpunk",
	"real-time",
	"kanban",
	"agent",
	"git",
	"commit",
	"epic",
	"task",
	"artifact",
	"screenshot",
]


def test_prompt(system_prompt: str, finalize_prompt: str, label: str):
	"""Run a full simulated conversation and evaluate the PRD."""
	llm = get_model("ollama", "llama3.1:8b")

	messages: list = []

	# Simulate conversation turns
	for i, user_msg in enumerate(USER_MESSAGES):
		messages.append(HumanMessage(content=user_msg))
		response = llm.invoke([SystemMessage(content=system_prompt)] + messages)
		messages.append(response)
		print(f"  Turn {i+1}: {len(response.content)} chars", file=sys.stderr)

	# Finalize
	messages.append(HumanMessage(content=finalize_prompt))
	response = llm.invoke([SystemMessage(content=system_prompt)] + messages)
	prd = response.content

	# Evaluate
	prd_lower = prd.lower()
	hits = [c for c in PRD_QUALITY_CRITERIA if c in prd_lower]
	misses = [c for c in PRD_QUALITY_CRITERIA if c not in prd_lower]
	score = len(hits) / len(PRD_QUALITY_CRITERIA) * 100

	print(f"\n{'='*60}")
	print(f"[{label}] Score: {score:.0f}% ({len(hits)}/{len(PRD_QUALITY_CRITERIA)})")
	print(f"  Hits: {', '.join(hits)}")
	print(f"  Misses: {', '.join(misses)}")
	print(f"  PRD length: {len(prd)} chars")
	print(f"{'='*60}")
	print(prd)
	print(f"{'='*60}\n")

	return score, prd


# --- Prompt variants ---

SYSTEM_V1 = """\
You are a product requirements analyst helping the user define their project.

Your job:
1. Ask clarifying questions about scope, users, features, non-functional requirements, and priorities.
2. Help them think through edge cases and dependencies.
3. Keep responses concise — one or two questions at a time.
4. When the user says "done", produce a comprehensive PRD summary.

Do NOT generate a project plan or task breakdown — just the requirements document."""

FINALIZE_V1 = """\
The user is done providing input. Produce a final, comprehensive PRD that covers everything discussed.

Format it as a clear requirements document with sections:
- Overview
- Goals & Non-goals
- User Stories / Features
- Non-functional Requirements
- Open Questions (if any remain)

Be thorough but concise."""

SYSTEM_V2 = """\
You are a senior product requirements analyst. Your ONLY job is to ask questions \
and gather requirements. You must NEVER summarize or produce a PRD until explicitly \
asked to finalize.

Behavior rules:
- Ask 1-2 focused questions per turn. Dig deeper before moving on.
- Cover these areas systematically: target users, core workflows, UI/UX specifics, \
  data model, integrations, real-time behavior, non-functional requirements (performance, \
  browser support, accessibility), visual design specifics.
- If the user gives a short answer, probe for details. "yes" or "small scale" should \
  trigger follow-up questions, not acceptance.
- Do NOT volunteer feature lists or summaries mid-conversation.
- Do NOT say "here's a draft" or "let me summarize" — just keep asking questions."""

FINALIZE_V2 = """\
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
Layout, navigation, visual design language (cyberpunk aesthetics: color palette, \
typography, animations, effects). Describe key screens and interactions.

## 6. Data Model & Integrations
What entities exist (projects, epics, tasks, etc.), how they relate, and what \
external systems are integrated (Git, CI, agent runtime).

## 7. Real-time Behavior
How live updates work (SSE, WebSocket), what gets updated in real-time, latency expectations.

## 8. Non-functional Requirements
Performance targets, browser support, accessibility, security considerations.

## 9. Open Questions
Unresolved items that need further discussion.

Be thorough and specific. Reference concrete details from the conversation."""

SYSTEM_V3 = """\
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

FINALIZE_V3 = FINALIZE_V2  # Same finalize, different conversation style


if __name__ == "__main__":
	import argparse
	parser = argparse.ArgumentParser()
	parser.add_argument("--variant", choices=["v1", "v2", "v3", "all"], default="all")
	args = parser.parse_args()

	variants = {
		"v1": (SYSTEM_V1, FINALIZE_V1, "v1-original"),
		"v2": (SYSTEM_V2, FINALIZE_V2, "v2-strict-gather"),
		"v3": (SYSTEM_V3, FINALIZE_V3, "v3-pushback"),
	}

	to_run = variants if args.variant == "all" else {args.variant: variants[args.variant]}
	results = {}

	for key, (sys_p, fin_p, label) in to_run.items():
		print(f"\nRunning variant: {label}", file=sys.stderr)
		score, prd = test_prompt(sys_p, fin_p, label)
		results[key] = (score, len(prd))

	if len(results) > 1:
		print("\n\nSummary:")
		for key, (score, length) in results.items():
			print(f"  {key}: {score:.0f}% coverage, {length} chars")
