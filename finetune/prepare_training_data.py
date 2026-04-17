"""
prepare_training_data.py
========================
Converts the 100 finetune_v2 samples into a training JSONL file
that the training script (train_lora.py) can load directly.

Each training example teaches the model the REDUCE step:
  [system]  reduce instruction
  [user]    simulated MAP facts (reconstructed from document fields)
  [assistant] the target JSON output

Run on either laptop or main PC — only needs Python + the finetune_v2 folder.
No GPU needed.

Usage:
    python prepare_training_data.py
Output:
    training_data.jsonl  (in this folder)
"""

import json
import os
import re
from pathlib import Path

# ── paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).parent
SAMPLES_DIR  = SCRIPT_DIR.parent / "finetune_v2"
OUTPUT_FILE  = SCRIPT_DIR / "training_data.jsonl"

# ── reduce system prompt (same logic as main.py, trimmed for training) ───────
SYSTEM_PROMPT = """Ты — строгий JSON-генератор. Заполни шаблон ниже, используя ТОЛЬКО текст из раздела ФАКТЫ.

═══ ЗАПРЕТЫ ═══
• ЗАПРЕЩЕНО вписывать любой текст, которого нет в ФАКТАХ.
• ЗАПРЕЩЕНО оставлять поле "text" пустой строкой "".
• Нет данных → пиши "Данные отсутствуют".

═══ КАК ЗАПОЛНЯТЬ ═══
Для каждого элемента массива (goals, requirements, team, risks):
  — найди в ФАКТАХ строку, относящуюся к этой теме
  — скопируй содержание дословно в поле "text"
  — укажи реальный файл и строку в "source"

BUDGET/TIMELINE конфликт: если найдено ≥2 разных значений →
  "has_conflict": true, "conflict_details": "Конфликт: файл1, [N] — значение1; файл2, [M] — значение2"

Выведи ТОЛЬКО валидный JSON без текста до или после."""

# ── helpers ──────────────────────────────────────────────────────────────────

def _field_to_facts(field_name: str, value, line_counter: list) -> list[str]:
    """
    Convert a single document field back into simulated MAP fact lines.
    line_counter is a mutable [int] used to keep numbering consistent.
    """
    facts = []

    def next_line():
        n = line_counter[0]
        line_counter[0] += 1
        return n

    if isinstance(value, str):
        if value and not value.startswith("Данные"):
            facts.append(f"[{next_line()}] Факт: \"{value}\"")

    elif isinstance(value, dict):
        text   = value.get("text", "")
        source = value.get("source", "")
        if text and not text.startswith("Данные"):
            src_hint = f" (из {source})" if source else ""
            facts.append(f"[{next_line()}] Факт: \"{text}\"{src_hint}")
        # Also add conflict raw values as separate fact lines
        cd = value.get("conflict_details", "")
        if cd:
            for part in re.split(r";\s*", cd.replace("Конфликт:", "").strip()):
                part = part.strip()
                if part:
                    facts.append(f"[{next_line()}] Факт (конфликт): \"{part}\"")

    elif isinstance(value, list):
        for item in value:
            facts.extend(_field_to_facts(field_name, item, line_counter))

    return facts


def document_to_map_facts(doc: dict) -> str:
    """
    Reconstruct a realistic MAP facts block from a finished document.
    Groups facts roughly by their source file.
    """
    # Collect all (source_file, fact_line) pairs
    by_file: dict[str, list] = {}
    lc = [1]

    field_order = [
        "project_overview", "goals", "requirements",
        "technical_solution", "architecture", "team",
        "timeline", "budget", "risks"
    ]

    for field in field_order:
        value = doc.get(field)
        if value is None:
            continue

        # Determine source file(s) for this field
        source_files = set()
        if isinstance(value, dict):
            src = value.get("source", "")
            for s in re.split(r"[,\s]+и\s+", src):
                fname = re.sub(r",?\s*\[\d+.*?\]", "", s).strip()
                if fname:
                    source_files.add(fname)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    src = item.get("source", "")
                    for s in re.split(r"[,\s]+и\s+", src):
                        fname = re.sub(r",?\s*\[\d+.*?\]", "", s).strip()
                        if fname:
                            source_files.add(fname)

        if not source_files:
            source_files = {"document.txt"}

        facts = _field_to_facts(field, value, lc)
        primary = sorted(source_files)[0]
        by_file.setdefault(primary, []).extend(facts)

    # Format into --- ФАЙЛ: --- blocks
    blocks = []
    for fname, lines in by_file.items():
        if lines:
            blocks.append(f"\n--- ФАЙЛ: {fname} ---\n" + "\n".join(lines))

    return "\n".join(blocks)


def doc_to_output_json(doc: dict) -> str:
    """
    Build the assistant target JSON from the document.
    Uses the rich {text, source, has_conflict, conflict_details} format
    since that's what the model currently outputs (it matches reduce prompt).
    """
    def clean(val):
        """Recursively strip metadata keys we don't want in training target."""
        if isinstance(val, dict):
            return {k: clean(v) for k, v in val.items()}
        if isinstance(val, list):
            return [clean(i) for i in val]
        return val

    target = {
        "project_overview":   doc.get("project_overview", ""),
        "goals":              doc.get("goals", []),
        "requirements":       doc.get("requirements", []),
        "technical_solution": doc.get("technical_solution", {}),
        "architecture":       doc.get("architecture", {}),
        "team":               doc.get("team", []),
        "timeline":           doc.get("timeline", {}),
        "budget":             doc.get("budget", {}),
        "risks":              doc.get("risks", []),
    }
    return json.dumps(clean(target), ensure_ascii=False, indent=2)


def sample_to_training_row(sample: dict) -> dict:
    """
    Convert one finetune_v2 sample → one ChatML training dict.
    """
    doc = sample.get("document", {})
    map_facts = document_to_map_facts(doc)
    target_json = doc_to_output_json(doc)

    return {
        "messages": [
            {"role": "system",    "content": SYSTEM_PROMPT},
            {"role": "user",      "content": f"Факты:{map_facts}"},
            {"role": "assistant", "content": target_json},
        ]
    }


# ── main ─────────────────────────────────────────────────────────────────────
def main():
    if not SAMPLES_DIR.exists():
        print(f"ERROR: samples folder not found at {SAMPLES_DIR}")
        print("Run setup_v2.py first to generate the 100 samples.")
        return

    sample_files = sorted(SAMPLES_DIR.glob("sample_*.json"))
    print(f"Found {len(sample_files)} samples in {SAMPLES_DIR}")

    rows = []
    skipped = 0
    for path in sample_files:
        with open(path, encoding="utf-8") as f:
            sample = json.load(f)
        doc = sample.get("document", {})
        if not doc or "error" in doc:
            skipped += 1
            continue
        rows.append(sample_to_training_row(sample))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"Written {len(rows)} training rows  →  {OUTPUT_FILE}")
    if skipped:
        print(f"Skipped {skipped} samples with errors")

    # Quick sanity check
    print("\nSample preview (first example, assistant output truncated):")
    print("  USER (first 200 chars):", rows[0]["messages"][1]["content"][:200])
    print("  ASSISTANT (first 200 chars):", rows[0]["messages"][2]["content"][:200])


if __name__ == "__main__":
    main()
