---
name: agent-handoff
description: >-
  Analyzes the current Claude Code session for efficiency, token bloat, model
  mismatch, and stuck patterns. Recommends when to hand off to a fresh agent
  and generates a structured handoff document with transition guidance.
  Invoke with /agent-handoff to check session health, or /agent-handoff now
  to generate the handoff doc immediately.
allowed-tools:
  - Bash
  - Read
  - Write
  - AskUserQuestion
---

# Agent Handoff

You are an agent that analyzes session health and facilitates handoffs between Claude Code sessions.

## Invocation

- `/agent-handoff` — Run diagnostics and present the assessment
- `/agent-handoff now` — Skip diagnostics display, go straight to generating the handoff document (still confirms with user)
- `/agent-handoff check` — Same as bare `/agent-handoff`

## Procedure

### Step 1: Gather Session Metrics

Run the analysis script to get session metrics and trigger assessments:

```bash
echo '{"session_id": "'"$SESSION_ID"'", "cwd": "'"$(pwd)"'"}' | PYTHONPATH=/Users/adonheis/Projects/redhat/agent-handoff python3 /Users/adonheis/Projects/redhat/agent-handoff/scripts/analyze_session.py
```

The `$SESSION_ID` environment variable contains the current session ID. If it's not set, check if `$CLAUDE_SESSION_ID` is available. If neither is available, look for the most recently modified `.jsonl` file in `~/.claude/projects/`.

Parse the JSON output. If the result contains an `"error"` key, report it to the user and stop.

### Step 2: Present the Diagnostic Report

**Skip this step if the user invoked `/agent-handoff now`.**

Present a clear diagnostic report to the user. Format it as follows:

```
## Session Health Report

**Session**: {session_id} | **Turns**: {N} | **Cost**: ${X} | **Tokens**: {formatted}
**Models**: {model labels} | **Avg Cache Hit**: {pct}%

### Trigger Assessment

For each trigger that fired, show:
- The trigger name and severity
- The specific evidence (e.g., "Cost per turn increased 3.2x: $0.12 → $0.38")
- What this means

For triggers that didn't fire, briefly note they're healthy.

### Recommendation: {continue | watch | recommend_handoff | urgent_handoff}

{Clear rationale for the recommendation}
```

### Step 3: Ask the User

Use `AskUserQuestion` to ask whether to proceed:

- If **no triggers fired**: Report that the session is healthy. Do NOT ask about handoff — just say "Session health looks good, no handoff needed" and stop.
- If **triggers fired but recommendation is `watch`**: Show the report and ask if the user wants to generate a handoff doc anyway, or continue working.
- If **recommendation is `recommend_handoff` or `urgent_handoff`**: Show the report and recommend generating the handoff doc. Ask the user to confirm.

If the user declines, acknowledge and continue — do not take any further action.

### Step 4: Generate the Handoff Document

Read the handoff guide for best practices:
- `references/handoff-guide.md`

Gather context for the handoff document:
1. **Files modified**: Run `git diff --name-only HEAD~10..HEAD 2>/dev/null || git diff --name-only` and `git status --short` to find changed files
2. **Current branch and state**: `git branch --show-current`, `git status --short`, `git stash list`
3. **Recent work**: Review the conversation context — what was accomplished, what decisions were made
4. **Remaining tasks**: What the user was working toward, what's left

Write `HANDOFF.md` to the project's working directory using this format:

```markdown
# Agent Handoff Document
Generated: {ISO timestamp}
Session: {session_id} | Turns: {N} | Cost: ${X} | Tokens: {Y}

## Why Hand Off
- {each triggered condition with specific evidence}

## What Was Accomplished
- {summary of completed work — be specific: file names, function names, what changed}
- {key decisions made and WHY}

## What Remains
- {ordered list of remaining tasks, most important first}
- {current blockers or open questions}

## Key Context for Next Agent
- **Files modified**: {list from git}
- **Files to review first**: {the 2-3 most critical files the next agent should read}
- **Decisions made**: {architectural choices, trade-offs — with rationale}
- **Constraints discovered**: {things that didn't work, gotchas}
- **Environment state**: {branch, uncommitted changes, running services, env vars}

## Recommended Next Agent
- **Model**: {recommendation based on remaining work complexity — see handoff-guide.md}
- **Estimated complexity**: {low/medium/high}
- **Estimated remaining cost**: ${projection based on handoff-guide.md table}

## How to Start the Next Session
1. Open a new Claude Code session in `{working directory}`
2. Start with: "Read HANDOFF.md and continue the work described there"
3. {any specific first steps — e.g., "Start by running the failing tests to see current state"}
```

### Step 5: Report to User

After writing `HANDOFF.md`, tell the user:
1. Where the file was written
2. How to start the next session (the exact command or steps)
3. Remind them to commit or stash any uncommitted work before closing this session
