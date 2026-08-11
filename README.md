# Agent Handoff + Price Check

A combined toolkit for Claude Code that provides:

1. **Price Check** — CLI tool and status line integration for tracking Claude Code token usage and costs
2. **Agent Handoff** — Skill that analyzes session health and generates structured handoff documents

## Features

### Price Check

- **Per-model cost tracking** with correct rates for all Claude models (Opus, Sonnet, Haiku, Fable)
- **Dynamic pricing** — fetches latest rates from Anthropic on session start
- **Daily usage summary** with token breakdown (cache read, cache write, LLM output) and cost estimates
- **Period totals** — Today, Week, and Month cost aggregates in the status line
- **Turn tracking** — counts unique prompts per session and per day
- **Per-session drill-down** with per-model sub-rows for multi-model sessions
- **Project-level aggregation** across all sessions
- **Subagent tracking** — discovers subagent JSONL files and displays per-type invocation counts
- **Claude Code status line** showing per-model prompt, session, and period costs
- **Rates table** — view current pricing with `--rates`
- **Markdown export** with clipboard copy support

### Agent Handoff

- **6 Health Triggers**: Token bloat, efficiency decay, cache degradation, rat-holing, model upgrade needed, model downgrade possible
- **Per-Turn Analytics**: Tracks tokens, cost, cache hit rates, and tool usage across the session timeline
- **Severity Levels**: `watch`, `recommend`, `urgent` based on trigger thresholds
- **Structured Handoffs**: Generates `HANDOFF.md` with context for the next agent
- **Cost Projections**: Estimates remaining work complexity and suggests appropriate model tier

## Requirements

- Python 3.9+
- No external dependencies (stdlib only)
- Claude Code installed (reads from `~/.claude/projects/`)

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/andrewdonheiser/agent-handoff.git
   cd agent-handoff
   ```

2. Register the skill globally:
   ```bash
   mkdir -p ~/.claude/skills
   ln -sf "$(pwd)" ~/.claude/skills/agent-handoff
   ```

### Setting up Claude Code hooks

Price Check uses three integration points in `~/.claude/settings.json`: a `SessionStart` hook (fetches latest pricing), a `Stop` hook (updates the status line after each turn), and a `statusLine` entry.

**If you don't have existing hooks**, you can add the full block:

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/agent-handoff/price_check/main.py --session-start",
            "timeout": 20
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/agent-handoff/price_check/main.py --hook",
            "timeout": 10
          }
        ]
      }
    ]
  },
  "statusLine": {
    "type": "command",
    "command": "python3 /path/to/agent-handoff/price_check/main.py --status-line"
  }
}
```

**If you already have hooks defined**, merge these entries into your existing config:

- Append the `SessionStart` and `Stop` objects to the corresponding arrays. Each hook event (`SessionStart`, `Stop`, etc.) takes an array of matcher/hooks pairs — add a new entry alongside your existing ones rather than replacing them.
- If you already have a `statusLine`, you'll need to wrap both commands in a shell script or choose one, since `statusLine` only accepts a single command.

For example, if you already have a `Stop` hook:

```json
{
  "hooks": {
    "Stop": [
      {
        "matcher": "",
        "hooks": [
          { "type": "command", "command": "your-existing-stop-hook" }
        ]
      },
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /path/to/agent-handoff/price_check/main.py --hook",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

Replace `/path/to/agent-handoff` with the actual path where you cloned the repo.

## Usage

### Price Check CLI

```bash
# Daily summary (last 7 days)
python3 price_check/main.py

# Last 30 days
python3 price_check/main.py 30

# Sessions for a specific date
python3 price_check/main.py --sessions today
python3 price_check/main.py --sessions 2026-07-27

# Project views
python3 price_check/main.py --projects
python3 price_check/main.py --top-projects

# Model rates
python3 price_check/main.py --rates

# Force-refresh pricing
python3 price_check/main.py --update-pricing

# Markdown export with clipboard copy
python3 price_check/main.py --markdown --copy
```

### Agent Handoff Skill

Run a health check on the current session:
```
/agent-handoff
```

Generate a handoff document immediately:
```
/agent-handoff now
```

See [SKILL.md](SKILL.md) for the full procedure and [references/](references/) for trigger definitions and handoff best practices.

## Project Structure

```
agent-handoff/
├── price_check/
│   ├── __init__.py               # Public API exports
│   └── main.py                   # Token usage CLI, hooks, status line
├── scripts/
│   └── analyze_session.py        # Session health analyzer (imports from price_check)
├── tests/
│   └── test_price_check.py       # Test suite
├── references/
│   ├── handoff-guide.md          # Handoff best practices & model selection
│   └── handoff-triggers.md       # Trigger definitions & thresholds
├── SKILL.md                      # Claude Code skill definition
└── README.md
```

## Testing

```bash
python3 -m pytest tests/ -v
```

## Pricing

Rates are fetched automatically from Anthropic's pricing page when Claude Code starts (via the `SessionStart` hook) and cached at `~/.claude/price-check-rates.json`. A 13% volume discount is applied to all cost calculations (configurable via the `_DISCOUNT` constant in `price_check/main.py`).

## Acknowledgments

Price Check is based on [claude-usage](https://gist.github.com/rhuss/67a7d9d300285350ff12563b6074a9e4) by [Roland Huss](https://github.com/rhuss).

## License

MIT
