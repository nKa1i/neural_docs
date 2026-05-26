"""Tests for JSON repair — all 5 repair stages."""
from app.services.post_process import _repair_json
import pytest


def test_stage1_direct_parse():
    """Stage 1: valid JSON passes through."""
    raw = '{"name": "test", "value": 42}'
    result = _repair_json(raw)
    assert result == {"name": "test", "value": 42}


def test_stage2_strip_trailing_commas():
    """Stage 2: trailing commas before ] or } are removed."""
    raw = '{"name": "test", "value": 42,}'
    result = _repair_json(raw)
    assert result == {"name": "test", "value": 42}


def test_stage2_trailing_commas_in_arrays():
    """Stage 2: trailing commas in arrays too."""
    raw = '{"items": [1, 2, 3,]}'
    result = _repair_json(raw)
    assert result == {"items": [1, 2, 3]}


def test_stage3_fix_bracket_mismatches():
    """Stage 3: } where ] expected is fixed."""
    raw_broken = '{"items": [{"a": 1}, {"b": 2}}'
    result = _repair_json(raw_broken)
    assert result is not None
    assert "items" in result


def test_stage4_strip_markdown_fences():
    """Stage 4: ```json ... ``` fences are stripped."""
    raw = '```json\n{"name": "test"}\n```'
    result = _repair_json(raw)
    assert result == {"name": "test"}


def test_stage4_strip_json_fence_only():
    """Stage 4: just ``` (no json) also stripped."""
    raw = '```\n{"name": "test"}\n```'
    result = _repair_json(raw)
    assert result == {"name": "test"}


def test_stage5_fix_single_quotes():
    """Stage 5: single-quoted string values are converted to double-quoted."""
    raw = "{'name': 'test', 'value': 42}"
    result = _repair_json(raw)
    assert result == {"name": "test", "value": 42}


def test_no_brackets_returns_none():
    """If input has no { or }, return None."""
    result = _repair_json("no json here")
    assert result is None


def test_no_opening_bracket_returns_none():
    """Only } but no { → None."""
    result = _repair_json('{"key": "val}')
    assert result is None


def test_empty_object():
    """Empty JSON object passes."""
    result = _repair_json("{}")
    assert result == {}


def test_nested_object():
    """Nested objects with commas."""
    raw = '{"a": {"b": {"c": 1}},}'
    result = _repair_json(raw)
    assert result == {"a": {"b": {"c": 1}}}


def test_nested_array():
    """Nested arrays."""
    raw = '{"items": [[1, 2], [3, 4]]}'
    result = _repair_json(raw)
    assert result == {"items": [[1, 2], [3, 4]]}


def test_deeply_nested_bracket_fix():
    """Multiple levels of } where ] expected."""
    raw = '{"a": {"b": {"c": 1}, "d": {"e": 2}},}'
    result = _repair_json(raw)
    assert result is not None
    assert "a" in result


def test_text_before_and_after_json():
    """Text before { and after } is ignored."""
    raw = 'Here is some text {"key": "val"} More text'
    result = _repair_json(raw)
    assert result == {"key": "val"}


def test_string_with_commas_doesnt_break():
    """Commas inside strings should not trigger trailing comma removal."""
    raw = '{"sentence": "hello, world, foo,"}'
    result = _repair_json(raw)
    assert result == {"sentence": "hello, world, foo,"}


def test_complex_realistic_llm_output():
    """A realistic broken JSON output from an LLM."""
    raw = """```json
{
  "project_name": "TestApp",
  "goals": [{"text": "Build platform", "line": "1"},],
  "budget": {"text": "$1M",},
  "architecture": {"text": "Microservices", "line": "3"}
}
```"""
    result = _repair_json(raw)
    assert result is not None
    assert result["project_name"] == "TestApp"
    assert len(result["goals"]) == 1
    assert result["goals"][0]["text"] == "Build platform"
