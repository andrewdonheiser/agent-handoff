#!/usr/bin/env python3
"""SessionStart hook: scan for pending handoffs and notify the agent.

Reads {session_id, cwd} from stdin (JSON). Outputs a notification
message to stdout based on config notification mode. Always exits 0.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_pkg_root = str(Path(__file__).resolve().parent.parent)
if _pkg_root not in sys.path:
    sys.path.insert(0, _pkg_root)

from handoff.storage import (
    get_project_slug,
    list_all_project_slugs,
    list_pending,
    load_config,
)


def _drafts_dir(slug: str) -> Path:
    from handoff.storage import _drafts_dir
    return _drafts_dir(slug)


def _count_drafts(slug: str) -> int:
    d = _drafts_dir(slug)
    if not d.exists():
        return 0
    return sum(1 for f in d.iterdir() if f.is_file() and f.suffix == ".md")


def scan(cwd: str) -> dict:
    """Scan for pending handoffs and return notification info.

    Returns dict with:
      - current_project: slug
      - current_pending: list of filenames
      - other_projects: {slug: count} for other projects with pending handoffs
      - drafts_count: number of drafts for current project
      - notification_mode: from config
      - message: formatted notification text (empty if quiet or nothing pending)
    """
    config = load_config()
    mode = config.get("notification", "proactive")
    slug = get_project_slug(cwd)

    # Promote orphaned drafts (from sessions that ended without an explicit
    # handoff) into the pending list so the normal load flow can pick them up.
    if config.get("auto_handoff", False):
        from handoff.drafts import promote_drafts
        promote_drafts(slug)

    current_pending = list_pending(slug)
    drafts_count = _count_drafts(slug)

    other_projects = {}
    for other_slug in list_all_project_slugs():
        if other_slug == slug:
            continue
        other_pending = list_pending(other_slug)
        if other_pending:
            other_projects[other_slug] = len(other_pending)

    message = ""
    if mode == "quiet":
        pass
    elif current_pending or drafts_count or other_projects:
        parts = []
        if current_pending:
            count = len(current_pending)
            s = "s" if count != 1 else ""
            parts.append(
                f"{count} pending handoff{s} for this project ({slug}). "
                f"Run `/agent-handoff --load` to review or `/agent-handoff --load-latest` to load the most recent."
            )
        if drafts_count:
            s = "s" if drafts_count != 1 else ""
            parts.append(
                f"{drafts_count} session draft{s} available. "
                f"Run `/agent-handoff --load` to review."
            )
        if other_projects:
            other_parts = [f"{s} ({c})" for s, c in other_projects.items()]
            parts.append(
                f"Other projects with pending handoffs: {', '.join(other_parts)}"
            )

        message = "\n".join(parts)

        if mode == "passive":
            message = f"[Handoff info available if asked]\n{message}"

    return {
        "current_project": slug,
        "current_pending": current_pending,
        "other_projects": other_projects,
        "drafts_count": drafts_count,
        "notification_mode": mode,
        "message": message,
    }


def main():
    try:
        hook_input = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, ValueError):
        hook_input = {}

    cwd = hook_input.get("cwd", ".")

    try:
        result = scan(cwd)
        if result["message"]:
            print(result["message"])
    except Exception:
        pass

    sys.exit(0)


if __name__ == "__main__":
    main()
