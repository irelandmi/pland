# pland

LLM-powered project planner for [taskd](https://github.com/irelandmi/taskd). Reads a PRD and decomposes it into epics, tasks, and dependencies in taskd.

## Install

```
uv sync
```

## Usage

### Capture a PRD interactively

```
uv run pland --provider ollama capture
uv run pland --provider ollama capture --output prd.md
```

The LLM asks clarifying questions to help you flesh out requirements. Type `done` to finalize the PRD.

### Create tickets from a PRD

```
uv run pland --provider ollama tickets prd.md
uv run pland --provider ollama tickets prd.md --dry-run   # preview plan without creating
uv run pland --provider ollama tickets - < prd.md         # read from stdin
```

Two-phase approach:
1. **Plan** — LLM reads the PRD and produces a structured JSON decomposition (project, epics, tasks, dependencies)
2. **Execute** — deterministic loop creates everything in taskd via the REST API

### Verbose logging

```
uv run pland -v --provider ollama tickets prd.md
```

Shows wall-clock timing for each phase and individual API calls.

## Configuration

| Flag | Env var | Default |
|------|---------|---------|
| `--provider` | `PLAND_PROVIDER` | `ollama` |
| `--model` | `PLAND_MODEL` | `llama3.1:8b` (ollama) / `claude-sonnet-4-20250514` (anthropic) |
| | `ANTHROPIC_API_KEY` | required for anthropic |
| | `PLAND_OLLAMA_URL` | `http://localhost:11434` |
| | `TASKD_URL` | `http://localhost:3000` |

## Requirements

- Python 3.12+
- A running taskd server
- Ollama with a pulled model, or an Anthropic API key
