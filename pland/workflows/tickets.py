"""Tickets workflow: decompose a PRD into fully fleshed-out taskd tickets.

Uses a multi-phase approach to work within small model context limits:
1. Planning phase: LLM reads PRD and produces a structured decomposition (no tools)
2. Execution phase: feed the plan back in smaller chunks with tool calls
"""
from __future__ import annotations

PLAN_PROMPT = """\
You are a senior technical project planner. Read this PRD and produce a structured \
project decomposition as JSON. Do NOT call any tools — just return the JSON.

Return this exact format:
{
  "project_name": "short name",
  "project_description": "one-line description",
  "labels": [{"name": "label", "color": "#hex"}],
  "epics": [
    {
      "name": "Epic Name",
      "description": "what this epic covers",
      "tasks": [
        {
          "title": "Actionable task title",
          "description": "Detailed description with:\\n- Context\\n- Requirements\\n- Acceptance criteria\\n- Technical notes",
          "kind": "story|task|spike|bug|chore",
          "priority": "low|medium|high|urgent",
          "labels": ["label-name"],
          "depends_on": ["title of blocking task"]
        }
      ]
    }
  ]
}

Guidelines:
- 15-25 well-described tasks, not 40 thin ones
- Small tasks (2-8 hours each)
- Actionable titles: "Implement X", "Design Y", "Spike: Evaluate Z"
- Rich descriptions with acceptance criteria
- story = user-facing, task = implementation, spike = research, chore = setup
- Only add depends_on where one task's output is genuinely needed by another"""

EXEC_SYSTEM = """\
You are executing a project plan. Use the provided tools to create everything in taskd. \
Call one tool at a time. Use the IDs returned by previous tool calls for references."""
