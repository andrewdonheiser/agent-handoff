"""Tests for scan_per_turn — per-model cost and subagent inclusion."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from price_check import main
from scripts.analyze_session import scan_per_turn

# ── helpers ──────────────────────────────────────────────────────────

FAKE_PRICING = {
    "claude-opus-4-6": {
        "input": 15.0, "output": 75.0,
        "cache_read": 1.5, "cache_write": 18.75,
        "label": "Opus 4.6",
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.8, "output": 4.0,
        "cache_read": 0.08, "cache_write": 1.0,
        "label": "Haiku 4.5",
    },
}


def _usage_line(
    req_id: str,
    model: str = "claude-opus-4-6",
    prompt_id: str = "p1",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read: int = 0,
    cache_write: int = 0,
) -> str:
    return json.dumps({
        "requestId": req_id,
        "promptId": prompt_id,
        "message": {
            "model": model,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_write,
            },
        },
    })


def _prompt_id_line(prompt_id: str, content: str = "user text") -> str:
    return json.dumps({"promptId": prompt_id, "message": {"content": content}})


def _write_jsonl(path: Path, lines: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")


def _setup_with_subagents(tmp_path, main_lines, subagent_specs=None):
    jsonl = tmp_path / "session.jsonl"
    _write_jsonl(jsonl, main_lines)
    if subagent_specs:
        subdir = tmp_path / "session" / "subagents"
        for filename, lines in subagent_specs:
            _write_jsonl(subdir / filename, lines)
    return jsonl


@pytest.fixture(autouse=True)
def _setup_pricing(monkeypatch):
    monkeypatch.setattr(main, "MODEL_PRICING", FAKE_PRICING)
    monkeypatch.setattr(main, "_PRICING_UPDATED", "2026-01-01")


# ── per-model cost calculation ──────────────────────────────────────

class TestPerModelCost:
    def test_single_model_cost(self, tmp_path):
        jsonl = _setup_with_subagents(tmp_path, [
            _usage_line("r1", model="claude-opus-4-6", input_tokens=1000, output_tokens=500),
        ])
        turns = scan_per_turn(jsonl)
        assert len(turns) == 1
        assert turns[0]["models"] == ["claude-opus-4-6"]
        assert turns[0]["cost"] > 0

    def test_multi_model_cost_not_double_counted(self, tmp_path):
        """When a turn uses two models, each model's tokens are priced separately."""
        jsonl = _setup_with_subagents(tmp_path, [
            _usage_line("r1", model="claude-opus-4-6", prompt_id="p1",
                        input_tokens=1000, output_tokens=500),
            _usage_line("r2", model="claude-haiku-4-5-20251001", prompt_id="p1",
                        input_tokens=2000, output_tokens=1000),
        ])
        turns = scan_per_turn(jsonl)
        assert len(turns) == 1
        t = turns[0]
        assert sorted(t["models"]) == ["claude-haiku-4-5-20251001", "claude-opus-4-6"]
        assert t["input"] == 3000
        assert t["output"] == 1500

        discount = 1 - main._DISCOUNT
        opus_cost = (1000 * 15.0 + 500 * 75.0) / 1_000_000 * discount
        haiku_cost = (2000 * 0.8 + 1000 * 4.0) / 1_000_000 * discount
        expected = opus_cost + haiku_cost
        assert t["cost"] == pytest.approx(expected)


# ── subagent inclusion ──────────────────────────────────────────────

class TestSubagentInclusion:
    def test_subagent_tokens_included_in_turn(self, tmp_path):
        jsonl = _setup_with_subagents(tmp_path,
            main_lines=[
                _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
            ],
            subagent_specs=[
                ("agent-1.jsonl", [
                    _usage_line("r2", prompt_id="p1", input_tokens=200, output_tokens=100),
                ]),
            ],
        )
        turns = scan_per_turn(jsonl)
        assert len(turns) == 1
        assert turns[0]["input"] == 300
        assert turns[0]["output"] == 150

    def test_subagent_assigned_to_matching_turn(self, tmp_path):
        """Subagent with promptId p1 merges into turn 1, not turn 2."""
        jsonl = _setup_with_subagents(tmp_path,
            main_lines=[
                _prompt_id_line("p1"),
                _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
                _prompt_id_line("p2"),
                _usage_line("r2", prompt_id="p2", input_tokens=100, output_tokens=50),
            ],
            subagent_specs=[
                ("agent-1.jsonl", [
                    _usage_line("r3", prompt_id="p1", input_tokens=500, output_tokens=200),
                ]),
            ],
        )
        turns = scan_per_turn(jsonl)
        assert len(turns) == 2
        assert turns[0]["input"] == 600
        assert turns[1]["input"] == 100

    def test_subagent_falls_back_to_last_turn(self, tmp_path):
        """Subagent with unknown promptId falls back to the last turn."""
        jsonl = _setup_with_subagents(tmp_path,
            main_lines=[
                _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
            ],
            subagent_specs=[
                ("agent-1.jsonl", [
                    _usage_line("r2", prompt_id="unknown-pid", input_tokens=200, output_tokens=100),
                ]),
            ],
        )
        turns = scan_per_turn(jsonl)
        assert len(turns) == 1
        assert turns[0]["input"] == 300

    def test_subagent_with_different_model(self, tmp_path):
        """Subagent using haiku gets priced at haiku rate, not opus."""
        jsonl = _setup_with_subagents(tmp_path,
            main_lines=[
                _usage_line("r1", model="claude-opus-4-6", prompt_id="p1",
                            input_tokens=1000, output_tokens=500),
            ],
            subagent_specs=[
                ("agent-1.jsonl", [
                    _usage_line("r2", model="claude-haiku-4-5-20251001", prompt_id="p1",
                                input_tokens=2000, output_tokens=1000),
                ]),
            ],
        )
        turns = scan_per_turn(jsonl)
        assert len(turns) == 1
        assert sorted(turns[0]["models"]) == ["claude-haiku-4-5-20251001", "claude-opus-4-6"]

        discount = 1 - main._DISCOUNT
        opus_cost = (1000 * 15.0 + 500 * 75.0) / 1_000_000 * discount
        haiku_cost = (2000 * 0.8 + 1000 * 4.0) / 1_000_000 * discount
        expected = opus_cost + haiku_cost
        assert turns[0]["cost"] == pytest.approx(expected)

    def test_no_subagent_dir(self, tmp_path):
        jsonl = _setup_with_subagents(tmp_path, [
            _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
        ])
        turns = scan_per_turn(jsonl)
        assert len(turns) == 1
        assert turns[0]["input"] == 100

    def test_dedup_across_main_and_subagent(self, tmp_path):
        """Same requestId in main and subagent is counted only once."""
        jsonl = _setup_with_subagents(tmp_path,
            main_lines=[
                _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
            ],
            subagent_specs=[
                ("agent-1.jsonl", [
                    _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
                ]),
            ],
        )
        turns = scan_per_turn(jsonl)
        assert len(turns) == 1
        assert turns[0]["input"] == 100

    def test_multiple_subagents_same_turn(self, tmp_path):
        """Multiple subagents all assigned to the same turn."""
        jsonl = _setup_with_subagents(tmp_path,
            main_lines=[
                _usage_line("r1", prompt_id="p1", input_tokens=100, output_tokens=50),
            ],
            subagent_specs=[
                ("agent-1.jsonl", [
                    _usage_line("r2", prompt_id="p1", input_tokens=200, output_tokens=100),
                ]),
                ("agent-2.jsonl", [
                    _usage_line("r3", prompt_id="p1", input_tokens=300, output_tokens=150),
                ]),
                ("agent-3.jsonl", [
                    _usage_line("r4", prompt_id="p1", input_tokens=400, output_tokens=200),
                ]),
            ],
        )
        turns = scan_per_turn(jsonl)
        assert len(turns) == 1
        assert turns[0]["input"] == 1000  # 100 + 200 + 300 + 400
        assert turns[0]["output"] == 500
