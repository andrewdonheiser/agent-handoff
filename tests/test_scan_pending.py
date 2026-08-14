"""Tests for handoff.scan_pending module."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from handoff import scan_pending, storage


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    handoffs_dir = tmp_path / "handoffs"
    config_path = tmp_path / "agent-handoff.json"
    monkeypatch.setattr(storage, "_HANDOFFS_DIR", handoffs_dir)
    monkeypatch.setattr(storage, "_CONFIG_PATH", config_path)


def _mock_slug(slug="test/project"):
    """Patch get_project_slug to return a fixed slug."""
    return patch("handoff.scan_pending.get_project_slug", return_value=slug)


# ── no pending handoffs ──


def test_scan_empty():
    with _mock_slug():
        result = scan_pending.scan("/some/path")
    assert result["current_pending"] == []
    assert result["other_projects"] == {}
    assert result["drafts_count"] == 0
    assert result["message"] == ""


# ── pending handoffs for current project ──


def test_scan_with_pending():
    slug = "test/project"
    storage.save_handoff(slug, "content 1", "fix-a")
    storage.save_handoff(slug, "content 2", "fix-b")

    with _mock_slug(slug):
        result = scan_pending.scan("/some/path")

    assert len(result["current_pending"]) == 2
    assert "2 pending handoffs" in result["message"]
    assert "/agent-handoff --load" in result["message"]


def test_scan_with_single_pending():
    slug = "test/project"
    storage.save_handoff(slug, "content", "fix")

    with _mock_slug(slug):
        result = scan_pending.scan("/some/path")

    assert "1 pending handoff " in result["message"]
    assert "handoffs" not in result["message"].split("\n")[0]  # singular


# ── cross-project awareness ──


def test_scan_with_other_projects():
    storage.save_handoff("other/project", "content", "thing")

    with _mock_slug("test/project"):
        result = scan_pending.scan("/some/path")

    assert "other/project" in result["other_projects"]
    assert result["other_projects"]["other/project"] == 1
    assert "Other projects" in result["message"]


# ── drafts ──


def test_scan_with_drafts():
    slug = "test/project"
    drafts_dir = storage._drafts_dir(slug)
    drafts_dir.mkdir(parents=True, exist_ok=True)
    (drafts_dir / "20260813-session1.md").write_text("draft content")
    (drafts_dir / "20260813-session2.md").write_text("draft content")

    with _mock_slug(slug):
        result = scan_pending.scan("/some/path")

    assert result["drafts_count"] == 2
    assert "2 session drafts" in result["message"]


# ── draft promotion (auto_handoff) ──


def test_scan_does_not_promote_drafts_when_auto_handoff_off():
    slug = "test/project"
    drafts_dir = storage._drafts_dir(slug)
    drafts_dir.mkdir(parents=True, exist_ok=True)
    (drafts_dir / "20260813-session.md").write_text("draft content")

    with _mock_slug(slug):
        result = scan_pending.scan("/some/path")

    # Default config: auto_handoff off -> draft stays a draft.
    assert result["drafts_count"] == 1
    assert result["current_pending"] == []


def test_scan_promotes_drafts_when_auto_handoff_on(tmp_path, monkeypatch):
    config_path = tmp_path / "agent-handoff.json"
    monkeypatch.setattr(storage, "_CONFIG_PATH", config_path)
    import json
    config_path.write_text(json.dumps({"auto_handoff": True}))

    slug = "test/project"
    drafts_dir = storage._drafts_dir(slug)
    drafts_dir.mkdir(parents=True, exist_ok=True)
    (drafts_dir / "20260813-session.md").write_text("draft content")

    with _mock_slug(slug):
        result = scan_pending.scan("/some/path")

    # Draft was promoted: now a loadable pending handoff, no drafts left.
    assert result["drafts_count"] == 0
    assert len(result["current_pending"]) == 1
    assert "pending handoff" in result["message"]
    assert "session draft" not in result["message"]


# ── notification modes ──


def test_scan_quiet_mode(tmp_path, monkeypatch):
    config_path = tmp_path / "agent-handoff.json"
    monkeypatch.setattr(storage, "_CONFIG_PATH", config_path)
    import json
    config_path.write_text(json.dumps({"notification": "quiet"}))

    slug = "test/project"
    storage.save_handoff(slug, "content", "fix")

    with _mock_slug(slug):
        result = scan_pending.scan("/some/path")

    assert result["message"] == ""
    assert result["notification_mode"] == "quiet"
    assert len(result["current_pending"]) == 1


def test_scan_passive_mode(tmp_path, monkeypatch):
    config_path = tmp_path / "agent-handoff.json"
    monkeypatch.setattr(storage, "_CONFIG_PATH", config_path)
    import json
    config_path.write_text(json.dumps({"notification": "passive"}))

    slug = "test/project"
    storage.save_handoff(slug, "content", "fix")

    with _mock_slug(slug):
        result = scan_pending.scan("/some/path")

    assert result["message"].startswith("[Handoff info available if asked]")
    assert result["notification_mode"] == "passive"


def test_scan_proactive_mode_is_default():
    slug = "test/project"
    storage.save_handoff(slug, "content", "fix")

    with _mock_slug(slug):
        result = scan_pending.scan("/some/path")

    assert result["notification_mode"] == "proactive"
    assert "[Handoff info available if asked]" not in result["message"]
    assert "pending handoff" in result["message"]


# ── combined scenarios ──


def test_scan_pending_and_drafts_and_other():
    slug = "test/project"
    storage.save_handoff(slug, "content", "fix")
    storage.save_handoff("other/repo", "content", "other-fix")

    drafts_dir = storage._drafts_dir(slug)
    drafts_dir.mkdir(parents=True, exist_ok=True)
    (drafts_dir / "20260813-session.md").write_text("draft")

    with _mock_slug(slug):
        result = scan_pending.scan("/some/path")

    assert len(result["current_pending"]) == 1
    assert result["drafts_count"] == 1
    assert "other/repo" in result["other_projects"]
    lines = result["message"].split("\n")
    assert len(lines) == 3
