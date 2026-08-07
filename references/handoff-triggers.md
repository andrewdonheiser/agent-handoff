# Handoff Triggers

## Token Bloat

Session total tokens have grown large enough to degrade performance.

| Level | Threshold | Action |
|-------|-----------|--------|
| Watch | >300K tokens | Monitor — cache may still be efficient |
| Recommend | >600K tokens | Handoff recommended — context window pressure |
| Urgent | >900K tokens | Handoff strongly recommended — near capacity |

## Efficiency Decay

Cost per turn is increasing, indicating more tokens needed per unit of work.

- **Signal**: Compare average cost of the last 5 turns to the first 5 turns
- **Threshold**: >2x increase triggers recommendation
- **Why it matters**: Rising cost-per-turn means the model is re-reading more context, generating longer outputs to compensate for lost coherence, or both

## Cache Degradation

Cache hit rate is dropping, meaning the model is re-processing context it should have cached.

| Level | Condition | Action |
|-------|-----------|--------|
| Watch | Cache hit % < 50% after turn 10 | Monitor |
| Recommend | Cache hit % < 30% after turn 10 | Handoff recommended |

## Rat-holing

The agent is repeating similar actions without making progress.

- **Signal**: 3+ identical error patterns or repeated tool calls in the last 5 turns
- **Severity**: High — this wastes tokens with no forward progress
- **Detection**: Look for repeated tool names with similar arguments and error outputs

## Model Mismatch — Upgrade Needed

The current model is struggling with the task complexity.

- **Signal**: High output token count combined with elevated error rate
- **Threshold**: Average turn >30K output tokens AND error rate >15%
- **Action**: Recommend upgrading to a more capable model

## Model Mismatch — Downgrade Possible

The remaining work is simple enough for a less expensive model.

- **Signal**: Low output tokens, simple tool calls, mechanical edits
- **Threshold**: Average turn <5K output tokens for last 5 turns on Opus
- **Severity**: Low (cost optimization, not a problem)

## Task Boundary

The current task is complete and a new distinct task is starting.

- **Signal**: Conversation flow analysis — completion messages followed by new task descriptions
- **Severity**: Info — a natural handoff point, not a problem indicator
