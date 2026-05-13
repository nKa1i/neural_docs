from datetime import datetime, timezone


def extract_project_name(result: dict) -> str:
    """
    Derive a human-readable project name from an LLM result dict.

    Fallback chain:
      1. result["document_extended"]["project_name"]  (LLM-produced)
      2. First sentence of project_overview            (legacy)
      3. "Analysis DD Mon YYYY"                        (date fallback)
    """
    doc_data = result.get("document_extended") or result.get("document") or {}

    # Tier 1: explicit project_name from LLM
    llm_name = (doc_data.get("project_name") or "").strip()[:50]

    # Tier 2: first sentence of project_overview
    if not llm_name:
        overview = doc_data.get("project_overview") or ""
        if isinstance(overview, dict):
            overview = overview.get("text") or ""
        llm_name = overview.split(".")[0].strip()[:50] if overview else ""

    # Tier 3: date fallback
    return llm_name if llm_name else f"Analysis {datetime.now(timezone.utc).strftime('%d %b %Y')}"
