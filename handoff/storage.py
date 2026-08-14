"""Handoff document persistence, config, and retention management."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

_HANDOFFS_DIR = Path.home() / ".claude" / "handoffs"
_CONFIG_PATH = Path.home() / ".claude" / "agent-handoff.json"

_DEFAULT_CONFIG = {
    "notification": "proactive",
    "auto_handoff": False,
    "max_handoffs": 5,
    "max_consumed": 10,
}


def get_handoffs_dir() -> Path:
    return _HANDOFFS_DIR


def load_config() -> dict:
    if _CONFIG_PATH.exists():
        try:
            cfg = json.loads(_CONFIG_PATH.read_text())
            merged = dict(_DEFAULT_CONFIG)
            merged.update(cfg)
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")


def get_project_slug(cwd: str) -> str:
    """Derive a project slug from git remote or directory name.

    Tries git remote origin URL first, extracting org/repo or last path
    segment. Falls back to the directory basename.
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5, cwd=cwd,
        )
        if result.returncode == 0:
            url = result.stdout.strip()
            slug = _slug_from_url(url)
            if slug:
                return slug
    except (OSError, subprocess.TimeoutExpired):
        pass

    return _slugify(Path(cwd).name)


def _slug_from_url(url: str) -> str | None:
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]

    # SSH: git@github.com:org/repo
    m = re.match(r".*[:/]([^/]+/[^/]+)$", url)
    if m:
        return _slugify(m.group(1))

    # HTTPS: https://github.com/org/repo
    parts = url.split("/")
    if len(parts) >= 2:
        return _slugify(f"{parts[-2]}/{parts[-1]}")

    return None


def _slugify(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"[^a-z0-9/.-]+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s.strip("-")


def _project_dir(slug: str) -> Path:
    return _HANDOFFS_DIR / slug


def _consumed_dir(slug: str) -> Path:
    return _project_dir(slug) / "consumed"


def _drafts_dir(slug: str) -> Path:
    return _project_dir(slug) / "drafts"


def _ensure_dirs(slug: str) -> None:
    _project_dir(slug).mkdir(parents=True, exist_ok=True)
    _consumed_dir(slug).mkdir(exist_ok=True)
    _drafts_dir(slug).mkdir(exist_ok=True)


def list_pending(slug: str) -> list[str]:
    d = _project_dir(slug)
    if not d.exists():
        return []
    skip = {"consumed", "drafts"}
    files = []
    for f in sorted(d.iterdir()):
        if f.is_file() and f.suffix == ".md" and f.name not in skip:
            files.append(f.name)
    return files


def list_consumed(slug: str) -> list[str]:
    d = _consumed_dir(slug)
    if not d.exists():
        return []
    return sorted(f.name for f in d.iterdir() if f.is_file() and f.suffix == ".md")


def save_handoff(slug: str, content: str, semantic_slug: str = "handoff") -> str:
    _ensure_dirs(slug)
    today = date.today().strftime("%Y%m%d")
    filename = f"{today}-{_slugify(semantic_slug)}.md"

    # Avoid collisions
    dest = _project_dir(slug) / filename
    counter = 1
    while dest.exists():
        counter += 1
        filename = f"{today}-{_slugify(semantic_slug)}-{counter}.md"
        dest = _project_dir(slug) / filename

    dest.write_text(content)
    return filename


def load_handoff(slug: str, filename: str) -> str:
    path = _project_dir(slug) / filename
    return path.read_text()


def archive_handoff(slug: str, filename: str) -> None:
    src = _project_dir(slug) / filename
    if not src.exists():
        return
    _consumed_dir(slug).mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(_consumed_dir(slug) / filename))


def cleanup_retention(slug: str, config: dict | None = None) -> None:
    if config is None:
        config = load_config()

    max_handoffs = config.get("max_handoffs", 5)
    max_consumed = config.get("max_consumed", 10)

    # Prune pending handoffs (keep newest)
    pending = list_pending(slug)
    if max_handoffs >= 0 and len(pending) > max_handoffs:
        to_remove = pending[: len(pending) - max_handoffs]
        for f in to_remove:
            (_project_dir(slug) / f).unlink(missing_ok=True)

    # Prune consumed handoffs (keep newest, -1 = unlimited)
    if max_consumed >= 0:
        consumed = list_consumed(slug)
        if len(consumed) > max_consumed:
            to_remove = consumed[: len(consumed) - max_consumed]
            for f in to_remove:
                (_consumed_dir(slug) / f).unlink(missing_ok=True)


def list_all_project_slugs() -> list[str]:
    """List all project slugs that have handoff directories.

    Handles nested slugs (e.g., "org/repo") by walking the directory tree
    and identifying leaf project dirs (those containing .md files or
    consumed/drafts subdirs).
    """
    if not _HANDOFFS_DIR.exists():
        return []

    slugs = []
    for root, dirs, files in _HANDOFFS_DIR.walk():
        # Skip consumed/ and drafts/ — they're internal to a project dir
        dirs[:] = [d for d in dirs if d not in ("consumed", "drafts") and not d.startswith(".")]

        has_md = any(f.endswith(".md") for f in files)
        has_consumed = (_HANDOFFS_DIR / root.relative_to(_HANDOFFS_DIR) / "consumed").is_dir()
        has_drafts = (_HANDOFFS_DIR / root.relative_to(_HANDOFFS_DIR) / "drafts").is_dir()

        if has_md or has_consumed or has_drafts:
            slug = str(root.relative_to(_HANDOFFS_DIR))
            if slug != ".":
                slugs.append(slug)

    return sorted(slugs)
