#!/usr/bin/env python3
"""Session health analyzer for agent-handoff skill.

Reads Claude Code session JSONL data, computes efficiency metrics,
detects handoff triggers, and outputs a JSON assessment.

Receives session_id and cwd via stdin (JSON).
Reuses pricing and path resolution from price-check.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

_pkg_root = str(Path(__file__).resolve().parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from price_check.main import (  # noqa: E402
    _find_session_jsonl,
    _ensure_pricing,
    get_pricing,
    cost_for_model,
    total_tokens,
    cache_pct,
    model_label,
    _empty_bucket,
    _NO_PRICING,
    PROJECTS_DIR,
    MAX_JSONL_SIZE,
    context_limit,
)
from price_check.parsing import (
    discover_subagent_files,
    iter_session_records,
)


def scan_per_turn(jsonl_path: Path) -> list[dict]:
    """Parse session JSONL into per-turn metrics, including subagent usage.

    Returns a list of dicts, one per user turn (promptId), each containing:
      - turn_number, prompt_id
      - token buckets (input, output, cache_read, cache_write)
      - model(s) used, cost, cache_hit_pct
      - tool_calls: list of {name, error} for repetition detection
    """
    turns: list[dict] = []
    seen_requests: set[str] = set()
    pid_to_turn: dict[str, int] = {}
    current_pid = None
    current_model_buckets: dict[str, dict] | None = None
    current_tools: list[dict] = []
    current_errors = 0
    current_calls = 0
    current_max_prompt_tokens = 0
    current_max_prompt_model = ""

    def _flush():
        nonlocal current_model_buckets, current_tools, current_errors, current_calls, current_max_prompt_tokens, current_max_prompt_model
        if current_model_buckets is None or current_pid is None:
            return
        idx = len(turns)
        pid_to_turn[current_pid] = idx
        turns.append({
            "turn_number": idx + 1,
            "prompt_id": current_pid,
            "_model_buckets": current_model_buckets,
            "tool_calls": current_tools,
            "error_count": current_errors,
            "api_calls": current_calls,
            "max_prompt_tokens": current_max_prompt_tokens,
            "max_prompt_model": current_max_prompt_model,
        })
        current_model_buckets = None
        current_tools = []
        current_errors = 0
        current_calls = 0
        current_max_prompt_tokens = 0
        current_max_prompt_model = ""

    # ── main session file (no fast_path — needs tool_use/tool_result records) ──
    for obj in iter_session_records(jsonl_path, include_subagents=False):
        pid = obj["_parsed_prompt_id"]
        is_system = obj["_parsed_is_system"]

        if is_system:
            continue

        if pid and pid != current_pid:
            _flush()
            current_pid = pid
            current_model_buckets = defaultdict(_empty_bucket)

        msg = obj.get("message") or {}
        if msg.get("role") == "assistant":
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_name = block.get("name", "")
                        current_tools.append({"name": tool_name, "error": False})
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        is_error = block.get("is_error", False)
                        if is_error and current_tools:
                            current_tools[-1]["error"] = True
                            current_errors += 1

        if msg.get("role") == "tool":
            content = msg.get("content")
            is_error = False
            if isinstance(content, str) and ("error" in content.lower() or "Error" in content):
                is_error = True
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        if block.get("is_error"):
                            is_error = True
                        text = block.get("text", "")
                        if "error" in text.lower() or "Error" in text:
                            is_error = True
            if is_error and current_tools:
                current_tools[-1]["error"] = True
                current_errors += 1

        req_id = obj.get("requestId")
        if not req_id or req_id in seen_requests:
            continue
        usage = msg.get("usage")
        if not usage or "output_tokens" not in usage:
            continue
        seen_requests.add(req_id)
        model = msg.get("model", "unknown")
        if model.startswith("<"):
            continue
        if current_model_buckets is None:
            current_model_buckets = defaultdict(_empty_bucket)
        bucket = current_model_buckets[model]
        req_input = usage.get("input_tokens", 0)
        req_cache_read = usage.get("cache_read_input_tokens", 0)
        bucket["input"] += req_input
        bucket["output"] += usage.get("output_tokens", 0)
        bucket["cache_read"] += req_cache_read
        bucket["cache_write"] += usage.get("cache_creation_input_tokens", 0)
        bucket["calls"] += 1
        current_calls += 1
        req_prompt = req_input + req_cache_read
        if req_prompt > current_max_prompt_tokens:
            current_max_prompt_tokens = req_prompt
            current_max_prompt_model = model

    _flush()

    # ── subagent files ──
    for sf in discover_subagent_files(jsonl_path):
        file_pids: set[str] = set()
        file_model_buckets: dict[str, dict] = defaultdict(_empty_bucket)
        file_calls = 0

        for obj in iter_session_records(sf, include_subagents=False, fast_path=True):
            pid = obj["_parsed_prompt_id"]
            if pid:
                file_pids.add(pid)

            req_id = obj.get("requestId")
            if not req_id or req_id in seen_requests:
                continue
            msg = obj.get("message") or {}
            usage = msg.get("usage")
            if not usage or "output_tokens" not in usage:
                continue
            seen_requests.add(req_id)
            model = msg.get("model", "unknown")
            if model.startswith("<"):
                continue
            bucket = file_model_buckets[model]
            bucket["input"] += usage.get("input_tokens", 0)
            bucket["output"] += usage.get("output_tokens", 0)
            bucket["cache_read"] += usage.get("cache_read_input_tokens", 0)
            bucket["cache_write"] += usage.get("cache_creation_input_tokens", 0)
            bucket["calls"] += 1
            file_calls += 1

        if not file_model_buckets:
            continue

        target_idx = None
        for pid in file_pids:
            if pid in pid_to_turn:
                target_idx = pid_to_turn[pid]
                break
        if target_idx is None and turns:
            # No matching promptId — attribute to the last turn as best guess
            import logging
            logging.getLogger(__name__).debug(
                "Subagent file %s has no matching turn promptId; attributing to last turn", sf.name,
            )
            target_idx = len(turns) - 1

        if target_idx is not None:
            turn_mb = turns[target_idx]["_model_buckets"]
            for model, sub_bucket in file_model_buckets.items():
                for k in ("input", "output", "cache_read", "cache_write", "calls"):
                    turn_mb[model][k] += sub_bucket[k]
            turns[target_idx]["api_calls"] += file_calls

    # ── finalize: compute derived fields from per-model buckets ──
    for t in turns:
        mb = t.pop("_model_buckets")
        combined = _empty_bucket()
        cost = 0.0
        for model, bucket in mb.items():
            for k in ("input", "output", "cache_read", "cache_write"):
                combined[k] += bucket[k]
            c = cost_for_model(bucket, model)
            if c is not None:
                cost += c
        t.update({
            "input": combined["input"],
            "output": combined["output"],
            "cache_read": combined["cache_read"],
            "cache_write": combined["cache_write"],
            "total_tokens": total_tokens(combined),
            "cache_hit_pct": cache_pct(combined),
            "cost": cost,
            "models": sorted(mb.keys()),
        })

    return turns


def assess_triggers(turns: list[dict]) -> list[dict]:
    """Evaluate all handoff triggers against the turn timeline."""
    triggers = []
    n = len(turns)

    # Totals
    total_tok = sum(t["total_tokens"] for t in turns)
    total_cost = sum(t["cost"] or 0 for t in turns)
    all_models = set()
    for t in turns:
        all_models.update(t["models"])

    # 1. Token volume (informational only — never drives recommendation)
    triggers.append({
        "trigger": "token_volume",
        "fired": False,
        "severity": "info",
        "evidence": {
            "total_tokens": total_tok,
        },
    })

    # 2. Efficiency decay — cost per turn trend
    if n >= 10:
        first5_cost = sum(t["cost"] or 0 for t in turns[:5]) / 5
        last5_cost = sum(t["cost"] or 0 for t in turns[-5:]) / 5
        ratio = last5_cost / first5_cost if first5_cost > 0 else 0
        fired = ratio > 2.0
        triggers.append({
            "trigger": "efficiency_decay",
            "fired": fired,
            "severity": "high" if ratio > 3 else ("medium" if fired else "none"),
            "evidence": {
                "cost_per_turn_first5": round(first5_cost, 4),
                "cost_per_turn_last5": round(last5_cost, 4),
                "ratio": round(ratio, 2),
            },
        })
    else:
        triggers.append({
            "trigger": "efficiency_decay",
            "fired": False,
            "severity": "none",
            "evidence": {"reason": f"insufficient turns ({n}), need >= 10"},
        })

    # 3. Cache degradation
    if n > 10:
        recent_turns = turns[10:]
        if recent_turns:
            avg_cache = sum(t["cache_hit_pct"] for t in recent_turns) / len(recent_turns)
            fired = avg_cache < 50
            sev = "none"
            if avg_cache < 30:
                sev = "high"
            elif avg_cache < 50:
                sev = "medium"
            triggers.append({
                "trigger": "cache_degradation",
                "fired": fired,
                "severity": sev,
                "evidence": {
                    "avg_cache_pct_after_turn10": round(avg_cache, 1),
                    "turns_analyzed": len(recent_turns),
                },
            })
        else:
            triggers.append({
                "trigger": "cache_degradation",
                "fired": False,
                "severity": "none",
                "evidence": {"reason": "no turns after turn 10"},
            })
    else:
        triggers.append({
            "trigger": "cache_degradation",
            "fired": False,
            "severity": "none",
            "evidence": {"reason": f"insufficient turns ({n}), need > 10"},
        })

    # 4. Context utilization — how full is the context window
    if n >= 1:
        last_turn = turns[-1]
        last_prompt_tokens = last_turn["max_prompt_tokens"]
        last_model = last_turn.get("max_prompt_model", "") or (last_turn["models"][0] if last_turn["models"] else "")
        ctx_lim = context_limit(last_model)

        # Detect compaction: a 40%+ drop in prompt tokens between consecutive
        # turns suggests context was summarized/compacted. Skip near-empty turns
        # (<1K tokens) to avoid false positives from cache-priming requests.
        compaction_count = 0
        for i in range(1, n):
            prev_ctx = turns[i - 1]["max_prompt_tokens"]
            curr_ctx = turns[i]["max_prompt_tokens"]
            if curr_ctx < 1000:
                continue
            if prev_ctx > 0 and curr_ctx < prev_ctx * 0.6:
                compaction_count += 1

        if ctx_lim:
            utilization = last_prompt_tokens / ctx_lim
            fired = utilization > 0.8 or compaction_count >= 2
            if utilization > 0.9 or compaction_count >= 3:
                sev = "high"
            elif fired:
                sev = "medium"
            else:
                sev = "none"
            triggers.append({
                "trigger": "context_utilization",
                "fired": fired,
                "severity": sev,
                "evidence": {
                    "current_utilization_pct": round(utilization * 100, 1),
                    "prompt_tokens": last_prompt_tokens,
                    "context_limit": ctx_lim,
                    "compaction_count": compaction_count,
                    "model": last_model,
                },
            })
        else:
            triggers.append({
                "trigger": "context_utilization",
                "fired": False,
                "severity": "none",
                "evidence": {"reason": f"unknown context limit for model {last_model}"},
            })
    else:
        triggers.append({
            "trigger": "context_utilization",
            "fired": False,
            "severity": "none",
            "evidence": {"reason": "no turns"},
        })

    # 5. Combined context pressure — multiple context-related signals together
    eff_fired = any(t["trigger"] == "efficiency_decay" and t["fired"] for t in triggers)
    cache_fired = any(t["trigger"] == "cache_degradation" and t["fired"] for t in triggers)
    ctx_fired = any(t["trigger"] == "context_utilization" and t["fired"] for t in triggers)
    combined_fired = (eff_fired and cache_fired) or (ctx_fired and (eff_fired or cache_fired))
    triggers.append({
        "trigger": "combined_context_pressure",
        "fired": combined_fired,
        "severity": "urgent" if combined_fired else "none",
        "evidence": {
            "efficiency_decay_fired": eff_fired,
            "cache_degradation_fired": cache_fired,
            "context_utilization_fired": ctx_fired,
        },
    })

    # 6. Rat-holing — repeated tool call patterns with errors
    if n >= 5:
        recent = turns[-5:]
        error_patterns: dict[str, int] = defaultdict(int)
        for t in recent:
            for tc in t["tool_calls"]:
                if tc["error"]:
                    error_patterns[tc["name"]] += 1

        repeated = {k: v for k, v in error_patterns.items() if v >= 3}
        fired = len(repeated) > 0
        triggers.append({
            "trigger": "rat_holing",
            "fired": fired,
            "severity": "high" if fired else "none",
            "evidence": {
                "repeated_error_tools": repeated,
                "turns_analyzed": len(recent),
            },
        })
    else:
        triggers.append({
            "trigger": "rat_holing",
            "fired": False,
            "severity": "none",
            "evidence": {"reason": f"insufficient turns ({n}), need >= 5"},
        })

    # 7. Model upgrade needed
    if n >= 5:
        recent = turns[-5:]
        avg_output = sum(t["output"] for t in recent) / len(recent)
        total_errors = sum(t["error_count"] for t in recent)
        total_calls = sum(t["api_calls"] for t in recent)
        error_rate = total_errors / total_calls if total_calls > 0 else 0
        fired = avg_output > 30_000 and error_rate > 0.15
        triggers.append({
            "trigger": "model_upgrade_needed",
            "fired": fired,
            "severity": "medium" if fired else "none",
            "evidence": {
                "avg_output_tokens_last5": round(avg_output),
                "error_rate_last5": round(error_rate, 3),
            },
        })
    else:
        triggers.append({
            "trigger": "model_upgrade_needed",
            "fired": False,
            "severity": "none",
            "evidence": {"reason": f"insufficient turns ({n})"},
        })

    # 8. Model downgrade possible
    if n >= 5:
        recent = turns[-5:]
        avg_output = sum(t["output"] for t in recent) / len(recent)
        uses_opus = any("opus" in m for t in recent for m in t["models"])
        fired = avg_output < 5_000 and uses_opus
        triggers.append({
            "trigger": "model_downgrade_possible",
            "fired": fired,
            "severity": "low" if fired else "none",
            "evidence": {
                "avg_output_tokens_last5": round(avg_output),
                "uses_opus": uses_opus,
            },
        })
    else:
        triggers.append({
            "trigger": "model_downgrade_possible",
            "fired": False,
            "severity": "none",
            "evidence": {"reason": f"insufficient turns ({n})"},
        })

    return triggers


def compute_recommendation(triggers: list[dict]) -> str:
    """Compute overall recommendation from trigger results."""
    severities = [t["severity"] for t in triggers if t["fired"]]
    if "urgent" in severities:
        return "urgent_handoff"
    if severities.count("high") >= 2 or "high" in severities:
        return "recommend_handoff"
    if "medium" in severities:
        return "watch"
    return "continue"


def analyze(session_id: str, cwd: str) -> dict:
    """Run full analysis on a session. Returns the assessment dict."""
    _ensure_pricing()

    jsonl_path = _find_session_jsonl(session_id, cwd)
    if not jsonl_path:
        return {"error": f"Session JSONL not found for {session_id}"}

    turns = scan_per_turn(jsonl_path)
    if not turns:
        return {"error": "No turns found in session"}

    triggers = assess_triggers(turns)
    recommendation = compute_recommendation(triggers)

    total_tok = sum(t["total_tokens"] for t in turns)
    total_cost = sum(t["cost"] or 0 for t in turns)
    all_models = set()
    for t in turns:
        all_models.update(t["models"])
    avg_cache = sum(t["cache_hit_pct"] for t in turns) / len(turns) if turns else 0

    timeline = []
    for t in turns:
        timeline.append({
            "turn": t["turn_number"],
            "tokens": t["total_tokens"],
            "cost": round(t["cost"] or 0, 4),
            "cache_hit_pct": round(t["cache_hit_pct"], 1),
            "output_tokens": t["output"],
            "models": t["models"],
        })

    return {
        "session_id": session_id,
        "stats": {
            "total_tokens": total_tok,
            "total_cost": round(total_cost, 4),
            "turns": len(turns),
            "avg_cache_hit_pct": round(avg_cache, 1),
            "models": sorted(all_models),
            "model_labels": [model_label(m) for m in sorted(all_models)],
        },
        "timeline": timeline,
        "triggers": triggers,
        "recommendation": recommendation,
    }


def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        print(json.dumps({"error": "Invalid JSON on stdin"}))
        sys.exit(1)

    session_id = hook_input.get("session_id", "")
    cwd = hook_input.get("cwd", "")

    if not session_id:
        print(json.dumps({"error": "No session_id provided"}))
        sys.exit(1)

    result = analyze(session_id, cwd)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
