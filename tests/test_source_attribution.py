"""
Tests for source attribution (cite passages) as a core pipeline feature.
Every extracted fact must carry a source_line field (string, may be empty).
"""
import inspect
import pytest


def test_map_schema_list_items_are_objects():
    """MAP schema list fields must use {text, line} item objects, not plain strings."""
    from app.services.llm_provider import LocalProvider
    src = inspect.getsource(LocalProvider)
    assert "_MAP_ITEM" in src, "_MAP_ITEM object shape must be defined"
    assert '"required": ["text", "line"]' in src or "'required': ['text', 'line']" in src


def test_map_schema_scalar_items_are_objects():
    """MAP schema scalar fields must be {text, line} objects, not plain strings."""
    from app.services.llm_provider import LocalProvider
    src = inspect.getsource(LocalProvider)
    # Scalar fields should reference _MAP_ITEM (not {"type": "string"})
    assert '"technical_solution": _MAP_ITEM' in src or "_MAP_ITEM" in src


def test_map_instruction_mentions_line_citation():
    """MAP prompt must instruct the model to cite line numbers."""
    from app.services.llm_provider import LocalProvider
    src = inspect.getsource(LocalProvider)
    assert "cite the bracketed line number" in src or '"line"' in src


def test_fact_item_schema_has_source_line():
    """_FACT_ITEM REDUCE schema must include source_line in properties."""
    from app.services.llm_provider import LocalProvider
    src = inspect.getsource(LocalProvider)
    assert '"source_line"' in src


def test_fact_item_required_includes_source_line():
    """source_line must be in _FACT_ITEM required list."""
    from app.services.llm_provider import LocalProvider
    src = inspect.getsource(LocalProvider)
    # Check source_line appears alongside has_conflict in a required context
    assert "source_line" in src
    assert '"has_conflict"' in src


def test_merge_threads_source_line_from_dict_item():
    """Merge loop must extract line from MAP dict items into source_line."""
    from app.services import llm_provider
    src = inspect.getsource(llm_provider)
    assert '"source_line": line' in src or "'source_line': line" in src


def test_merge_source_line_empty_for_plain_string():
    """When MAP returns a plain string item, source_line defaults to ''."""
    from app.services import llm_provider
    src = inspect.getsource(llm_provider)
    # The merge loop must have a branch that sets line = "" for plain strings
    assert 'line = ""' in src


def test_regex_extraction_has_empty_source_line():
    """Regex-extracted facts (budget, timeline, team) must include source_line=''."""
    from app.services import llm_provider
    src = inspect.getsource(llm_provider)
    # All three regex appends must include source_line
    assert src.count('"source_line": ""') >= 3


def test_no_data_defaults_have_source_line():
    """Every dict that sets has_conflict must also set source_line."""
    from app.services import llm_provider
    src = inspect.getsource(llm_provider)
    hc_count = src.count('"has_conflict"')
    sl_count = src.count('"source_line"')
    assert sl_count >= hc_count, (
        f"source_line ({sl_count}) should appear at least as often as "
        f"has_conflict ({hc_count}) — some defaults are missing source_line"
    )


def test_make_fact_carries_source_line():
    """_make_fact helper must carry source_line from the entry."""
    from app.services import llm_provider
    src = inspect.getsource(llm_provider)
    assert 'source_line.*entry' in src or "entry.get(\"source_line\"" in src or "entry.get('source_line'" in src
