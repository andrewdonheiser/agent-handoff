# Agent Handoff

A Claude Code skill that analyzes session health and facilitates smooth handoffs between agents. Detects when a session has become inefficient due to token bloat, cache degradation, or stuck patterns, then generates structured handoff documents to transition work to a fresh agent.

## Why This Exists

Long Claude Code sessions can accumulate context bloat, leading to:
- **Exponential token costs** as the conversation grows
- **Cache degradation** when prompt caching becomes less effective
- **Rat-holing** when repeatedly hitting the same errors
- **Context dilution** where relevant information gets buried

This skill monitors session health across six triggers and recommends when to hand off work to a fresh agent, preserving continuity while regaining efficiency.

## Features

- **6 Health Triggers**: Token bloat, efficiency decay, cache degradation, rat-holing, model upgrade needed, model downgrade possible
- **Per-Turn Analytics**: Tracks tokens, cost, cache hit rates, and tool usage across the session timeline
- **Severity Levels**: `watch`, `recommend`, `urgent` based on trigger thresholds
- **Structured Handoffs**: Generates `HANDOFF.md` with context for the next agent
- **Cost Projections**: Estimates remaining work complexity and suggests appropriate model tier
- **Reuses Price-Check**: Leverages the [price-check](https://github.com/andrewdonheiser/price-check) project for pricing and JSONL parsing

## Installation

### Prerequisites

- Claude Code CLI, desktop app, or web app
- Python 3.8+
- The [price-check](https://github.com/andrewdonheiser/price-check) project cloned to `~/Projects/redhat/price-check/`

### Setup

1. Clone this repository:
   ```bash
   git clone https://github.com/andrewdonheiser/agent-handoff.git
   cd agent-handoff
   ```

2. Ensure the [price-check](https://github.com/andrewdonheiser/price-check) dependency is available:
   ```bash
   ls ~/Projects/redhat/price-check/main.py
   ```
   If not found, clone it:
   ```bash
   mkdir -p ~/Projects/redhat
   git clone https://github.com/andrewdonheiser/price-check.git ~/Projects/redhat/price-check
   ```

3. Register the skill globally (creates symlink in `~/.claude/skills/`):
   ```bash
   mkdir -p ~/.claude/skills
   ln -sf "$(pwd)" ~/.claude/skills/agent-handoff
   ```

4. Verify installation:
   ```bash
   ls -l ~/.claude/skills/agent-handoff
   ```

The skill is now available as `/agent-handoff` in any Claude Code session.

## Usage

### Basic Diagnostic

Run a health check on the current session:

```
/agent-handoff
```

This will:
1. Analyze the current session metrics
2. Present a diagnostic report with trigger assessment
3. Ask if you want to generate a handoff document (if triggers fired)

### Skip to Handoff

Generate a handoff document immediately:

```
/agent-handoff now
```

Skips the diagnostic display and goes straight to confirmation, then generates `HANDOFF.md`.

### Check Alias

```
/agent-handoff check
```

Same as the bare `/agent-handoff` invocation.

## Health Triggers

The skill evaluates six triggers to assess session health:

| Trigger | Description | Thresholds |
|---------|-------------|------------|
| **Token Bloat** | Total session tokens exceed efficiency thresholds | Watch: 300K, Recommend: 600K, Urgent: 900K |
| **Efficiency Decay** | Cost per turn has increased significantly | Recommend: 2x cost ratio |
| **Cache Degradation** | Prompt cache hit rate declining over time | Watch: <50%, Urgent: <30% |
| **Rat-Holing** | Repeated errors or stuck patterns (3+ similar errors) | Recommend: 3-4 errors, Urgent: 5+ |
| **Model Upgrade Needed** | Simple tasks on underpowered model showing repeated failures | Recommend: detected |
| **Model Downgrade Possible** | Complex model (Opus) on simple, successful tasks | Watch: detected |

See [`references/handoff-triggers.md`](references/handoff-triggers.md) for detailed trigger definitions.

## How It Works

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      SKILL.md (Procedure)                    │
│  1. Gather metrics  2. Report  3. Confirm  4. Generate doc  │
└─────────────────────┬───────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────────┐
│              scripts/analyze_session.py                      │
│  • Find session JSONL in ~/.claude/projects/                │
│  • Parse per-turn metrics (tokens, cost, cache, errors)     │
│  • Evaluate 6 triggers with thresholds                      │
│  • Output structured JSON recommendation                    │
└─────────────────────┬───────────────────────────────────────┘
                      │ imports
                      ▼
┌─────────────────────────────────────────────────────────────┐
│         ~/Projects/redhat/price-check/ (via sys.path)       │
│  • load_jsonl() – parse session files                       │
│  • pricing.json – model costs                               │
│  • calculate_turn_cost() – cost computation                 │
└─────────────────────────────────────────────────────────────┘
```

### Session Discovery

The script attempts to find the current session JSONL in this order:

1. `$SESSION_ID` environment variable (if set by Claude Code)
2. `$CLAUDE_SESSION_ID` environment variable (alternate)
3. Most recently modified `.jsonl` file in `~/.claude/projects/<cwd>/`

**Note**: Session ID env vars are not always available, so the fallback is usually used.

### Output Format

The analysis script outputs JSON with:

```json
{
  "session_id": "...",
  "stats": {
    "total_tokens": 1580000,
    "total_cost": 1.42,
    "turns": 4,
    "avg_cache_hit_pct": 75.2,
    "models": ["claude-sonnet-4-5-20250929"],
    "model_labels": ["Sonnet 5"]
  },
  "timeline": [
    {"turn": 1, "tokens": 908000, "cost": 0.82, "cache_hit_pct": 0.0, ...},
    ...
  ],
  "triggers": [
    {
      "trigger": "token_bloat",
      "fired": true,
      "severity": "urgent",
      "evidence": {"total_tokens": 1580000, "threshold_900k": true}
    },
    ...
  ],
  "recommendation": "urgent_handoff"
}
```

## Generated Handoff Document

When you confirm the handoff, the skill writes `HANDOFF.md` to your working directory with:

- **Why Hand Off**: Specific triggered conditions with evidence
- **What Was Accomplished**: Files changed, decisions made, key context
- **What Remains**: Ordered list of remaining tasks
- **Key Context for Next Agent**: Critical files, constraints, environment state
- **Recommended Next Agent**: Model tier, complexity estimate, cost projection
- **How to Start**: Exact steps to resume work in a fresh session

Example handoff workflow:

1. Session hits 900K tokens (urgent threshold)
2. Run `/agent-handoff` → see diagnostic report
3. Confirm handoff → `HANDOFF.md` generated
4. Commit or stash work, close session
5. New session: "Read HANDOFF.md and continue"
6. Fresh agent picks up with full context, zero token overhead

## Examples

### Healthy Session (No Action)

```
/agent-handoff

## Session Health Report

**Session**: 42e8c3d7... | **Turns**: 3 | **Cost**: $0.15 | **Tokens**: 237.5K
**Models**: Sonnet 5 | **Avg Cache Hit**: 33.3%

### Trigger Assessment

✅ All triggers healthy
- Token bloat: 237.5K tokens (well below 300K threshold)
- Efficiency decay: Insufficient data (need 10+ turns)
- Cache degradation: Insufficient data (need 10+ turns)

### Recommendation: continue

Session health looks good, no handoff needed.
```

### Bloated Session (Urgent Handoff)

```
/agent-handoff

## Session Health Report

**Session**: 0ea7b1b8... | **Turns**: 4 | **Cost**: $1.42 | **Tokens**: 1.58M
**Models**: Sonnet 5 | **Avg Cache Hit**: 72%

### Trigger Assessment

🔴 **Token Bloat (URGENT)**: 1.58M tokens consumed
   - Turn 1 alone used 908K tokens for initial implementation
   - Well past the 900K urgent threshold
   - Context window pressure increasing

✅ Cache degradation: 72% avg hit rate (healthy)
✅ No rat-holing detected

### Recommendation: urgent_handoff

Session has consumed 1.58M tokens — well past the 900K urgent threshold.
Hand off to a fresh agent to reset context overhead.

[Generate handoff document? Yes/No]
```

## Development

### Project Structure

```
agent-handoff/
├── SKILL.md                      # Skill definition (5-step procedure)
├── scripts/
│   └── analyze_session.py        # Session analysis engine
├── references/
│   ├── handoff-triggers.md       # Trigger definitions & thresholds
│   └── handoff-guide.md          # Best practices & model selection
└── README.md                     # This file
```

### Running the Analyzer Directly

Test the analyzer on any session:

```bash
echo '{"session_id": "YOUR_SESSION_ID", "cwd": "/path/to/project"}' \
  | python3 scripts/analyze_session.py
```

Or analyze the most recent session for a project:

```bash
cd /path/to/your/project
SESSION_ID=$(ls -t ~/.claude/projects/-$(pwd | sed 's|/|-|g')/*.jsonl | head -1 | xargs basename .jsonl)
echo "{\"session_id\": \"$SESSION_ID\", \"cwd\": \"$(pwd)\"}" \
  | python3 scripts/analyze_session.py
```

### Testing

No formal test suite yet. To test end-to-end:

1. Open a Claude Code session in a project
2. Run `/agent-handoff` to see diagnostics
3. Verify the report matches session state
4. Test `/agent-handoff now` to generate `HANDOFF.md`
5. Verify the handoff document contains accurate context

Recommended test cases:
- Very short session (1-2 turns)
- Multi-model session (Opus → Sonnet)
- Session with subagents
- Session with actual cache degradation
- Session with repeated errors (rat-holing)

## Limitations

- **Session ID Discovery**: Env vars `$SESSION_ID`/`$CLAUDE_SESSION_ID` not always available; fallback to most recent JSONL may pick wrong session if multiple are active
- **Price-Check Dependency**: Requires price-check project at `~/Projects/redhat/price-check/` — not yet packaged standalone
- **Trigger Calibration**: Thresholds (300K/600K/900K, 2x cost ratio, etc.) are based on empirical observation; may need tuning for different workflows
- **No Retroactive Analysis**: Can only analyze completed turns; can't detect mid-turn inefficiency

## References

- [`references/handoff-triggers.md`](references/handoff-triggers.md) — Trigger definitions and thresholds
- [`references/handoff-guide.md`](references/handoff-guide.md) — Handoff best practices and model selection guidance
- [price-check](https://github.com/andrewdonheiser/price-check) — Session pricing and JSONL parsing library

## Contributing

Contributions welcome! Areas for improvement:

- [ ] Better session ID discovery (detect actively-written JSONL)
- [ ] Package price-check as a dependency (eliminate hardcoded path)
- [ ] Tune trigger thresholds based on more session data
- [ ] Add formal test suite
- [ ] Support for multi-project sessions
- [ ] Detect mid-turn inefficiency (not just post-turn)
- [ ] Add `/agent-handoff stats` for historical trends across sessions

## License

MIT

## Author

Built with Claude Code (Sonnet 5) for the Red Hat AI tooling team.
