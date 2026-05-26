# NeuralDocs AI — Task List
**Generated:** 2026-05-16
**Specs:** Source Attribution · Conflict Persistence · Security Hardening

---

## Phase 1: Source Attribution

- [ ] **A1** — MAP schema: list + scalar items become `{"text", "line"}` objects; update MAP prompt to cite line numbers
  - Files: `app/services/llm_provider.py`
  - Verify: `python -c "from app.services.llm_provider import LocalProvider; print('OK')"`

- [ ] **A2** — Merge step: extract `line` from MAP items, store as `source_line` in merged dicts (list fields, scalar fields, regex pre-extraction)
  - Files: `app/services/llm_provider.py`
  - Verify: `python -c "from app.services.llm_provider import LocalProvider; print('OK')"`

- [ ] **A3** — REDUCE schema: add `source_line: string` to `_FACT_ITEM` required fields; update REDUCE prompt to copy `source_line` verbatim; update example template
  - Files: `app/services/llm_provider.py`
  - Verify: `python -c "from app.services.llm_provider import LocalProvider; print('OK')"`

- [ ] **A4** — All "No data" defaults: add `"source_line": ""` to every inline fact dict (`_normalize_parsed`, `_make_fact`, `_merge_partial_specs`, line ~594 placeholder)
  - Files: `app/services/llm_provider.py`
  - Verify: `pytest tests/test_project_name_extraction.py tests/test_public_release.py -v`

- [ ] **CHECKPOINT A** — `python -c "import main; print('OK')"` && `pytest tests/ -v`

- [ ] **A5** — Frontend: update `.source-badge` rendering to show `filename · line N` or `filename · page N`
  - Files: `app/frontend/index.html`
  - Verify: Manual — run pipeline, check source badges in Results UI

- [ ] **A6** — Write `tests/test_source_attribution.py` (7 tests)
  - Verify: `pytest tests/test_source_attribution.py -v`

- [ ] **COMMIT A** — `git commit -m "feat: source attribution — filename + line/page ref on every extracted fact"`

---

## Phase 2: Conflict Persistence

- [ ] **B1** — Inject `_archive_filename` into `done` SSE payload (routes.py lines ~172–176)
  - Files: `app/api/routes.py`
  - Verify: `python -c "from app.api.routes import router; print('OK')"`

- [ ] **B2** — New `PATCH /api/samples/{filename}` endpoint (session-scoped, path-traversal blocked)
  - Files: `app/api/routes.py`
  - Verify: `python -c "from app.api.routes import router; print('OK')"`

- [ ] **CHECKPOINT B** — `python -c "import main; print('OK')"` && `pytest tests/ -v`

- [ ] **B3** — Frontend: add `currentArchiveFilename` variable; set on `done` SSE event and in `loadSampleByName`
  - Files: `app/frontend/index.html`

- [ ] **B4** — Frontend: fire-and-forget PATCH in `markConflictResolved` after writing `resolved: true`
  - Files: `app/frontend/index.html`
  - Verify: Manual — run pipeline → resolve conflict → reload → load archive item → conflict stays resolved

- [ ] **B5** — Write `tests/test_conflict_persistence.py` (6 tests)
  - Verify: `pytest tests/test_conflict_persistence.py -v`

- [ ] **COMMIT B** — `git commit -m "feat: conflict resolved-state persists to archive JSON via PATCH endpoint"`

---

## Phase 3: Security Hardening

- [ ] **C1** — File type whitelist: `ALLOWED_EXTENSIONS` set + extension check before text extraction
  - Files: `app/api/routes.py`
  - Verify: `python -c "from app.api.routes import router; print('OK')"`

- [ ] **C2** — File size + count limits: `MAX_FILES=10`, `MAX_FILE_BYTES=10MB`, `MAX_TOTAL_BYTES=30MB`
  - Files: `app/api/routes.py`
  - Verify: `python -c "from app.api.routes import router; print('OK')"`

- [ ] **C3** — Per-session rate limiter: `_check_rate_limit()`, 5 req/hr in-memory token bucket; HTTP 429 on breach
  - Files: `app/api/routes.py`
  - Verify: `python -c "from app.api.routes import router; print('OK')"`

- [ ] **C4** — LLM output sanitization: implement `sanitize_llm_output` + `sanitize_result` in `sanitizer.py`; apply in `routes.py` before yielding `done`
  - Files: `app/services/sanitizer.py`, `app/api/routes.py`
  - Verify: `python -c "from app.services.sanitizer import sanitize_result; print('OK')"`

- [ ] **C5** — Write `tests/test_security_hardening.py` (16 tests)
  - Verify: `pytest tests/test_security_hardening.py -v`

- [ ] **COMMIT C** — `git commit -m "feat: security hardening — file whitelist, size limits, rate limiting, output sanitization"`

---

## Phase 4: Final Checkpoint

- [ ] **FINAL** — `python -c "import main; print('OK')"` && `pytest tests/ -v` — all tests pass
- [ ] **PUSH** — `git push origin main` → Railway auto-deploys
