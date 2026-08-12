"""Tests for price_check.parsing — shared JSONL parsing utilities."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from price_check.parsing import (
    _is_system_prompt,
    _SYSTEM_PREFIXES,
    discover_subagent_files,
    iter_session_records,
)


def _write_jsonl(path: Path, records: list[dict]):
    with path.open("w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def _usage_record(req_id: str, pid: str, model: str = "claude-sonnet-4-20250514",
                  input_tokens: int = 100, output_tokens: int = 50, **extra):
    obj = {
        "requestId": req_id,
        "promptId": pid,
        "message": {
            "role": "assistant",
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
        },
    }
    obj.update(extra)
    return obj


class TestIsSystemPrompt:
    def test_system_reminder_string(self):
        obj = {"message": {"content": "<system-reminder>hello</system-reminder>"}}
        assert _is_system_prompt(obj) is True

    def test_task_notification_string(self):
        obj = {"message": {"content": "<task-notification>done</task-notification>"}}
        assert _is_system_prompt(obj) is True

    def test_command_message_string(self):
        obj = {"message": {"content": "<command-message>run</command-message>"}}
        assert _is_system_prompt(obj) is True

    def test_normal_string_not_system(self):
        obj = {"message": {"content": "Hello, how can I help?"}}
        assert _is_system_prompt(obj) is False

    def test_list_content_marker_in_first_block(self):
        obj = {"message": {"content": [
            {"type": "text", "text": "<system-reminder>stuff</system-reminder>"},
        ]}}
        assert _is_system_prompt(obj) is True

    def test_list_content_marker_in_non_first_block(self):
        obj = {"message": {"content": [
            {"type": "text", "text": "normal text"},
            {"type": "text", "text": "<system-reminder>stuff</system-reminder>"},
        ]}}
        assert _is_system_prompt(obj) is True

    def test_list_content_no_system(self):
        obj = {"message": {"content": [
            {"type": "text", "text": "just a normal message"},
        ]}}
        assert _is_system_prompt(obj) is False

    def test_whitespace_before_prefix(self):
        obj = {"message": {"content": "  <system-reminder>stuff"}}
        assert _is_system_prompt(obj) is True

    def test_empty_content(self):
        obj = {"message": {"content": ""}}
        assert _is_system_prompt(obj) is False

    def test_missing_message(self):
        assert _is_system_prompt({}) is False


class TestDiscoverSubagentFiles:
    def test_finds_subagent_files(self, tmp_path):
        session = tmp_path / "session.jsonl"
        session.touch()
        sub_dir = tmp_path / "session" / "subagents"
        sub_dir.mkdir(parents=True)
        (sub_dir / "agent-abc.jsonl").touch()
        (sub_dir / "agent-def.jsonl").touch()
        (sub_dir / "not-an-agent.jsonl").touch()

        result = discover_subagent_files(session)
        names = sorted(p.name for p in result)
        assert names == ["agent-abc.jsonl", "agent-def.jsonl"]

    def test_missing_subagent_dir(self, tmp_path):
        session = tmp_path / "session.jsonl"
        session.touch()
        assert discover_subagent_files(session) == []

    def test_nested_subagent_files(self, tmp_path):
        session = tmp_path / "session.jsonl"
        session.touch()
        nested = tmp_path / "session" / "subagents" / "deep"
        nested.mkdir(parents=True)
        (nested / "agent-nested.jsonl").touch()

        result = discover_subagent_files(session)
        assert len(result) == 1
        assert result[0].name == "agent-nested.jsonl"


class TestIterSessionRecords:
    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.jsonl"
        f.write_text("")
        assert list(iter_session_records(f)) == []

    def test_missing_file(self, tmp_path):
        f = tmp_path / "missing.jsonl"
        assert list(iter_session_records(f)) == []

    def test_corrupt_lines_skipped(self, tmp_path):
        f = tmp_path / "data.jsonl"
        f.write_text("not json\n{\"promptId\": \"p1\"}\n")
        records = list(iter_session_records(f, include_subagents=False))
        assert len(records) == 1
        assert records[0]["_parsed_prompt_id"] == "p1"

    def test_system_prompt_flagged(self, tmp_path):
        f = tmp_path / "data.jsonl"
        records = [
            {"promptId": "p1", "message": {"content": "<system-reminder>hi"}},
            {"promptId": "p1", "message": {"content": "followup same pid"}},
            {"promptId": "p2", "message": {"content": "user msg"}},
        ]
        _write_jsonl(f, records)
        result = list(iter_session_records(f, include_subagents=False))
        assert result[0]["_parsed_is_system"] is True
        assert result[1]["_parsed_is_system"] is True
        assert result[2]["_parsed_is_system"] is False

    def test_fast_path_skips_irrelevant_lines(self, tmp_path):
        f = tmp_path / "data.jsonl"
        records = [
            {"message": {"role": "user", "content": "hello"}},  # no promptId, no usage
            _usage_record("r1", "p1"),
        ]
        _write_jsonl(f, records)

        all_recs = list(iter_session_records(f, include_subagents=False, fast_path=False))
        fast_recs = list(iter_session_records(f, include_subagents=False, fast_path=True))

        assert len(all_recs) == 2
        assert len(fast_recs) == 1

    def test_source_tagging_main(self, tmp_path):
        f = tmp_path / "session.jsonl"
        _write_jsonl(f, [_usage_record("r1", "p1")])
        result = list(iter_session_records(f, include_subagents=False))
        assert result[0]["_parsed_source"] == "main"

    def test_source_tagging_subagent(self, tmp_path):
        f = tmp_path / "session.jsonl"
        _write_jsonl(f, [_usage_record("r1", "p1")])

        sub_dir = tmp_path / "session" / "subagents"
        sub_dir.mkdir(parents=True)
        sf = sub_dir / "agent-x.jsonl"
        _write_jsonl(sf, [_usage_record("r2", "p1", attributionAgent="explorer")])

        result = list(iter_session_records(f, include_subagents=True))
        assert result[0]["_parsed_source"] == "main"
        assert result[1]["_parsed_source"] == "subagent"
        assert result[1]["_parsed_attribution_agent"] == "explorer"

    def test_include_subagents_false(self, tmp_path):
        f = tmp_path / "session.jsonl"
        _write_jsonl(f, [_usage_record("r1", "p1")])

        sub_dir = tmp_path / "session" / "subagents"
        sub_dir.mkdir(parents=True)
        sf = sub_dir / "agent-x.jsonl"
        _write_jsonl(sf, [_usage_record("r2", "p1")])

        result = list(iter_session_records(f, include_subagents=False))
        assert len(result) == 1
        assert result[0]["_parsed_source"] == "main"
