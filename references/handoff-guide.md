# Handoff Guide

## What Makes a Good Handoff

A good handoff document lets the next agent start productive work within its first turn. The test: could a capable engineer pick up this document cold and know exactly what to do next?

**Be specific, not general.** Name files, line numbers, function names, error messages. "The auth middleware needs work" is useless. "src/middleware/auth.ts:47 — the token validation skips expiry checks when `NODE_ENV=test`, which also runs in staging" is actionable.

## Context Triage

Organize context by what the next agent actually needs:

### Must Know
- What was accomplished (with specifics — files changed, tests added)
- What remains (ordered by priority)
- Blockers and open questions
- Decisions already made and WHY (so the next agent doesn't re-litigate)
- Environment state (branch, uncommitted changes, running services, env vars)

### Nice to Know
- Approaches that were tried and failed (saves the next agent from repeating)
- Constraints discovered during the work
- Relevant context from conversation that isn't in the code

### Derivable from Code (Skip)
- File structure descriptions
- What functions do (the code says this)
- Import relationships
- Test coverage numbers (run the tests)

## Model Selection Guidance

### Use Opus When
- Designing architecture or making cross-cutting decisions
- Debugging complex multi-file issues
- Large refactors that require holding many files in context
- Tasks requiring deep reasoning about trade-offs
- Writing or reviewing security-sensitive code

### Use Sonnet When
- Implementing a well-specified feature
- Straightforward bug fixes with clear reproduction
- Writing tests for existing code
- Code review with clear criteria
- Documentation tasks requiring code understanding

### Use Haiku When
- Mechanical edits (rename, reformat, update imports)
- Simple find-and-replace style changes
- Generating boilerplate from templates
- Quick lookups or simple questions about the code

## Anti-patterns

- **Dumping the conversation**: Never paste the entire conversation history. Summarize what matters.
- **Vague tasks**: "Continue the work" tells the next agent nothing. List specific remaining items.
- **Missing environment state**: Not mentioning the branch, uncommitted changes, or required env vars forces the next agent to discover these.
- **Omitting failed approaches**: If you spent 30 minutes on an approach that didn't work, say so — or the next agent will try it again.
- **Over-specifying implementation**: Tell the next agent WHAT to do and WHY, not exactly HOW line-by-line. They may find a better approach.

## Handoff Execution Steps

1. **Commit or stash**: Ensure all meaningful work is saved. `git stash -u` for work-in-progress, commit for completed work.
2. **Verify no broken state**: Run tests, check for syntax errors. Don't hand off a broken build.
3. **Write the handoff doc**: Use the structured format with specific, actionable content.
4. **Note the start command**: Tell the user exactly how to present the doc to the next agent.

## Cost Projections

Rough estimates based on task complexity:

| Complexity | Typical Cost (Opus) | Typical Cost (Sonnet) |
|-----------|--------------------|-----------------------|
| Simple fix / small edit | $0.50–2 | $0.10–0.50 |
| Feature implementation | $2–8 | $0.50–2 |
| Multi-file refactor | $5–15 | $1–5 |
| Architecture / design | $3–10 | $1–3 |
| Complex debugging | $5–20 | $2–8 |

These are rough guides — actual cost depends on codebase size, context needed, and iteration cycles.
