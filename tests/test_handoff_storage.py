"""Tests for handoff.storage module."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from handoff import storage


# ── fixtures ──


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    """Redirect all storage paths to tmp_path so tests don't touch the real filesystem."""
    handoffs_dir = tmp_path / "handoffs"
    config_path = tmp_path / "agent-handoff.json"
    monkeypatch.setattr(storage, "_HANDOFFS_DIR", handoffs_dir)
    monkeypatch.setattr(storage, "_CONFIG_PATH", config_path)


# ── load_config ──


def test_load_config_defaults():
    cfg = storage.load_config()
    assert cfg == storage._DEFAULT_CONFIG
    assert cfg["notification"] == "proactive"
    assert cfg["auto_handoff"] is False


def test_load_config_from_file(tmp_path, monkeypatch):
    config_path = tmp_path / "agent-handoff.json"
    monkeypatch.setattr(storage, "_CONFIG_PATH", config_path)
    config_path.write_text(json.dumps({"notification": "quiet", "max_handoffs": 3}))
    cfg = storage.load_config()
    assert cfg["notification"] == "quiet"
    assert cfg["max_handoffs"] == 3
    # Defaults preserved for missing keys
    assert cfg["auto_handoff"] is False
    assert cfg["max_consumed"] == 10


def test_load_config_malformed_json(tmp_path, monkeypatch):
    config_path = tmp_path / "agent-handoff.json"
    monkeypatch.setattr(storage, "_CONFIG_PATH", config_path)
    config_path.write_text("not json {{{")
    cfg = storage.load_config()
    assert cfg == storage._DEFAULT_CONFIG


def test_save_config(tmp_path, monkeypatch):
    config_path = tmp_path / "agent-handoff.json"
    monkeypatch.setattr(storage, "_CONFIG_PATH", config_path)
    storage.save_config({"notification": "passive"})
    assert config_path.exists()
    loaded = json.loads(config_path.read_text())
    assert loaded["notification"] == "passive"


# ── get_project_slug ──


def test_slug_from_https_url():
    assert storage._slug_from_url("https://github.com/myorg/my-repo.git") == "myorg/my-repo"


def test_slug_from_ssh_url():
    assert storage._slug_from_url("git@github.com:myorg/my-repo.git") == "myorg/my-repo"


def test_slug_from_url_no_git_suffix():
    assert storage._slug_from_url("https://github.com/org/repo") == "org/repo"


def test_slug_from_url_trailing_slash():
    assert storage._slug_from_url("https://github.com/org/repo/") == "org/repo"


def test_slugify_special_chars():
    assert storage._slugify("My Cool_Project!") == "my-cool-project"


def test_slugify_preserves_dots_and_slashes():
    assert storage._slugify("org/my.project") == "org/my.project"


def test_get_project_slug_from_git(tmp_path):
    """When git remote origin exists, use it."""
    fake_result = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="https://github.com/testorg/testrepo.git\n"
    )
    with patch("handoff.storage.subprocess.run", return_value=fake_result):
        slug = storage.get_project_slug(str(tmp_path))
    assert slug == "testorg/testrepo"


def test_get_project_slug_fallback_to_dirname(tmp_path):
    """When git fails, fall back to directory name."""
    fake_result = subprocess.CompletedProcess(
        args=[], returncode=128, stdout="", stderr="fatal: not a git repository"
    )
    with patch("handoff.storage.subprocess.run", return_value=fake_result):
        slug = storage.get_project_slug(str(tmp_path / "my-project"))
    assert slug == "my-project"


def test_get_project_slug_git_timeout(tmp_path):
    """When git times out, fall back to directory name."""
    with patch("handoff.storage.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="git", timeout=5)):
        slug = storage.get_project_slug(str(tmp_path / "fallback-dir"))
    assert slug == "fallback-dir"


# ── save / list / load / archive ──


def test_save_and_list_handoff():
    slug = "test/project"
    content = "# Handoff\nSome content"
    filename = storage.save_handoff(slug, content, "auth-refactor")

    assert filename.startswith("2")  # starts with date
    assert "auth-refactor" in filename

    pending = storage.list_pending(slug)
    assert filename in pending
    assert len(pending) == 1


def test_save_avoids_collision():
    slug = "test/project"
    f1 = storage.save_handoff(slug, "content1", "fix")
    f2 = storage.save_handoff(slug, "content2", "fix")
    assert f1 != f2
    assert len(storage.list_pending(slug)) == 2


def test_load_handoff():
    slug = "test/project"
    content = "# Test Handoff\nDetailed content here"
    filename = storage.save_handoff(slug, content, "test")
    loaded = storage.load_handoff(slug, filename)
    assert loaded == content


def test_archive_handoff():
    slug = "test/project"
    filename = storage.save_handoff(slug, "content", "archive-test")
    assert len(storage.list_pending(slug)) == 1

    storage.archive_handoff(slug, filename)
    assert len(storage.list_pending(slug)) == 0
    assert len(storage.list_consumed(slug)) == 1


def test_archive_nonexistent_is_noop():
    storage.archive_handoff("test/project", "nonexistent.md")


def test_list_pending_empty_slug():
    assert storage.list_pending("nonexistent/slug") == []


def test_list_pending_excludes_subdirs():
    """consumed/ and drafts/ dirs should not appear in pending list."""
    slug = "test/project"
    storage.save_handoff(slug, "content", "test")
    pending = storage.list_pending(slug)
    assert all(f.endswith(".md") for f in pending)
    assert "consumed" not in pending
    assert "drafts" not in pending


# ── retention ──


def test_cleanup_retention_pending():
    slug = "test/project"
    config = {"max_handoffs": 2, "max_consumed": 10}

    # Create 4 handoffs
    for i in range(4):
        storage.save_handoff(slug, f"content {i}", f"item-{i}")

    assert len(storage.list_pending(slug)) == 4
    storage.cleanup_retention(slug, config)
    assert len(storage.list_pending(slug)) == 2


def test_cleanup_retention_consumed():
    slug = "test/project"
    config = {"max_handoffs": 10, "max_consumed": 2}

    filenames = []
    for i in range(4):
        f = storage.save_handoff(slug, f"content {i}", f"item-{i}")
        filenames.append(f)

    for f in filenames:
        storage.archive_handoff(slug, f)

    assert len(storage.list_consumed(slug)) == 4
    storage.cleanup_retention(slug, config)
    assert len(storage.list_consumed(slug)) == 2


def test_cleanup_retention_unlimited_consumed():
    slug = "test/project"
    config = {"max_handoffs": 10, "max_consumed": -1}

    filenames = []
    for i in range(10):
        f = storage.save_handoff(slug, f"content {i}", f"item-{i}")
        filenames.append(f)

    for f in filenames:
        storage.archive_handoff(slug, f)

    storage.cleanup_retention(slug, config)
    assert len(storage.list_consumed(slug)) == 10


def test_cleanup_retention_at_limit():
    slug = "test/project"
    config = {"max_handoffs": 3, "max_consumed": 10}

    for i in range(3):
        storage.save_handoff(slug, f"content {i}", f"item-{i}")

    storage.cleanup_retention(slug, config)
    assert len(storage.list_pending(slug)) == 3


def test_cleanup_retention_uses_default_config():
    slug = "test/project"
    for i in range(7):
        storage.save_handoff(slug, f"content {i}", f"item-{i}")

    storage.cleanup_retention(slug)
    assert len(storage.list_pending(slug)) == 5  # default max_handoffs


# ── list_all_project_slugs ──


def test_list_all_project_slugs():
    storage.save_handoff("project-a", "content", "test")
    storage.save_handoff("project-b", "content", "test")

    slugs = storage.list_all_project_slugs()
    assert "project-a" in slugs
    assert "project-b" in slugs


def test_list_all_project_slugs_empty():
    assert storage.list_all_project_slugs() == []
