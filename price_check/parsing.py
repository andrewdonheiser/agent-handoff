"""Low-level JSONL session parsing — shared by price_check and analyze_session."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

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


def discover_subagent_files(jsonl_path: Path) -> list[Path]:
    subagents_dir = jsonl_path.parent / jsonl_path.stem / "subagents"
    if subagents_dir.is_dir():
        return list(subagents_dir.rglob("agent-*.jsonl"))
    return []


def iter_session_records(
    jsonl_path: Path,
    *,
    include_subagents: bool = True,
    fast_path: bool = False,
) -> Iterator[dict]:
    """Yield every parsed JSONL record from a session file, enriched with prompt tracking.

    Each yielded dict is the original parsed JSON object with added keys:
      - _parsed_prompt_id: the current promptId (may be None)
      - _parsed_is_system: True if this promptId was detected as a system prompt
      - _parsed_source: "main" or "subagent"
      - _parsed_attribution_agent: agent type string (subagent records only)
      - _parsed_subagent_file: Path to the subagent file (subagent records only)

    fast_path: if True, skip lines that don't contain '"usage"' or '"promptId"'
               (unsafe for consumers that need tool_use/tool_result records).
    """
    system_pids: set[str] = set()

    try:
        fh = jsonl_path.open()
    except OSError:
        return

    with fh:
        for line in fh:
            if fast_path and '"usage"' not in line and '"promptId"' not in line:
                continue
            try:
                obj = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                continue

            pid = obj.get("promptId")
            is_system = False
            if pid and pid not in system_pids:
                if _is_system_prompt(obj):
                    system_pids.add(pid)
                    is_system = True
            elif pid and pid in system_pids:
                is_system = True

            yield {
                **obj,
                "_parsed_prompt_id": pid,
                "_parsed_is_system": is_system,
                "_parsed_source": "main",
            }

    if not include_subagents:
        return

    for sf in discover_subagent_files(jsonl_path):
        try:
            sfh = sf.open()
        except OSError:
            continue
        agent_type = ""
        with sfh:
            for line in sfh:
                if fast_path and '"usage"' not in line and '"promptId"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

                if not agent_type:
                    agent_type = obj.get("attributionAgent", "")

                pid = obj.get("promptId")
                yield {
                    **obj,
                    "_parsed_prompt_id": pid,
                    "_parsed_is_system": False,
                    "_parsed_source": "subagent",
                    "_parsed_attribution_agent": agent_type,
                    "_parsed_subagent_file": sf,
                }
