# NeuralDocs AI
Status: Architectural Refactoring Planned
Date: 2026-05-10

## Approach
NeuralDocs AI is an Applied LLM / RAG application that extracts structured project specifications from chaotic documents (PDFs, code, docs) using a local LLM via LM Studio. It automatically detects contradictions across files.

## Session Notes (2026-05-10)

### Phase/Status Changes
- Completed project discovery and analysis.
- Confirmed the project is a strong "Option 1" (Applied LLM) candidate for portfolio building.
- Created and approved an implementation plan to refactor the monolithic `main.py`.

### Key Decisions
| Decision | Rationale |
|---|---|
| Modularize `main.py` | 137KB file is too large to maintain or show to employers. Must be split into standard MVC/API architecture. |
| Isolate Dummy Data | Move `company_projects/`, `budget_draft.txt`, etc., to `tests/dummy_data/` to keep root clean. |
| Extract Frontend | Move HTML/JS/CSS out of `main.py` strings and into `app/frontend/` static files. |
| Preserve Plan | Saved this context to `CLAUDE.md` so the work can be seamlessly resumed in a new dedicated workspace. |

### Planned Structure (To be executed in new workspace)
- `app/api/routes.py`
- `app/services/llm_provider.py`
- `app/services/sanitizer.py`
- `app/utils/parsers.py`
- `app/frontend/index.html`
- `main.py` (entrypoint only)
- `tests/dummy_data/`

### Next Steps
1. Move `D:\digital_farabi` to a dedicated workspace.
2. Follow the implementation plan to perform the file cleanup.
3. Slice `main.py` into the planned directories.
4. Verify the API and frontend still work.
