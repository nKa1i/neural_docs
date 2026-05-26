# NeuralDocs AI — Implementation Plan
**Date:** 2026-05-16
**Specs covered:** Source Attribution · Conflict Persistence · Security Hardening
**Status:** Ready for execution

---

## Codebase Findings

Key splice points discovered during exploration:

- `sanitizer.py` is a stub (comment only) — all output sanitization goes there
- `_normalize_parsed` (~line 902) is the canonical source of `EMPTY_SCALAR` dicts — needs `source_line: ""`
- `_make_fact` (~line 1007) constructs inline fallback facts — needs `source_line: ""`
- `_merge_partial_specs` (~line 581) constructs scalar defaults inline — needs `source_line: ""`
- Merge loop (lines 293–312): `merged[key].append({"text": ..., "source": src})` — primary splice point for `source_line`
- Regex pre-extraction (lines 369–412): three more `{"text": val, "source": fname}` appends — all need `source_line`
- `markConflictResolved()` in `index.html` (line ~908) writes `resolved: true` but never fires PATCH
- `done` SSE handler (~line 1004–1016): calls `showResult(data, false)` — no filename tracking yet
- `loadSampleByName` (~line 1160): sets no `currentArchiveFilename` yet
- `routes.py` lines 172–174: archive filename constructed but never injected into `done` payload
- No `PATCH /api/samples/{filename}` endpoint exists
- No rate limiting, no extension whitelist, no size check in `generate_document`

---

## Dependency Graph

```
Spec A — Source Attribution
  A1  MAP schema + MAP prompt                [llm_provider.py]
  A2  merge step threads source_line         [llm_provider.py]  ← needs A1
  A3  REDUCE schema + REDUCE prompt          [llm_provider.py]  ← needs A2
  A4  "No data" defaults get source_line     [llm_provider.py]  ← needs A3
  A5  frontend source-badge rendering        [index.html]        ← needs A3
  A6  tests/test_source_attribution.py       [tests/]           ← needs A1–A4

Spec B — Conflict Persistence
  B1  inject _archive_filename into done SSE [routes.py]
  B2  PATCH /api/samples/{filename}          [routes.py]         ← needs B1
  B3  frontend currentArchiveFilename        [index.html]        ← needs B1
  B4  frontend PATCH call in resolveConflict [index.html]        ← needs B2+B3
  B5  tests/test_conflict_persistence.py     [tests/]           ← needs B1+B2

Spec C — Security Hardening
  C1  file type whitelist                    [routes.py]
  C2  file size + count limits               [routes.py]         ← needs C1
  C3  per-session rate limiter               [routes.py]         ← independent
  C4  LLM output sanitization                [sanitizer.py, routes.py]
  C5  tests/test_security_hardening.py       [tests/]           ← needs C1–C4

Cross-spec ordering:
  routes.py touched by: B1, B2, C1, C2, C3, C4 → do B then C to avoid conflicts
  llm_provider.py touched by: A1–A4 → do A in one pass
  index.html touched by: A5, B3, B4 → do A5 first, then B3+B4
```

---

## Execution Order

```
Phase 1: Spec A (Source Attribution)  — llm_provider.py + index.html
  A1 → A2 → A3 → A4 → CHECKPOINT → A5 → A6

Phase 2: Spec B (Conflict Persistence) — routes.py + index.html
  B1 → B2 → CHECKPOINT → B3 → B4 → B5

Phase 3: Spec C (Security Hardening) — routes.py + sanitizer.py
  C1 → C2 → C3 → C4 → C5

Phase 4: Final checkpoint — full test suite + smoke test
```

---

## Phase 1: Source Attribution

### Task A1 — MAP schema: items become `{"text", "line"}` objects + MAP prompt update
**Files:** `app/services/llm_provider.py`

Update `_MAP_RESPONSE_FORMAT` so list fields (`goals`, `requirements`, `team`, `risks`) use item objects instead of plain strings, and scalar fields (`technical_solution`, `architecture`, `timeline`, `budget`) become objects too:

```python
_MAP_ITEM = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "line": {"type": "string"}   # "42", "page 3", "§12", or ""
    },
    "required": ["text", "line"],
    "additionalProperties": False
}
```

Update `map_instruction` to add:
```
• For each fact, cite the bracketed line number where you found it (e.g. [42]).
• Write only the digits in the "line" field (e.g. "42").
• For PDFs the input uses "--- page N ---" markers — write "page N" in the "line" field.
• If you cannot identify a specific line, leave "line" as "".
```

Also update `_parse_map_output` to handle the new object format (unwrap `text` from each item if needed).

**Acceptance criteria:**
- `_MAP_RESPONSE_FORMAT` list items are `{"text": string, "line": string}` objects
- Scalar fields are also `{"text": string, "line": string}` objects
- MAP instruction mentions citing line numbers

**Verify:** `python -c "from app.services.llm_provider import LocalProvider; print('OK')"`

---

### Task A2 — Merge step threads `source_line` through

**Files:** `app/services/llm_provider.py`

In `_map_one`'s merge loop (lines ~293–312), update every `merged[key].append(...)` call to extract `line` from MAP items and store it as `source_line`:

```python
# List fields
if isinstance(item, dict):
    text = str(item.get("text", "")).strip()
    line = str(item.get("line", "")).strip()
else:
    text = str(item).strip()
    line = ""
if text:
    merged[key].append({"text": text, "source": src, "source_line": line})

# Scalar fields
if isinstance(val, dict):
    line = str(val.get("line", "")).strip()
    val = str(val.get("text", val)).strip()
else:
    line = ""
if val:
    merged[key].append({"text": val, "source": src, "source_line": line})
```

Also update the 3 regex pre-extraction appends (budget, timeline, team around lines 369–412):
```python
merged["budget"].append({"text": val, "source": fname, "source_line": ""})
```

**Acceptance criteria:**
- Every item in `merged[key]` has a `source_line` key (string, may be empty)
- Regex-extracted facts have `source_line: ""`

**Verify:** `python -c "from app.services.llm_provider import LocalProvider; print('OK')"`

---

### Task A3 — REDUCE schema `_FACT_ITEM` + REDUCE prompt

**Files:** `app/services/llm_provider.py`

Add `source_line` to `_FACT_ITEM`:
```python
_FACT_ITEM = {
    "type": "object",
    "properties": {
        "text":             {"type": "string"},
        "source":           {"type": "string"},
        "source_line":      {"type": "string"},   # ← new
        "has_conflict":     {"type": "boolean"},
        "conflict_details": {"type": "string"}
    },
    "required": ["text", "source", "source_line", "has_conflict", "conflict_details"],
    "additionalProperties": False
}
```

Update REDUCE instruction to add:
```
• Each fact in the input has a "source_line" field. Copy it verbatim into the output "source_line" field.
• Do not invent line numbers. If source_line is "", output "".
```

Update the REDUCE example JSON template (lines ~494–501) to include `"source_line": ""` in each fact example.

**Acceptance criteria:**
- `_FACT_ITEM` has `source_line` in both `properties` and `required`
- REDUCE instruction mentions copying `source_line` verbatim

**Verify:** `python -c "from app.services.llm_provider import LocalProvider; print('OK')"`

---

### Task A4 — All "No data" defaults get `source_line: ""`

**Files:** `app/services/llm_provider.py`

Find every location that constructs a fact-item dict with `"No data"` or empty text:
- `_normalize_parsed` (~line 902): `EMPTY_SCALAR` dict
- `_make_fact` (~line 1007): inline fallback
- `_merge_partial_specs` (~line 581): scalar defaults
- The `{k: {"text": "No data", "source": "", "has_conflict": False, "conflict_details": ""}` at line ~594

Add `"source_line": ""` to each.

**Acceptance criteria:**
- Grep for `"has_conflict": False` in `llm_provider.py` — every match also has `"source_line": ""`

**Verify:**
```bash
pytest tests/test_project_name_extraction.py -v
pytest tests/test_public_release.py -v
```
All existing tests pass.

---

### CHECKPOINT A — App starts, existing tests pass

```bash
python -c "import main; print('OK')"
pytest tests/ -v
```

---

### Task A5 — Frontend: update `.source-badge` to show line/page reference

**Files:** `app/frontend/index.html`

Find the function or inline code that renders source badges. Update it to append the line reference:

```javascript
function makeSourceBadge(fact) {
    if (!fact || !fact.source) return ''
    let ref = ''
    if (fact.source_line) {
        const sl = fact.source_line
        ref = ' · ' + (sl.startsWith('page') || sl.startsWith('§') ? sl : 'line ' + sl)
    }
    return `<span class="source-badge">${fact.source}${ref}</span>`
}
```

**Acceptance criteria:**
- A fact with `source: "brief.txt"` and `source_line: "42"` renders as `brief.txt · line 42`
- A fact with `source: "report.pdf"` and `source_line: "page 3"` renders as `report.pdf · page 3`
- A fact with `source_line: ""` renders as just `brief.txt`

**Verify:** Manual — run pipeline, check source badges in Results UI.

---

### Task A6 — Tests: `tests/test_source_attribution.py`

```python
def test_map_schema_list_items_are_objects()
def test_map_schema_scalar_items_are_objects()
def test_merge_threads_source_line_from_dict_item()
def test_merge_threads_source_line_from_plain_string()   # backwards compat
def test_fact_item_schema_has_source_line()
def test_no_data_default_has_source_line()
def test_regex_extraction_has_empty_source_line()
```

**Verify:** `pytest tests/test_source_attribution.py -v` — all pass.

---

## Phase 2: Conflict Persistence

### Task B1 — Inject `_archive_filename` into `done` SSE payload

**Files:** `app/api/routes.py`

After constructing `archive_path` (lines ~172–174), add the filename to the result before yielding `done`:

```python
archive_filename = f"analysis_{timestamp}_{short_id}.json"
archive_path = os.path.join(session_dir, archive_filename)
with open(archive_path, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

result["_archive_filename"] = archive_filename   # ← inject
yield _sse("done", json.dumps(result, ensure_ascii=False))
```

**Acceptance criteria:**
- `done` SSE payload JSON contains `_archive_filename` key with value like `"analysis_20260516_142301_a3f9c1.json"`

**Verify:** `python -c "from app.api.routes import router; print('OK')"`

---

### Task B2 — New `PATCH /api/samples/{filename}` endpoint

**Files:** `app/api/routes.py`

```python
@router.patch("/api/samples/{filename}")
async def update_sample(filename: str, request: Request):
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    session_dir = get_session_dir(request)
    path = os.path.join(session_dir, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return JSONResponse({"ok": True})
```

**Acceptance criteria:**
- `PATCH /api/samples/valid_file.json` with valid JSON body returns `{"ok": true}`
- `PATCH /api/samples/../evil.json` returns 400
- `PATCH /api/samples/missing.json` returns 404

**Verify:** `python -c "from app.api.routes import router; print('OK')"`

---

### CHECKPOINT B — Routes load, existing tests pass

```bash
python -c "import main; print('OK')"
pytest tests/ -v
```

---

### Task B3 — Frontend: track `currentArchiveFilename`

**Files:** `app/frontend/index.html`

Add near the top of the script block:
```javascript
let currentArchiveFilename = null
```

In the `done` SSE handler, after parsing `data`:
```javascript
currentArchiveFilename = data._archive_filename || null
```

In `loadSampleByName(filename)`:
```javascript
currentArchiveFilename = filename
```

**Acceptance criteria:**
- After a pipeline run, `currentArchiveFilename` holds the archive filename
- After clicking an archive item, `currentArchiveFilename` holds that item's filename

---

### Task B4 — Frontend: fire-and-forget PATCH in `markConflictResolved`

**Files:** `app/frontend/index.html`

In `markConflictResolved()` (line ~908), after writing `resolved: true` to `currentRawData` and re-rendering, add:

```javascript
if (currentArchiveFilename && currentRawData) {
    fetch(`/api/samples/${currentArchiveFilename}`, {
        method: 'PATCH',
        headers: {
            'Content-Type': 'application/json',
            'X-Session-Id': SESSION_ID
        },
        body: JSON.stringify(currentRawData)
    }).catch(e => console.warn('Could not persist resolved state:', e))
}
```

**Acceptance criteria:**
- Marking a conflict resolved triggers a PATCH request to the correct endpoint
- PATCH failure is caught and logged — does not surface as a UI error
- After page reload and re-loading the same archive item, the conflict remains resolved

**Verify:** Manual — run pipeline → mark conflict resolved → reload page → load archive item → conflict stays resolved.

---

### Task B5 — Tests: `tests/test_conflict_persistence.py`

```python
def test_patch_sample_updates_file(tmp_path)
def test_patch_sample_path_traversal_blocked()
def test_patch_sample_wrong_session_returns_404()
def test_patch_sample_missing_file_returns_404()
def test_patch_sample_invalid_json_returns_400()
def test_done_payload_contains_archive_filename()  # mock pipeline result
```

**Verify:** `pytest tests/test_conflict_persistence.py -v` — all pass.

---

## Phase 3: Security Hardening

### Task C1 — File type whitelist

**Files:** `app/api/routes.py`

Add at module level:
```python
import pathlib

ALLOWED_EXTENSIONS = {
    ".txt", ".pdf", ".docx",
    ".py", ".js", ".ts", ".jsx", ".tsx",
    ".java", ".go", ".rs", ".cpp", ".c", ".h",
    ".md", ".json", ".yaml", ".yml", ".toml",
    ".csv", ".html", ".css"
}
```

Inside `event_stream()`, after extracting text and before the security scan:
```python
ext = pathlib.Path(filename).suffix.lower()
if ext not in ALLOWED_EXTENSIONS:
    yield _sse("error", f"File type '{ext}' is not supported.")
    return
```

**Acceptance criteria:**
- `.pdf`, `.txt`, `.py` pass the check
- `.exe`, `.zip`, `.dll` trigger SSE error before any LLM call

**Verify:** `python -c "from app.api.routes import router; print('OK')"`

---

### Task C2 — File size + count limits

**Files:** `app/api/routes.py`

Add at module level:
```python
MAX_FILE_BYTES  = 10 * 1024 * 1024   # 10 MB
MAX_TOTAL_BYTES = 30 * 1024 * 1024   # 30 MB
MAX_FILES       = 10
```

In `generate_document`, after reading all file bytes into `files_data_pre` (before `event_stream`):
```python
if len(files_data_pre) > MAX_FILES:
    raise HTTPException(status_code=400, detail=f"Too many files. Maximum is {MAX_FILES}.")

total_bytes = 0
for fname, content in files_data_pre:
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail=f"File '{fname}' exceeds the 10 MB limit.")
    total_bytes += len(content)
if total_bytes > MAX_TOTAL_BYTES:
    raise HTTPException(status_code=400, detail="Total upload size exceeds 30 MB.")
```

**Acceptance criteria:**
- 11 files → 400 before streaming starts
- Single file >10 MB → 400
- Total >30 MB → 400

**Verify:** `python -c "from app.api.routes import router; print('OK')"`

---

### Task C3 — Per-session rate limiter (5 req/hr in-memory)

**Files:** `app/api/routes.py`

Add at module level:
```python
from collections import defaultdict

_rate_limit_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT_MAX    = 5
RATE_LIMIT_WINDOW = 3600  # seconds

def _check_rate_limit(session_id: str) -> bool:
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW
    _rate_limit_store[session_id] = [t for t in _rate_limit_store[session_id] if t > cutoff]
    if len(_rate_limit_store[session_id]) >= RATE_LIMIT_MAX:
        return False
    _rate_limit_store[session_id].append(now)
    return True
```

At the top of `generate_document` (before reading file bytes):
```python
session_id = request.headers.get("X-Session-Id", "default")
if not _check_rate_limit(session_id):
    raise HTTPException(status_code=429, detail="Rate limit exceeded. Max 5 analyses per hour.")
```

**Acceptance criteria:**
- First 5 calls for a session succeed
- 6th call within 1 hour returns 429
- After 1 hour window, counter resets

**Verify:** `python -c "from app.api.routes import router; print('OK')"`

---

### Task C4 — LLM output sanitization

**Files:** `app/services/sanitizer.py`, `app/api/routes.py`

Implement in `sanitizer.py`:
```python
import re

def sanitize_llm_output(text: str) -> str:
    """Strip control characters and XSS vectors from LLM output strings."""
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    text = re.sub(r'<script[\s\S]*?</script>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'javascript\s*:', '', text, flags=re.IGNORECASE)
    return text

def sanitize_result(obj):
    """Recursively sanitize all string values in a result dict."""
    if isinstance(obj, str):
        return sanitize_llm_output(obj)
    if isinstance(obj, dict):
        return {k: sanitize_result(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_result(i) for i in obj]
    return obj
```

In `routes.py`, import and apply before yielding `done`:
```python
from app.services.sanitizer import sanitize_result
# ...
result = sanitize_result(result)
yield _sse("done", json.dumps(result, ensure_ascii=False))
```

**Acceptance criteria:**
- `<script>alert(1)</script>` in any string value is stripped
- `javascript:alert(1)` is stripped
- Control chars `\x00`–`\x1f` (except `\t`, `\n`, `\r`) are stripped
- Normal project text passes through unchanged

**Verify:** `python -c "from app.services.sanitizer import sanitize_result; print('OK')"`

---

### Task C5 — Tests: `tests/test_security_hardening.py`

```python
def test_allowed_extension_txt_passes()
def test_allowed_extension_pdf_passes()
def test_disallowed_extension_exe_blocked()
def test_disallowed_extension_zip_blocked()
def test_file_too_large_blocked()
def test_total_size_too_large_blocked()
def test_too_many_files_blocked()
def test_rate_limit_allows_five_requests()
def test_rate_limit_blocks_sixth_request()
def test_rate_limit_resets_after_window()
def test_sanitize_strips_script_tags()
def test_sanitize_strips_control_chars()
def test_sanitize_strips_javascript_uri()
def test_sanitize_preserves_normal_text()
def test_sanitize_result_recurses_into_dicts()
def test_sanitize_result_recurses_into_lists()
```

**Verify:** `pytest tests/test_security_hardening.py -v` — all 16 pass.

---

## Phase 4: Final Checkpoint

```bash
python -c "import main; print('OK')"
pytest tests/ -v
```

Expected: all tests pass across all 4 test files.

Then commit each phase separately (one commit per spec).
