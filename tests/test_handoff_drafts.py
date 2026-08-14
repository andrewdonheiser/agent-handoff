"""Tests for handoff.drafts module."""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from handoff import drafts, storage


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    handoffs_dir = tmp_path / "handoffs"
    config_path = tmp_path / "agent-handoff.json"
    monkeypatch.setattr(storage, "_HANDOFFS_DIR", handoffs_dir)
    monkeypatch.setattr(storage, "_CONFIG_PATH", config_path)


def _enable_auto_handoff(tmp_path, monkeypatch):
    config_path = tmp_path / "agent-handoff.json"
    monkeypatch.setattr(storage, "_CONFIG_PATH", config_path)
    config_path.write_text(json.dumps({"auto_handoff": True}))


# ── should_create_draft ──


def test_should_create_draft_disabled_by_default():
    assert drafts.should_create_draft("test/proj", "session-abc") is False


def test_should_create_draft_enabled(tmp_path, monkeypatch):
    _enable_auto_handoff(tmp_path, monkeypatch)
    assert drafts.should_create_draft("test/proj", "session-abc") is True


def test_should_create_draft_already_exists(tmp_path, monkeypatch):
    _enable_auto_handoff(tmp_path, monkeypatch)
    slug = "test/proj"
    drafts.save_draft(slug, "session-abc", "some summary")
    assert drafts.should_create_draft(slug, "session-abc") is False


def test_should_create_draft_different_session(tmp_path, monkeypatch):
    _enable_auto_handoff(tmp_path, monkeypatch)
    slug = "test/proj"
    drafts.save_draft(slug, "session-abc", "some summary")
    assert drafts.should_create_draft(slug, "session-xyz") is True


# ── save_draft ──


def test_save_draft():
    slug = "test/proj"
    storage._ensure_dirs(slug)
    filename = drafts.save_draft(slug, "session-12345678-abcd", "Progress summary")
    assert filename.endswith(".md")
    assert "session-12345678-abcd" in filename

    content = drafts.load_draft(slug, filename)
    assert "auto: true" in content
    assert "session: session-12345678-abcd" in content
    assert "Progress summary" in content


def test_save_draft_listed():
    slug = "test/proj"
    drafts.save_draft(slug, "session-abc", "summary")
    listed = drafts.list_drafts(slug)
    assert len(listed) == 1


# ── list_drafts ──


def test_list_drafts_empty():
    assert drafts.list_drafts("nonexistent/proj") == []


# ── fold_drafts ──


def test_fold_drafts_none_when_empty():
    assert drafts.fold_drafts("nonexistent/proj") is None


def test_fold_drafts_combines():
    slug = "test/proj"
    drafts.save_draft(slug, "session-aaa", "First progress")
    drafts.save_draft(slug, "session-bbb", "Second progress")

    folded = drafts.fold_drafts(slug)
    assert folded is not None
    assert "First progress" in folded
    assert "Second progress" in folded
    assert "### Draft:" in folded


# ── promote_drafts ──


def test_promote_drafts_empty():
    assert drafts.promote_drafts("nonexistent/proj") == []


def test_promote_drafts_moves_to_pending():
    slug = "test/proj"
    drafts.save_draft(slug, "session-aaa", "summary")
    assert len(drafts.list_drafts(slug)) == 1

    promoted = drafts.promote_drafts(slug)

    assert len(promoted) == 1
    # Draft is gone, and it now shows up as a pending handoff.
    assert drafts.list_drafts(slug) == []
    assert promoted[0] in storage.list_pending(slug)


def test_promote_drafts_collision_suffix():
    slug = "test/proj"
    filename = drafts.save_draft(slug, "session-aaa", "summary")
    # A pending handoff already occupies the draft's target name.
    (storage._project_dir(slug) / filename).write_text("existing pending")

    promoted = drafts.promote_drafts(slug)

    assert len(promoted) == 1
    assert promoted[0] != filename
    assert promoted[0].endswith("-2.md")
    # Both the pre-existing and the promoted file are now pending.
    pending = storage.list_pending(slug)
    assert filename in pending
    assert promoted[0] in pending


# ── clear_drafts ──


def test_clear_drafts():
    slug = "test/proj"
    drafts.save_draft(slug, "session-aaa", "summary")
    drafts.save_draft(slug, "session-bbb", "summary")
    assert len(drafts.list_drafts(slug)) == 2

    count = drafts.clear_drafts(slug)
    assert count == 2
    assert drafts.list_drafts(slug) == []


def test_clear_drafts_empty():
    assert drafts.clear_drafts("nonexistent/proj") == 0


# ── cleanup_drafts ──


def test_cleanup_drafts_removes_stale():
    slug = "test/proj"
    storage._ensure_dirs(slug)
    d = storage._drafts_dir(slug)

    # Create a draft with an old date prefix
    old_date = (date.today() - timedelta(days=5)).strftime("%Y%m%d")
    (d / f"{old_date}-old-session.md").write_text("old draft")

    # Create a fresh draft
    drafts.save_draft(slug, "fresh-session", "fresh summary")

    drafts.cleanup_drafts(slug)
    remaining = drafts.list_drafts(slug)
    assert len(remaining) == 1
    assert "old-session" not in remaining[0]


def test_cleanup_drafts_enforces_cap():
    slug = "test/proj"
    for i in range(5):
        drafts.save_draft(slug, f"session-{i:03d}", f"summary {i}")

    assert len(drafts.list_drafts(slug)) <= drafts._MAX_DRAFTS_PER_PROJECT


def test_cleanup_drafts_noop_on_empty():
    drafts.cleanup_drafts("nonexistent/proj")
