# NeuralDocs AI
Status: Public release shipped (Groq + LM Studio dual-mode, SSE, llm-guard, session archive). Awaiting Railway deploy.
Date: 2026-05-16

## Approach
NeuralDocs AI is an Applied LLM / RAG application that extracts structured project specifications from chaotic documents (PDFs, code, docs) using either **Groq cloud LLM** (public demo) or **LM Studio local LLM** (self-hosted). It automatically detects contradictions across files. Output is always in English regardless of source language.

## Current Structure
- `app/api/routes.py` (FastAPI routes — SSE `/generate_document`, session-scoped archive)
- `app/services/` (`llm_provider.py` MAP-REDUCE, `sanitizer.py`, `export_service.py`)
- `app/utils/` (Document parsers + `project_name.py` extractor)
- `app/frontend/index.html` (single-file SPA — SSE reader, no timers)
- `main.py` (FastAPI entrypoint + 24h session cleanup task)
- `tests/test_public_release.py` (security scan, get_session_dir, model auto-detect tests)
- `tests/test_project_name_extraction.py`
- `tests/dummy_data/{session_id}/` (per-session archive folders, 24h TTL)
- `railway.toml` + `Dockerfile` (deploy config)
- `docs/superpowers/specs/`, `docs/superpowers/plans/`

## Session Notes (2026-05-16) — Public Release

### Phase/Status Changes
- **Public release scope shipped** (9 tasks, 11 commits, all spec+quality reviewed): Groq integration, LM Studio model auto-detect, llm-guard prompt injection protection, session-based archive with 24h cleanup, SSE streaming backend + frontend (timers DELETED), full English output, conflict resolved-state persistence, Railway/Dockerfile config + README.
- Plan: `docs/superpowers/plans/2026-05-16-public-release.md`. Spec: `docs/superpowers/specs/2026-05-16-public-release-design.md`.
- All 14 tests pass.

### Key Decisions / Insights
| Decision | Rationale |
|---|---|
| Provider selection via `GROQ_API_KEY` env var (routes.py) | If set → Groq with `llama-3.3-70b-versatile`; else → LM Studio with `model_name=None` (auto-detect via `/v1/models`). `LocalProvider.__init__` now accepts `api_key` param. |
| `_get_loaded_model()` queries LM Studio at request time | Avoids hardcoding model name. Falls back to `"local-model"` if `/v1/models` fails. Resolved once per pipeline run, threaded through closures as local `model` var. |
| llm-guard: `BanSubstrings` substituted for `PromptInjection` on Python 3.14 | `PromptInjection` needs `transformers==4.38.2` which segfaults on Py 3.14. `BanSubstrings` with 7 phrase blocklist gives deterministic injection protection. Swap back to `PromptInjection()` in `routes.py` when Docker (Py 3.11) is used. |
| Session archive: `tests/dummy_data/{session_id}/` | Frontend generates UUID v4 in `localStorage('nd_session_id')`, sends as `X-Session-Id` header. Backend's `get_session_dir(request)` validates UUID regex (`^[a-f0-9-]{36}$`) and falls back to `"default"` on invalid input — blocks path traversal. |
| 24h cleanup: `@app.on_event("startup")` in main.py | Async task wakes hourly, `shutil.rmtree`s subdirs older than 86400s. Deprecated decorator but functional; lifespan migration is future work. |
| SSE: `loop.run_in_executor()` + `asyncio.Queue` + `call_soon_threadsafe()` | LLM pipeline is sync (uses ThreadPoolExecutor for MAP). On_phase callback bridges sync thread → async generator via thread-safe queue puts. 0.5s drain timeout. |
| All frontend timers DELETED (`progressInterval`, `reduceTimeout`, `setInterval`, nested `setTimeout`) | Replaced by SSE event-driven `setPhase(PHASE_TO_STEP[eventData])` + `setPipelineGhost(eventData)`. PHASE_TO_STEP: `{Parsing: 0, Mapping: 1, Reducing: 2, Finalising: 3}`. Eliminates Sprint 4 stale-timer bug class entirely. |
| Conflict resolved-state in `currentRawData.document_extended[key].resolved` | `markConflictResolved()` writes `resolved=true` via `window._activeConflictKey/_activeConflictIdx`. `makeFact`/`makeFactList` skip resolved items. Badge count derived from `countUnresolvedConflicts()`, not DOM. Ephemeral (lost on reload) — archive JSON persistence is future work. |
| English output: `_lang_rule` + Cyrillic detection (`_doc_is_russian`) DELETED from `llm_provider.py` | REDUCE prompt always says "Output in English, translate naturally if source is another language". MAP stays language-agnostic. All Russian fallback strings (`"Нет данных"`, `"данные отсутствуют"`, etc.) → English equivalents. NON_DATA / NON_DATA_LC sets are English-only. |

### Next Steps
1. **Push + Deploy:** `git push origin main` → Railway: create project → set `GROQ_API_KEY` → deploy → add live URL to README.md placeholder.
2. **Swap `BanSubstrings` → `PromptInjection()` in `routes.py`** once running on Docker/Py 3.11 (gives ML-based detection vs phrase blocklist).
3. **Lifespan migration:** `@app.on_event("startup")` is deprecated in FastAPI 0.95+ — migrate to `lifespan=` context manager.
4. **Conflict resolved-state archive persistence:** Currently in-memory only. Persist to archive JSON if cross-session continuity desired.
5. **Rebuff** as a second security layer (vector DB of attack patterns + LLM classifier) — deferred from this release.
6. **Wire disabled checkboxes** ("Deep conflict scan", "Cite passages") once backend params are defined.
7. **⌘K command palette / header search** when reintroduced (was removed in Sprint 4).

---

## Session Notes (2026-05-13)

### Phase/Status Changes
- v2 UI design implemented and validated end-to-end.
- **Sprint 1 (8 bugs)** shipped: archive badge, archive auto-save, conflict modal resolve, conflict source parsing, PDF emoji removal, stepper phase decoupling, removed bottom nav pill, breadcrumb label.
- **Sprint 2 (4 UX)** shipped: breadcrumb reset, archive cache invalidation, live in-progress ghost row in archive, project name everywhere (archive grid + breadcrumb + download filenames).
- **Sprint 3 (5 fixes + pill + LLM name)** shipped: stale token display cleared on view-switch; ghost row renders immediately + survives empty `/api/samples` response; archive items locked during pipeline (redirect to processing); Cancel button now clears pipeline state; **floating progress pill** persists across views; **LLM-derived `project_name`** field replaces first-sentence heuristic.
- **Sprint 4 (ghost-row resurrection hunt)** shipped: logo button clickable + accessible (`type="button" aria-label` + `text-left` to override browser UA `text-align: center` on `<button>`); `clearPipelineGhost()` resets `allArchiveFiles=[]` + `archiveLoading=false`; `loadArchiveList()` resets `archiveLoading` in empty-data branch + clears `grid.innerHTML=''` synchronously before `await fetch`; **root-cause fix: nested `setTimeout` inside `setInterval` cancelled via tracked `reduceTimeout` ID** (was resurrecting `pipelineGhost` 3s after pipeline ended); decorative header search bar removed.
- Disabled unused checkboxes ("Deep conflict scan", "Cite passages") with "Soon" badges.

### Key Decisions / Insights
| Decision | Rationale |
|---|---|
| Backend auto-saves analysis to `tests/dummy_data/` as `analysis_{ts}_{uuid6}.json` | Archive must populate after each run; that folder *is* the archive. |
| Backend injects `metadata.project_name` via `app/utils/project_name.py` three-tier fallback | Tier 1: LLM-produced `document.project_name` (REDUCE schema field, 2–6 words). Tier 2: first sentence of `project_overview`. Tier 3: `Analysis {date}`. Tested in `tests/test_project_name_extraction.py`. |
| `pipelineRunning` flag gates archive-item clicks + drives floating pill | Set true before `go('processing')` in form submit, cleared in `clearPipelineGhost()` (called from success path, error path, AND Cancel button). `loadSampleByName()` early-returns to processing view when flag is true. |
| Floating `#progress-pill` (bottom-right, 272px, fixed) | Shown via `classList.toggle('pill-visible', pipelineRunning && name !== 'processing')` inside `go()`. Phase label updated by `setPipelineGhost()`. Hidden by `clearPipelineGhost()`. CSS `display: none` default + `.pill-visible { display: flex }`. |
| Empty `/api/samples` response must NOT hide ghost row | Backend saves archive file at pipeline END, so `/api/samples` returns `[]` for the entire pipeline duration. Both the empty-data branch and catch block in `loadArchiveList()` guard `emptyState.style.display = ''` with `if (!pipelineGhost)`. |
| Conflict details format from LLM: `file1: "v1" \| file2: "v2"` (pipe-separated) | Frontend `parseConflictDetails` tries pipe format first, falls back to legacy `file, [N] — value` regex. |
| DejaVu fonts have **no emoji glyphs** | Never use emojis in `export_service.py` PDF strings — they render as boxes. Use text-only. |
| Stepper phases driven by **explicit events**, not file-scan % | `setPhase(0..3)` called at Parsing→Mapping→Reducing→Finalizing transitions. File scan % only updates ring/bar. |
| Live ghost row in archive during pipeline | `pipelineGhost = { phase }` state + `setPipelineGhost/clearPipelineGhost` re-render archive grid if visible. Replaces header-pill idea. |
| `let allArchiveFiles` cleared in handlers, **NOT inside `go()`** | TDZ gotcha: `go('upload')` runs at page load before `let allArchiveFiles = []` is reached → ReferenceError kills script. Clear in `reset-btn`, `load-another-btn`, navTabs listener instead. |
| `clearInterval` does NOT cancel inner `setTimeout`s scheduled inside the interval callback | Sprint 4 ghost-row bug spent 3 attempts chasing the wrong layer. Real cause: `setTimeout(() => setPipelineGhost('Reducing conflicts…'), 3000)` inside the file-scan interval fired AFTER `clearPipelineGhost()`, resurrecting `pipelineGhost`. Fix: track inner timer in `reduceTimeout` and `clearTimeout` it everywhere `clearInterval(progressInterval)` is called. **Rule:** any nested timer scheduled inside a longer-running timer must be tracked separately and cancelled explicitly. |
| `<button>` text alignment | Browser UA stylesheet sets `text-align: center` on `<button>` and Tailwind Preflight does NOT reset it. Add `text-left` to any button containing left-aligned text content. |

### v2 Design Reference
- Design system: `@theme` CSS vars (ink/mute/line/canvas/brand/warn/ok) + JS-driven SVG icon templates hydrated via `[data-icon]`.
- Critical class names (used by JS): `.fp-item`, `.fp-check`, `.fp-spinner`, `.fp-dot`, `.stepper-step` (`complete`/`active`/`pending`), `.ar-row-item`, `.modal-panel`, `.diff-box`, `.conflict-inline`, `.conflict-banner`, `.result-section`, `.source-badge`, `.tab-active`.

### Plans
- `docs/superpowers/plans/2026-05-13-ui-bug-fixes.md` — Sprint 1 (8 tasks, all done)
- `docs/superpowers/plans/2026-05-13-ux-polish-sprint2.md` — Sprint 2 (4 tasks, all done)
- `docs/superpowers/specs/2026-05-13-sprint3-ux-bugs-progress-pill.md` + `docs/superpowers/plans/2026-05-13-sprint3-ux-bugs-progress-pill.md` — Sprint 3 (7 tasks, all done)
- `docs/superpowers/plans/2026-05-13-logo-click-ghost-row-fix.md` — Sprint 4 first wave: logo clickable + archive cache reset (3 tasks done)
- `docs/superpowers/plans/2026-05-13-logo-align-archive-stale-dom.md` — Sprint 4 second wave: logo `text-left` + `grid.innerHTML=''` pre-clear (2 tasks done). Stale-`setTimeout` root-cause fix landed direct (no plan).

### Next Steps
1. **Docker rebuild + full smoke test** required for Sprint 3 backend changes (`llm_provider.py` REDUCE schema/prompt + `routes.py` extraction + new `app/utils/project_name.py`).
2. **Conflict resolved-state persistence:** "Mark as resolved" currently only hides DOM + decrements counter; doesn't persist. Decide whether to track per-conflict resolved state in `currentRawData`.
3. **Share / Copy link** buttons in Results header — defer until login/auth lands.
4. **Wire the disabled checkboxes** ("Deep conflict scan", "Cite passages") to real backend params when scope is clear.
5. **Pipeline ghost row + pill phase** are timer-based (Mapping after all files scanned, Reducing 3s later). Sprint 4 fixed the stale-timer resurrection bug but the underlying drift remains — consider SSE/streaming from `/generate_document` to drive real phase events for both the ghost row and the floating pill.
6. **`datetime.utcnow()` deprecation in `routes.py`** — new `project_name.py` uses `datetime.now(timezone.utc)`; the rest of `routes.py` still has `.utcnow()` calls that should migrate before Python 3.14 makes it a hard error.
7. **Header search bar / ⌘K command palette** — removed in Sprint 4 (was decorative). When reintroduced, decide scope: command palette for view navigation vs. global search across archive analyses. Needs design pass before rebuild.
