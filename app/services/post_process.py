"""
Post-processing utilities for the LLM pipeline.
Pure functions — no side effects, no LLM calls.
"""
import re
import json


def _repair_json(raw: str):
    """Return a parsed dict, or None if all repair stages fail."""
    s = raw.find("{"); e = raw.rfind("}")
    if s == -1 or e == -1:
        return None
    snippet = raw[s:e+1]

    # Stage 1 — direct parse
    try:
        return json.loads(snippet)
    except Exception:
        pass

    # Stage 2 — strip trailing commas: ,} or ,]
    fixed = re.sub(r",\s*([}\]])", r"\1", snippet)
    try:
        return json.loads(fixed)
    except Exception:
        pass

    # Stage 3 — fix bracket mismatches
    def _fix_brackets(text: str) -> str:
        out, stack = [], []
        in_str = esc = False
        for ch in text:
            if esc:
                esc = False; out.append(ch); continue
            if ch == "\\" and in_str:
                esc = True; out.append(ch); continue
            if ch == '"':
                in_str = not in_str; out.append(ch); continue
            if in_str:
                out.append(ch); continue
            if ch == "{":
                stack.append("}"); out.append(ch)
            elif ch == "[":
                stack.append("]"); out.append(ch)
            elif ch in "}]":
                out.append(stack.pop() if stack else ch)
            else:
                out.append(ch)
        while stack:
            out.append(stack.pop())
        return "".join(out)

    fixed2 = _fix_brackets(fixed)
    try:
        return json.loads(fixed2)
    except Exception:
        pass

    # Stage 4 — strip markdown fences
    stripped = re.sub(r"```(?:json)?|```", "", raw).strip()
    for attempt in (stripped, re.sub(r",\s*([}\]])", r"\1", stripped)):
        s2 = attempt.find("{"); e2 = attempt.rfind("}")
        if s2 != -1 and e2 != -1:
            try:
                return json.loads(attempt[s2:e2+1])
            except Exception:
                try:
                    return json.loads(_fix_brackets(attempt[s2:e2+1]))
                except Exception:
                    pass

    # Stage 5 — fix single-quoted string values
    def _fix_single_quotes(text: str) -> str:
        # Simple case: replace all single quotes with double quotes
        # for JSON-like inputs (starts with { or [)
        stripped_text = text.strip()
        if stripped_text.startswith('{') or stripped_text.startswith('['):
            return text.replace("'", '"')
        # Complex case: try targeted replacement for ': 'value'' → ': "value"'
        return re.sub(r": '(.*?)'", r': "\1"', text)

    for src_text in (fixed, fixed2, stripped):
        sq = _fix_single_quotes(src_text)
        sq_clean = re.sub(r",\s*([}\]])", r"\1", sq)
        sq_clean = _fix_brackets(sq_clean)
        s3 = sq_clean.find("{"); e3 = sq_clean.rfind("}")
        if s3 != -1 and e3 != -1:
            try:
                return json.loads(sq_clean[s3:e3+1])
            except Exception:
                pass
    return None


def _base_src(source: str) -> str:
    """Return bare filename, stripping chunk labels like '(lines 1–80)' or '(part 2/4)'."""
    s = source.strip()
    s = re.sub(r"\s*\(lines\s+\d+[–\-]\d+\)\s*$", "", s)
    s = re.sub(r"\s*\(part\s+\d+/\d+\)\s*$", "", s)
    return s


def _detect_conflict(entries: list) -> tuple:
    """Detect if entries from different files have different values.

    Returns (is_conflict: bool, detail: str).
    Same value from same file = just line items, NOT conflict.
    Same value from different files = agreement, NOT conflict.
    Different values from different files = real conflict.
    """
    if len(entries) < 2:
        return False, ""

    # Keep one representative (longest) value per base file
    per_file: dict = {}  # base_src -> best entry
    for e in entries:
        src = _base_src(e["source"])
        existing = per_file.get(src)
        if existing is None or len(e["text"]) > len(existing["text"]):
            per_file[src] = e

    if len(per_file) < 2:
        return False, ""  # all values from the same file -> no conflict

    # Check whether the per-file values actually differ
    norms = {re.sub(r"\s+", " ", e["text"].strip().lower())
             for e in per_file.values()}
    if len(norms) < 2:
        return False, ""  # all files agree -> no conflict

    parts = "; ".join(
        f'{src} — "{e["text"]}"' for src, e in per_file.items()
    )
    return True, f"Conflict: {parts}"
