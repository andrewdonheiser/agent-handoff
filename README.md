# Agent Handoff + Price Check

A combined toolkit for Claude Code that provides:

1. **Price Check** — CLI tool and status line integration for tracking Claude Code token usage and costs
2. **Agent Handoff** — Skill that analyzes session health, generates structured handoff documents, and manages handoff continuity across sessions

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

- **8 Health Triggers**: Token bloat, efficiency decay, cache degradation, context utilization, combined context pressure, rat-holing, model upgrade needed, model downgrade possible
- **Per-Turn Analytics**: Tracks tokens, cost, cache hit rates, and tool usage across the session timeline
- **Severity Levels**: `watch`, `recommend`, `urgent` based on trigger thresholds
- **Structured Handoffs**: Generates handoff documents with context for the next agent
- **Cost Projections**: Estimates remaining work complexity and suggests appropriate model tier
- **Multi-Handoff Retention**: Stores handoffs per-project in `~/.claude/handoffs/` with configurable retention limits and archive management
- **Session-Start Detection**: Automatically scans for pending handoffs when a new session begins and notifies the user
- **Auto-Draft Snapshots**: Optional mid-session draft snapshots saved on each turn (when enabled), folded into the final handoff
- **Cross-Project Awareness**: Detects pending handoffs from other projects
- **Load & Resume**: Load a previous handoff with `/agent-handoff --load` or `/agent-handoff --load-latest`

## Requirements

- Python 3.9+
- No external dependencies (stdlib only)
- Claude Code installed (reads from `~/.claude/projects/`)

## Installation

### Plugin Install (recommended)

```bash
git clone https://github.com/andrewdonheiser/agent-handoff.git
cd agent-handoff
make install
```

This registers hooks and skills automatically via the Claude Code plugin system.

### Manual Install

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

3. Add hooks to `~/.claude/settings.json`:

Price Check uses three integration points: a `SessionStart` hook (fetches latest pricing), a `Stop` hook (updates the status line after each turn), and a `statusLine` entry.

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
          },
          {
            "type": "command",
            "command": "PYTHONPATH=/path/to/agent-handoff python3 /path/to/agent-handoff/handoff/scan_pending.py",
            "timeout": 10
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

**If you already have hooks defined**, merge these entries into your existing config. Each hook event takes an array of matcher/hooks pairs — add new entries alongside your existing ones rather than replacing them.

Replace `/path/to/agent-handoff` with the actual path where you cloned the repo.

## Configuration

Handoff behavior is configured via `~/.claude/agent-handoff.json`. Create this file to customize defaults:

```json
{
  "notification": "proactive",
  "auto_handoff": false,
  "max_handoffs": 5,
  "max_consumed": 10
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `notification` | `"proactive"` | How to notify about pending handoffs at session start: `proactive` (agent mentions them), `passive` (available if asked), `quiet` (silent) |
| `auto_handoff` | `false` | When `true`, save lightweight draft snapshots on each turn via the Stop hook |
| `max_handoffs` | `5` | Maximum pending handoffs per project (oldest pruned first) |
| `max_consumed` | `10` | Maximum archived handoffs per project (`-1` for unlimited) |

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

Load a pending handoff from a previous session:
```
/agent-handoff --load
/agent-handoff --load-latest
```

See [SKILL.md](SKILL.md) for the full procedure and [references/](references/) for trigger definitions and handoff best practices.

## Project Structure

```
agent-handoff/
├── .claude-plugin/
│   └── plugin.json               # Claude Code plugin manifest
├── price_check/
│   ├── __init__.py               # Public API exports
│   ├── main.py                   # Token usage CLI, hooks, status line
│   └── parsing.py                # Shared JSONL parsing (iter_session_records, system prompt detection)
├── handoff/
│   ├── __init__.py               # Package init
│   ├── storage.py                # Handoff persistence, config, retention management
│   ├── cli.py                    # CLI wrapper for skill invocation
│   ├── scan_pending.py           # SessionStart hook: detect pending handoffs
│   └── drafts.py                 # Auto-draft snapshot management
├── scripts/
│   └── analyze_session.py        # Session health analyzer (imports from price_check)
├── skills/
│   └── agent-handoff/
│       └── SKILL.md              # Symlink to root SKILL.md (for plugin system)
├── tests/
│   ├── test_price_check.py       # Price check test suite
│   ├── test_analyze_session.py   # Session analyzer test suite
│   ├── test_parsing.py           # Parsing module test suite
│   ├── test_handoff_storage.py   # Storage & retention tests
│   ├── test_handoff_cli.py       # CLI wrapper tests
│   ├── test_scan_pending.py      # Session-start detection tests
│   └── test_handoff_drafts.py    # Auto-draft tests
├── references/
│   ├── handoff-guide.md          # Handoff best practices & model selection
│   └── handoff-triggers.md       # Trigger definitions & thresholds
├── hooks.json                    # Hook definitions for plugin system
├── Makefile                      # Plugin install/uninstall/validate/test
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

Multi-handoff retention, session-start detection, auto-draft snapshots, and plugin packaging are inspired by [cc-handoff](https://github.com/rhuss/cc-handoff) by [Roland Huss](https://github.com/rhuss).

## License

MIT
