# NeuralDocs AI
Status: v2 validated, UX polish Sprint 1+2+3+4 shipped
Date: 2026-05-13

## Approach
NeuralDocs AI is an Applied LLM / RAG application that extracts structured project specifications from chaotic documents (PDFs, code, docs) using a local LLM via LM Studio. It automatically detects contradictions across files.

## Current Structure
- `app/api/` (API Routes)
- `app/services/` (LLM logic, sanitizer, export)
- `app/utils/` (Document parsers + `project_name.py` extractor)
- `app/frontend/index.html` (single-file SPA — v2 design)
- `main.py` (FastAPI Entrypoint)
- `tests/dummy_data/` (Sample data files)
- `tests/test_project_name_extraction.py` (pytest unit tests)
- `docs/` (Schemas, etc.)

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
