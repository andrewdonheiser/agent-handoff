#!/usr/bin/env python3
"""Session health analyzer for agent-handoff skill.

Reads Claude Code session JSONL data, computes efficiency metrics,
detects handoff triggers, and outputs a JSON assessment.

Receives session_id and cwd via stdin (JSON).
Reuses pricing and path resolution from price-check.
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from price_check.main import (
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
)

_SAFE_ID = re.compile(r"^[a-zA-Z0-9_-]+$")
_SYSTEM_PREFIXES = ("<system-reminder", "<task-notification", "<command-message")


def _is_system_prompt(obj: dict) -> bool:
    content = obj.get("message", {}).get("content")
    if isinstance(content, str):
        for pfx in _SYSTEM_PREFIXES:
            if content.lstrip().startswith(pfx):
                return True
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                text = block.get("text", "")
                for pfx in _SYSTEM_PREFIXES:
                    if text.lstrip().startswith(pfx):
                        return True
    return False


def scan_per_turn(jsonl_path: Path) -> list[dict]:
    """Parse session JSONL into per-turn metrics.

    Returns a list of dicts, one per user turn (promptId), each containing:
      - turn_number, prompt_id
      - token buckets (input, output, cache_read, cache_write)
      - model(s) used, cost, cache_hit_pct
      - tool_calls: list of {name, error} for repetition detection
    """
    turns: list[dict] = []
    seen_requests: set[str] = set()
    system_pids: set[str] = set()
    current_pid = None
    current_bucket = None
    current_models: set[str] = set()
    current_tools: list[dict] = []
    current_errors = 0
    current_calls = 0

    def _flush():
        nonlocal current_bucket, current_models, current_tools, current_errors, current_calls
        if current_bucket is None or current_pid is None:
            return
        model_list = sorted(current_models)
        cost = None
        if model_list:
            cost = 0.0
            for m in model_list:
                mbucket = {k: current_bucket[k] for k in ("input", "output", "cache_read", "cache_write")}
                c = cost_for_model(mbucket, m)
                if c is not None:
                    cost += c
        turns.append({
            "turn_number": len(turns) + 1,
            "prompt_id": current_pid,
            "input": current_bucket["input"],
            "output": current_bucket["output"],
            "cache_read": current_bucket["cache_read"],
            "cache_write": current_bucket["cache_write"],
            "total_tokens": total_tokens(current_bucket),
            "cache_hit_pct": cache_pct(current_bucket),
            "cost": cost,
            "models": model_list,
            "tool_calls": current_tools,
            "error_count": current_errors,
            "api_calls": current_calls,
        })
        current_bucket = None
        current_models = set()
        current_tools = []
        current_errors = 0
        current_calls = 0

    try:
        fh = jsonl_path.open()
    except OSError:
        return []

    with fh:
        for line in fh:
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            pid = obj.get("promptId")

            if pid and pid not in system_pids:
                if _is_system_prompt(obj):
                    system_pids.add(pid)
                    continue
                if pid != current_pid:
                    _flush()
                    current_pid = pid
                    current_bucket = _empty_bucket()

            if pid and pid in system_pids:
                continue

            # Tool call tracking
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

            # Tool result error tracking (tool_result messages)
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

            # Usage accumulation
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
            if current_bucket is None:
                current_bucket = _empty_bucket()
            current_bucket["input"] += usage.get("input_tokens", 0)
            current_bucket["output"] += usage.get("output_tokens", 0)
            current_bucket["cache_read"] += usage.get("cache_read_input_tokens", 0)
            current_bucket["cache_write"] += usage.get("cache_creation_input_tokens", 0)
            current_models.add(model)
            current_calls += 1

    _flush()
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

    # 1. Token bloat
    severity = None
    if total_tok > 900_000:
        severity = "urgent"
    elif total_tok > 600_000:
        severity = "high"
    elif total_tok > 300_000:
        severity = "medium"
    triggers.append({
        "trigger": "token_bloat",
        "fired": severity is not None,
        "severity": severity or "none",
        "evidence": {
            "total_tokens": total_tok,
            "threshold_300k": total_tok > 300_000,
            "threshold_600k": total_tok > 600_000,
            "threshold_900k": total_tok > 900_000,
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

    # 4. Rat-holing — repeated tool call patterns with errors
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

    # 5. Model upgrade needed
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

    # 6. Model downgrade possible
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
