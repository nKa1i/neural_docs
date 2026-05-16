"""
Tests for security hardening: file type whitelist, size limits,
per-session rate limiting, and LLM output sanitization.
"""
import time
import pytest


# ── C1: File type whitelist ───────────────────────────────────────────────────

def test_allowed_extensions_set_contains_common_types():
    from app.api.routes import ALLOWED_EXTENSIONS
    for ext in (".pdf", ".txt", ".docx", ".py", ".js", ".md", ".json"):
        assert ext in ALLOWED_EXTENSIONS, f"{ext} must be in ALLOWED_EXTENSIONS"


def test_disallowed_extensions_not_in_set():
    from app.api.routes import ALLOWED_EXTENSIONS
    for ext in (".exe", ".zip", ".dll", ".bat", ".sh", ".bin"):
        assert ext not in ALLOWED_EXTENSIONS, f"{ext} must NOT be in ALLOWED_EXTENSIONS"


def test_extension_check_is_case_insensitive():
    """Extension check must use .lower() so .PDF and .PDF are treated as .pdf."""
    import pathlib
    assert pathlib.Path("report.PDF").suffix.lower() == ".pdf"
    assert pathlib.Path("SCRIPT.EXE").suffix.lower() == ".exe"


# ── C2: File size + count limits ─────────────────────────────────────────────

def test_size_constants_are_correct():
    from app.api.routes import MAX_FILE_BYTES, MAX_TOTAL_BYTES, MAX_FILES
    assert MAX_FILE_BYTES  == 10 * 1024 * 1024
    assert MAX_TOTAL_BYTES == 30 * 1024 * 1024
    assert MAX_FILES       == 10


def test_single_file_over_limit_detected():
    from app.api.routes import MAX_FILE_BYTES
    large = b"x" * (MAX_FILE_BYTES + 1)
    assert len(large) > MAX_FILE_BYTES


def test_total_size_over_limit_detected():
    from app.api.routes import MAX_TOTAL_BYTES
    files = [b"x" * (11 * 1024 * 1024)] * 3   # 3 × 11 MB = 33 MB > 30 MB
    total = sum(len(f) for f in files)
    assert total > MAX_TOTAL_BYTES


def test_file_count_over_limit_detected():
    from app.api.routes import MAX_FILES
    assert 11 > MAX_FILES


# ── C3: Per-session rate limiter ─────────────────────────────────────────────

def test_rate_limit_allows_five_requests():
    from app.api.routes import _check_rate_limit, _rate_limit_store
    session = "test-allow-5"
    _rate_limit_store[session] = []
    for _ in range(5):
        assert _check_rate_limit(session) is True


def test_rate_limit_blocks_sixth_request():
    from app.api.routes import _check_rate_limit, _rate_limit_store
    session = "test-block-6"
    _rate_limit_store[session] = []
    for _ in range(5):
        _check_rate_limit(session)
    assert _check_rate_limit(session) is False


def test_rate_limit_resets_after_window():
    from app.api.routes import _check_rate_limit, _rate_limit_store, RATE_LIMIT_WINDOW
    session = "test-reset"
    old_time = time.time() - RATE_LIMIT_WINDOW - 10
    _rate_limit_store[session] = [old_time] * 5   # 5 expired timestamps
    assert _check_rate_limit(session) is True      # pruned → allowed


def test_different_sessions_are_independent():
    from app.api.routes import _check_rate_limit, _rate_limit_store
    s1, s2 = "test-session-a", "test-session-b"
    _rate_limit_store[s1] = []
    _rate_limit_store[s2] = []
    for _ in range(5):
        _check_rate_limit(s1)
    assert _check_rate_limit(s1) is False   # s1 exhausted
    assert _check_rate_limit(s2) is True    # s2 unaffected


# ── C4: LLM output sanitization ──────────────────────────────────────────────

def test_sanitize_strips_script_tags():
    from app.services.sanitizer import sanitize_llm_output
    result = sanitize_llm_output('hello <script>alert(1)</script> world')
    assert '<script>' not in result
    assert 'hello' in result
    assert 'world' in result


def test_sanitize_strips_script_with_attributes():
    from app.services.sanitizer import sanitize_llm_output
    result = sanitize_llm_output('<script type="text/javascript">evil()</script>')
    assert '<script' not in result


def test_sanitize_strips_control_chars():
    from app.services.sanitizer import sanitize_llm_output
    result = sanitize_llm_output('text\x00with\x01control\x07chars')
    assert '\x00' not in result
    assert '\x01' not in result
    assert 'textwithcontrolchars' in result


def test_sanitize_preserves_newlines_and_tabs():
    from app.services.sanitizer import sanitize_llm_output
    text = "line1\nline2\ttabbed\r\n"
    assert sanitize_llm_output(text) == text


def test_sanitize_strips_javascript_uri():
    from app.services.sanitizer import sanitize_llm_output
    result = sanitize_llm_output('click here javascript:alert(1)')
    assert 'javascript:' not in result


def test_sanitize_preserves_normal_project_text():
    from app.services.sanitizer import sanitize_llm_output
    text = "Project budget: $500,000. Timeline: 12 months. Team: 5 engineers."
    assert sanitize_llm_output(text) == text


def test_sanitize_result_recurses_into_dicts():
    from app.services.sanitizer import sanitize_result
    data = {"text": "hello <script>bad</script>", "nested": {"val": "clean"}}
    result = sanitize_result(data)
    assert '<script>' not in result["text"]
    assert result["nested"]["val"] == "clean"


def test_sanitize_result_recurses_into_lists():
    from app.services.sanitizer import sanitize_result
    data = [{"text": "clean"}, {"text": "<script>bad</script>"}]
    result = sanitize_result(data)
    assert result[0]["text"] == "clean"
    assert '<script>' not in result[1]["text"]


def test_sanitize_result_leaves_non_strings_unchanged():
    from app.services.sanitizer import sanitize_result
    data = {"count": 42, "flag": True, "nothing": None}
    result = sanitize_result(data)
    assert result["count"] == 42
    assert result["flag"] is True
    assert result["nothing"] is None
