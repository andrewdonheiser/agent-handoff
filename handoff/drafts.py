"""Auto-draft snapshot management for handoff sessions.

Drafts are lightweight mid-session snapshots stored in
~/.claude/handoffs/<slug>/drafts/. They are never auto-promoted —
users must explicitly load or fold them via the skill.
"""

from __future__ import annotations

import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from handoff.storage import _drafts_dir, _ensure_dirs, _project_dir, load_config

_MAX_DRAFTS_PER_PROJECT = 3
_DRAFT_STALE_DAYS = 2


def should_create_draft(slug: str, session_id: str) -> bool:
    config = load_config()
    if not config.get("auto_handoff", False):
        return False

    d = _drafts_dir(slug)
    if not d.exists():
        return True

    for f in d.iterdir():
        if session_id in f.name:
            return False

    return True


def save_draft(slug: str, session_id: str, summary: str) -> str:
    _ensure_dirs(slug)
    today = date.today().strftime("%Y%m%d")
    safe_id = session_id.replace("/", "-")
    filename = f"{today}-{safe_id}.md"

    content = f"auto: true\nsession: {session_id}\n\n{summary}"

    dest = _drafts_dir(slug) / filename
    dest.write_text(content)

    cleanup_drafts(slug)
    return filename


def list_drafts(slug: str) -> list[str]:
    d = _drafts_dir(slug)
    if not d.exists():
        return []
    return sorted(f.name for f in d.iterdir() if f.is_file() and f.suffix == ".md")


def load_draft(slug: str, filename: str) -> str:
    return (_drafts_dir(slug) / filename).read_text()


def fold_drafts(slug: str) -> str | None:
    """Read and concatenate all draft content for folding into a final handoff.

    Returns combined draft text, or None if no drafts exist.
    Does NOT delete drafts — caller should clean up after successful handoff.
    """
    drafts = list_drafts(slug)
    if not drafts:
        return None

    parts = []
    for filename in drafts:
        content = load_draft(slug, filename)
        parts.append(f"### Draft: {filename}\n{content}")

    return "\n\n".join(parts)


def promote_drafts(slug: str) -> list[str]:
    """Move draft snapshots into the pending handoff list.

    Called at session start (when auto_handoff is enabled) so drafts from a
    session that ended without an explicit handoff become loadable pending
    handoffs, picked up by the normal load flow. Returns the list of promoted
    filenames (final names after collision handling). Mirrors the collision
    suffixing used by storage.save_handoff (first clash gets ``-2``).
    """
    draft_files = list_drafts(slug)
    if not draft_files:
        return []

    src_dir = _drafts_dir(slug)
    dest_dir = _project_dir(slug)
    promoted = []
    for filename in draft_files:
        dest = dest_dir / filename
        stem = filename[:-3] if filename.endswith(".md") else filename
        counter = 1
        while dest.exists():
            counter += 1
            dest = dest_dir / f"{stem}-{counter}.md"
        shutil.move(str(src_dir / filename), str(dest))
        promoted.append(dest.name)
    return promoted


def clear_drafts(slug: str) -> int:
    """Remove all drafts for a project. Returns count removed."""
    drafts = list_drafts(slug)
    d = _drafts_dir(slug)
    for filename in drafts:
        (d / filename).unlink(missing_ok=True)
    return len(drafts)


def cleanup_drafts(slug: str) -> None:
    """Remove stale drafts and enforce per-project cap."""
    d = _drafts_dir(slug)
    if not d.exists():
        return

    cutoff = date.today() - timedelta(days=_DRAFT_STALE_DAYS)
    cutoff_str = cutoff.strftime("%Y%m%d")

    files = sorted(f for f in d.iterdir() if f.is_file() and f.suffix == ".md")

    # Remove stale drafts (date prefix older than cutoff)
    remaining = []
    for f in files:
        date_prefix = f.name[:8]
        if date_prefix.isdigit() and date_prefix < cutoff_str:
            f.unlink(missing_ok=True)
        else:
            remaining.append(f)

    # Enforce cap (keep newest)
    if len(remaining) > _MAX_DRAFTS_PER_PROJECT:
        to_remove = remaining[: len(remaining) - _MAX_DRAFTS_PER_PROJECT]
        for f in to_remove:
            f.unlink(missing_ok=True)
