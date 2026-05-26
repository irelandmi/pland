# Cyberpunk Kanban UI for AI Agent Swarm Management

## Overview
A real-time Kanban board with a cyberpunk visual theme for monitoring and managing
AI agent swarms. Built for developers and project/product managers who need visibility
into what autonomous agents are doing, what they've produced, and how work is progressing.

## Goals & Non-goals

### In scope
- Real-time visualization of AI agent swarm activity
- Kanban board with standard columns (todo, in_progress, done, blocked)
- Viewing project epics, spikes, tasks, and bugs
- Inspecting artifacts produced by agents (code, screenshots, logs)
- Linking tasks to Git commits and PRs
- Cyberpunk-themed UI (dark theme, neon accents, futuristic typography)
- SSE-based live updates from taskd backend

### Out of scope
- Agent orchestration or control (this is view-only)
- User authentication (single-user for now)
- Mobile-responsive design (desktop-first)
- Gantt charts or timeline views

## User Personas

### Developer
Works with the AI agent swarm daily. Needs to see what agents are working on,
inspect their outputs, review code changes, and identify issues quickly.

### Project Manager
Oversees the overall project. Wants epic-level progress visibility, dependency
tracking, and the ability to see which tasks are blocked and why.

## Key Features

### Kanban Board
- Drag-and-drop task cards between columns
- Cards show: title, kind, priority, assignee, labels, dependency status
- Filter by epic, label, kind, assignee
- Group by epic or flat view

### Task Detail Panel
- Full task description with markdown rendering
- Activity log / event history
- List of outputs (files, commits, URLs, screenshots)
- Clickable links to Git commits and PRs
- Child tasks and dependency graph

### Epic Overview
- List of epics with progress bars
- Drill down into epic tasks
- Epic-level status and description

### Real-time Updates
- SSE connection to taskd server
- Live card movement when task status changes
- New task cards appear automatically
- Activity feed updates in real-time

### Artifact Inspector
- View screenshots inline
- View file diffs for code artifacts
- Link out to full commit/PR on GitHub

## Visual Design
- Dark background (#0a0a0f) with neon accent colors (#00ff88, #ff0066, #00ccff)
- Monospace font for IDs and code, sans-serif for headings
- Glowing borders and hover effects on cards
- Subtle scan-line or grid overlay effect
- Status colors: todo=#6b7280, in_progress=#00ccff, done=#00ff88, blocked=#ff0066

## Technical Context
- Backend: taskd REST API (existing) with SSE endpoint at /api/events
- Frontend: standalone SPA (React or similar)
- Data model: projects, epics, tasks (with kinds: story/task/spike/bug/chore),
  labels, task_outputs, task_dependencies, task_events

## Non-functional Requirements
- Initial page load < 2 seconds
- Real-time updates < 1 second latency
- Works in Chrome, Firefox, Edge (latest)
- WCAG 2.1 AA color contrast compliance
