"""Tests for handoff.cli module."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from handoff import cli, storage


@pytest.fixture(autouse=True)
def _isolate_paths(tmp_path, monkeypatch):
    handoffs_dir = tmp_path / "handoffs"
    config_path = tmp_path / "agent-handoff.json"
    monkeypatch.setattr(storage, "_HANDOFFS_DIR", handoffs_dir)
    monkeypatch.setattr(storage, "_CONFIG_PATH", config_path)


def _run_cli(*args, stdin_text=""):
    """Run cli.main() with the given args, capturing stdout."""
    import io
    from contextlib import redirect_stdout

    old_argv = sys.argv
    old_stdin = sys.stdin
    try:
        sys.argv = ["handoff-cli"] + list(args)
        sys.stdin = io.StringIO(stdin_text)
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main()
        return buf.getvalue()
    finally:
        sys.argv = old_argv
        sys.stdin = old_stdin


def test_slug_command(tmp_path):
    fake_result = subprocess.CompletedProcess(
        args=[], returncode=0, stdout="https://github.com/testorg/testrepo.git\n",
    )
    with patch("handoff.storage.subprocess.run", return_value=fake_result):
        output = _run_cli("slug", "--cwd", str(tmp_path))
    assert output.strip() == "testorg/testrepo"


def test_save_and_list():
    slug = "test/project"
    output = _run_cli("save", "--slug", slug, "--semantic", "auth-fix",
                       stdin_text="# Handoff\nContent here")
    result = json.loads(output)
    assert result["slug"] == slug
    assert "auth-fix" in result["filename"]

    output = _run_cli("list", "--slug", slug)
    result = json.loads(output)
    assert len(result["pending"]) == 1
    assert result["pending"][0] == result["slug"] or "auth-fix" in result["pending"][0]


def test_save_runs_cleanup():
    slug = "test/project"
    config_path = storage._CONFIG_PATH
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"max_handoffs": 2}))

    for i in range(4):
        _run_cli("save", "--slug", slug, "--semantic", f"item-{i}",
                 stdin_text=f"content {i}")

    output = _run_cli("list", "--slug", slug)
    result = json.loads(output)
    assert len(result["pending"]) == 2


def test_load_command():
    slug = "test/project"
    content = "# Full handoff content\nWith details"
    save_out = _run_cli("save", "--slug", slug, "--semantic", "test",
                         stdin_text=content)
    filename = json.loads(save_out)["filename"]

    output = _run_cli("load", "--slug", slug, "--file", filename)
    assert output.rstrip("\n") == content


def test_archive_command():
    slug = "test/project"
    save_out = _run_cli("save", "--slug", slug, "--semantic", "test",
                         stdin_text="content")
    filename = json.loads(save_out)["filename"]

    output = _run_cli("archive", "--slug", slug, "--file", filename)
    result = json.loads(output)
    assert result["archived"] == filename

    list_out = _run_cli("list", "--slug", slug)
    assert len(json.loads(list_out)["pending"]) == 0
