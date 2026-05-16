import os
import re
import time
import json
from concurrent.futures import ThreadPoolExecutor
from openai import OpenAI
from app.utils.parsers import extract_text

# Path to the pre-generated samples archive (in the same folder as this file)
SAMPLES_DIR = os.path.join(os.getcwd(), "tests/dummy_data")

class LLMProvider:
    def generate_document(self, files_data: list[dict]) -> dict:
        pass

# --- ЛОКАЛЬНЫЙ ПРОВАЙДЕР С ЖЕСТКОЙ ДЕТЕРМИНИРОВАННОСТЬЮ ---
class LocalProvider(LLMProvider):
    def __init__(self, base_url: str, model_name: str = None, api_key: str = "lm-studio-local"):
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model_name = model_name  # None = auto-detect via /v1/models

    def _get_loaded_model(self) -> str:
        """Query LM Studio /v1/models and return the first loaded model ID."""
        try:
            models = self.client.models.list()
            if models.data:
                return models.data[0].id
        except Exception:
            pass
        return "local-model"

    def generate_document(self, files_data: list[dict], language: str = "en", on_phase=None, on_file=None) -> dict:
        def emit(phase: str):
            if on_phase:
                on_phase(phase)

        # Resolve model name — auto-detect from LM Studio if not set at init
        model = self.model_name if self.model_name else self._get_loaded_model()
        start_time = time.time()
        total_tokens_used = 0

        # ── LM Studio warmup / unpoisoning ─────────────────────────────────
        # LM Studio has a bug: once a json_schema is used, it caches it and
        # applies it to ALL subsequent requests (even those without response_format).
        # Sending a trivial schema here resets the cached grammar to something harmless.
        try:
            _warmup_schema = {
                "type": "json_schema",
                "json_schema": {
                    "name": "warmup",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"ok": {"type": "string"}},
                        "required": ["ok"],
                        "additionalProperties": False
                    }
                }
            }
            self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "ok"}],
                response_format=_warmup_schema,
                temperature=0.0,
                max_tokens=5
            )
        except Exception:
            pass  # If warmup fails, proceed anyway

        # ── Change 2: Schema-guided MAP ───────────────────────────────────────
        # MAP now outputs a compact JSON keyed by the 9 schema fields instead of
        # free-form "[N] Факт: ..." lines.  Python merges all chunk JSONs, detects
        # budget/timeline conflicts deterministically, then feeds a concise
        # structured fact list to the REDUCE LLM call.  Benefits:
        #  • Model only writes facts that map to a known field → zero noise tokens
        #  • Conflict detection is exact (Python string comparison), not guessed
        #  • REDUCE prompt is shorter → more room for the actual content
        MAP_CHUNK_CHARS  = 4_000   # chars per MAP call (≈ 1 500 tokens) — smaller
        #                            gives json_schema grammar more VRAM headroom
        REDUCE_MAX_CHARS = 5_000   # merged fact list cap for REDUCE

        SCHEMA_FIELDS_LIST   = ["goals", "requirements", "team", "risks"]
        SCHEMA_FIELDS_SCALAR = ["technical_solution", "architecture", "timeline", "budget"]

        map_instruction = """\
You are a structured fact extractor. Read the document chunk and output ONLY a JSON object \
with the fields below. Include ONLY fields you find clear evidence for — omit the rest entirely.

{
  "goals":              ["<project goal or objective — copy text exactly>"],
  "requirements":       ["<functional or technical requirement — copy text exactly>"],
  "technical_solution": "<programming languages, frameworks, engines, databases — copy exactly>",
  "architecture":       "<system design, components, deployment — copy exactly>",
  "team":               ["<any person, role, or team member mentioned — copy exactly>"],
  "timeline":           "<any duration, deadline, or timeframe mentioned — copy exactly>",
  "budget":             "<any monetary amount or cost mentioned — copy exactly>",
  "risks":              ["<any risk, problem, or concern mentioned — copy exactly>"]
}

Rules:
• ⚠️ DO NOT TRANSLATE. Copy text EXACTLY as it appears in the source. \
If the source text is in Russian — output Russian. \
If the source text is in English — output English. \
Never convert Russian words to English or English words to Russian.
• If a field has no evidence in this chunk, output an empty string "" (for strings) or an empty array [] (for lists).
• Output ONLY the JSON object — no markdown fences, no commentary.
• IMPORTANT: If the chunk starts with [SOURCE CODE], only extract technical_solution \
and architecture from it. Function names and method signatures are NOT goals or requirements."""

        def _parse_map_output(raw: str) -> dict:
            """Try to parse the MAP JSON; return {} on any failure."""
            s = raw.find("{"); e = raw.rfind("}")
            if s == -1 or e == -1:
                return {}
            snippet = raw[s:e+1]
            try:
                return json.loads(snippet)
            except Exception:
                # Strip trailing commas (common small-model mistake) and retry
                cleaned = re.sub(r",\s*([}\]])", r"\1", snippet)
                try:
                    return json.loads(cleaned)
                except Exception:
                    return {}

        # ── Structured-output schemas ──────────────────────────────────────────
        # LM Studio supports OpenAI-compatible response_format.
        # "json_object"  → llama.cpp JSON grammar: always valid JSON, no fences.
        # "json_schema"  → token-level GBNF grammar: forces exact field names +
        #                  types (LM Studio 0.3.5+).  We try json_schema first for
        #                  REDUCE and fall back to json_object if the server rejects
        #                  it (older LM Studio versions).

        # MAP schema: strict enforcement of fields
        _MAP_RESPONSE_FORMAT = {
            "type": "json_schema",
            "json_schema": {
                "name": "map_chunk",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "goals":              {"type": "array", "items": {"type": "string"}},
                        "requirements":       {"type": "array", "items": {"type": "string"}},
                        "technical_solution": {"type": "string"},
                        "architecture":       {"type": "string"},
                        "team":               {"type": "array", "items": {"type": "string"}},
                        "timeline":           {"type": "string"},
                        "budget":             {"type": "string"},
                        "risks":              {"type": "array", "items": {"type": "string"}}
                    },
                    "required": [
                        "goals", "requirements", "technical_solution",
                        "architecture", "team", "timeline", "budget", "risks"
                    ],
                    "additionalProperties": False
                }
            }
        }

        # Shared shape for a single fact entry (used in list + scalar fields)
        _FACT_ITEM = {
            "type": "object",
            "properties": {
                "text":             {"type": "string"},
                "source":           {"type": "string"},
                "has_conflict":     {"type": "boolean"},
                "conflict_details": {"type": "string"}
            },
            "required": ["text", "source", "has_conflict", "conflict_details"],
            "additionalProperties": False
        }

        # REDUCE schema: all 9 fields always present, correct types enforced
        _REDUCE_RESPONSE_FORMAT = {
            "type": "json_schema",
            "json_schema": {
                "name": "project_spec",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "project_name":       {"type": "string"},
                        "project_overview":   {"type": "string"},
                        "goals":              {"type": "array",  "items": _FACT_ITEM},
                        "requirements":       {"type": "array",  "items": _FACT_ITEM},
                        "technical_solution": _FACT_ITEM,
                        "architecture":       _FACT_ITEM,
                        "team":               {"type": "array",  "items": _FACT_ITEM},
                        "timeline":           _FACT_ITEM,
                        "budget":             _FACT_ITEM,
                        "risks":              {"type": "array",  "items": _FACT_ITEM}
                    },
                    "required": [
                        "project_name", "project_overview", "goals", "requirements",
                        "technical_solution", "architecture",
                        "team", "timeline", "budget", "risks"
                    ],
                    "additionalProperties": False
                }
            }
        }

        def _map_chunk(filename, lines, line_offset):
            """Send one chunk to the LLM; return (parsed_dict, token_count)."""
            numbered = "\n".join(
                f"[{line_offset+i+1}] {ln}" for i, ln in enumerate(lines)
            )
            try:
                # Attempt with response format first
                resp = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": map_instruction},
                        {"role": "user",   "content": f"File: {filename}\n\n{numbered}"}
                    ],
                    response_format=_MAP_RESPONSE_FORMAT,
                    temperature=0.0
                )
            except Exception as e:
                # If LM Studio is "poisoned" or rejects the schema, retry without it
                print(f"Warning: Map schema rejected for {filename}, retrying without schema...")
                try:
                    resp = self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": map_instruction},
                            {"role": "user",   "content": f"File: {filename}\n\n{numbered}"}
                        ],
                        temperature=0.0
                    )
                except Exception as retry_e:
                    import traceback
                    print(f"Map chunk completely failed for {filename}:")
                    traceback.print_exc()
                    return {}, 0
            tokens = resp.usage.total_tokens if resp.usage else 0
            parsed = _parse_map_output(resp.choices[0].message.content)
            # Normalise: wrap accidental scalar in list where list is expected
            for key in SCHEMA_FIELDS_LIST:
                if key in parsed and isinstance(parsed[key], str):
                    parsed[key] = [parsed[key]]
            return parsed, tokens

        def _map_one(f):
            lines = f["content"].splitlines()
            # Split into context-safe chunks
            chunks, cur, cur_len, offset = [], [], 0, 0
            for i, line in enumerate(lines):
                ll = len(line) + 1
                if cur_len + ll > MAP_CHUNK_CHARS and cur:
                    chunks.append((cur, offset))
                    offset = i
                    cur, cur_len = [], 0
                cur.append(line)
                cur_len += ll
            if cur:
                chunks.append((cur, offset))

            file_dicts, total_tokens = [], 0
            for idx, (chunk_lines, line_offset) in enumerate(chunks):
                start_ln = line_offset + 1
                end_ln   = line_offset + len(chunk_lines)
                label = (f"{f['filename']} (lines {start_ln}–{end_ln})"
                         if len(chunks) > 1 else f['filename'])
                d, tok = _map_chunk(label, chunk_lines, line_offset)
                if d:
                    d["_source"] = label
                file_dicts.append(d)
                total_tokens += tok
            return f["filename"], file_dicts, total_tokens

        # ── Run MAP sequentially (avoids OOM on CPU inference) ────────────────
        emit("Mapping documents…")
        map_results = []
        total_files = len(files_data)
        for i, f in enumerate(files_data):
            result = _map_one(f)
            map_results.append(result)
            if on_file:
                on_file(result[0], i + 1, total_files)

        emit("Reducing conflicts…")
        # ── Python merge: combine all chunk dicts ─────────────────────────────
        # List fields → extend; scalar fields → collect all distinct values
        # (multiple distinct budget/timeline values = conflict evidence)
        merged: dict = {k: [] for k in SCHEMA_FIELDS_LIST + SCHEMA_FIELDS_SCALAR}
        for filename, chunk_dicts, tokens in map_results:
            total_tokens_used += tokens
            for d in chunk_dicts:
                src = d.get("_source", filename)
                for key in SCHEMA_FIELDS_LIST:
                    if key in d and isinstance(d[key], list):
                        for item in d[key]:
                            if item and str(item).strip():
                                merged[key].append({"text": str(item), "source": src})
                for key in SCHEMA_FIELDS_SCALAR:
                    if key in d and d[key]:
                        val = d[key]
                        # MAP sometimes returns a list for a scalar field
                        # (e.g. when the model finds multiple values in the chunk).
                        # Join them into a single string rather than repr-ing the list.
                        if isinstance(val, list):
                            val = "; ".join(
                                str(v).strip() for v in val if str(v).strip()
                            )
                        elif not isinstance(val, str):
                            val = str(val)
                        val = val.strip()
                        if val:
                            merged[key].append({"text": val, "source": src})

        # ── Change 4: Regex pre-extraction ────────────────────────────────────
        # Scan every file's parsed text with regex patterns for the three fields
        # most likely to be missed or garbled by the LLM (budget, timeline, team).
        # Regex hits are added to `merged` so Python conflict detection sees them
        # alongside whatever the MAP phase found.  No LLM call — 100% reliable
        # for clearly formatted numeric/structured values.

        # Normalise a monetary string: collapse whitespace, unify currency symbols
        def _norm_money(s: str) -> str:
            s = re.sub(r"\s+", " ", s.strip())
            s = re.sub(r"тнг\b", "тенге", s, flags=re.IGNORECASE)
            return s

        # Regex patterns — each tuple: (compiled_pattern, group_index, field)
        BUDGET_RES = [
            # "30 000 000 тенге" / "30000000 ₸"  — require at least 4 digits total
            re.compile(r"\b(\d[\d\s]{3,}\s*(?:тенге|тнг|₸))", re.IGNORECASE),
            # "$4,200,000" / "$ 4 200 000" — stop before ". N." list-item suffixes
            re.compile(r"(\$\s*\d[\d\s]*\d)(?!\s*[,\s]*\d{3,})(?=\D|$)", re.IGNORECASE),
            # "4 200 000 usd/eur/руб"
            re.compile(r"\b(\d[\d\s]{3,}\s*(?:usd|eur|руб\.?|rub))\b", re.IGNORECASE),
            # "бюджет: X" / "budget: X" — grab rest of line only if it contains a digit
            re.compile(r"(?:бюджет|budget)\s*[:\-]\s*(\d[^\n]{2,40})", re.IGNORECASE),
        ]

        TIMELINE_RES = [
            # "20 месяцев" / "6 мес." / "12 months"
            re.compile(r"\b(\d+\s*(?:месяц(?:ев|а)?|мес\.?|month|months|week|weeks))\b", re.IGNORECASE),
            # "Q2 2026" / "Q4 2025"
            re.compile(r"\b(Q[1-4]\s*20\d{2})\b", re.IGNORECASE),
            # ISO date "2026-03-15" or "15.03.2026"
            re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b"),
            re.compile(r"\b(\d{2}\.\d{2}\.20\d{2})\b"),
            # "через X месяцев / лет"
            re.compile(r"(через\s+\d+\s*(?:месяц\w*|нед\w*|год\w*|лет))", re.IGNORECASE),
        ]

        TEAM_RES = [
            # "2 iOS-разработчика" / "3 developer" / "5 engineers"
            re.compile(
                r"\b(\d+\s*(?:iOS|Android|бэкенд|backend|frontend|разработчик\w*|"
                r"developer|engineer|designer|qa|тестировщик\w*|продакт\w*|аналитик\w*|"
                r"devops|архитектор\w*))",
                re.IGNORECASE,
            ),
            # "Имя: Роль" or "Name — role" informal lines
            re.compile(r"^[-•*]\s*(.{5,60})\s*[:\-–—]\s*(.{3,40})$", re.MULTILINE),
        ]

        already_in_merged: dict = {
            "budget":   {re.sub(r"\s+", " ", e["text"].lower()) for e in merged["budget"]},
            "timeline": {re.sub(r"\s+", " ", e["text"].lower()) for e in merged["timeline"]},
            "team":     {re.sub(r"\s+", " ", e["text"].lower()) for e in merged["team"]},
        }

        for f in files_data:
            fname = f["filename"]
            text  = f["content"]

            # Budget
            for pat in BUDGET_RES:
                for m in pat.finditer(text):
                    val = _norm_money(m.group(1))
                    norm = re.sub(r"\s+", " ", val.lower())
                    # Skip if already present or too short / looks like noise
                    if norm in already_in_merged["budget"] or len(val) < 4:
                        continue
                    # Skip if it's clearly not a monetary value (e.g. plain word from бюджет: line)
                    if not re.search(r"\d", val):
                        continue
                    merged["budget"].append({"text": val, "source": fname})
                    already_in_merged["budget"].add(norm)

            # Timeline
            for pat in TIMELINE_RES:
                for m in pat.finditer(text):
                    val = m.group(1).strip()
                    norm = re.sub(r"\s+", " ", val.lower())
                    if norm in already_in_merged["timeline"] or len(val) < 3:
                        continue
                    merged["timeline"].append({"text": val, "source": fname})
                    already_in_merged["timeline"].add(norm)

            # Team
            for pat in TEAM_RES:
                for m in pat.finditer(text):
                    # Two-group pattern (name — role): groups == 2
                    if pat.groups == 2 and m.lastindex and m.lastindex >= 2:
                        try:
                            val = f"{m.group(1).strip()}: {m.group(2).strip()}"
                        except Exception:
                            val = m.group(0).strip()
                    else:
                        val = m.group(1).strip()
                    norm = re.sub(r"\s+", " ", val.lower())
                    if norm in already_in_merged["team"] or len(val) < 4:
                        continue
                    merged["team"].append({"text": val, "source": fname})
                    already_in_merged["team"].add(norm)

        # ── Python conflict detection (deterministic) ─────────────────────────
        # A real conflict = DIFFERENT VALUES in DIFFERENT FILES.
        # Multiple values from the same file are budget line items or milestone
        # dates — NOT contradictions.  We strip " (part N/M)" suffixes so that
        # different chunks of the same file are treated as the same source.
        def _base_src(source: str) -> str:
            """Return bare filename, stripping chunk labels like '(lines 1–80)' or '(part 2/4)'."""
            s = source.strip()
            s = re.sub(r"\s*\(lines\s+\d+[–\-]\d+\)\s*$", "", s)
            s = re.sub(r"\s*\(part\s+\d+/\d+\)\s*$", "", s)
            return s

        def _detect_conflict(entries: list) -> tuple:
            if len(entries) < 2:
                return False, ""

            # Keep one representative (longest) value per base file
            per_file: dict = {}   # base_src → best entry
            for e in entries:
                src = _base_src(e["source"])
                existing = per_file.get(src)
                if existing is None or len(e["text"]) > len(existing["text"]):
                    per_file[src] = e

            if len(per_file) < 2:
                return False, ""   # all values from the same file → no conflict

            # Check whether the per-file values actually differ
            norms = {re.sub(r"\s+", " ", e["text"].strip().lower())
                     for e in per_file.values()}
            if len(norms) < 2:
                return False, ""   # all files agree → no conflict

            parts = "; ".join(
                f'{src} — "{e["text"]}"' for src, e in per_file.items()
            )
            return True, f"Conflict: {parts}"

        budget_conflict,   budget_detail   = _detect_conflict(merged["budget"])
        timeline_conflict, timeline_detail = _detect_conflict(merged["timeline"])

        # ── Deduplicate scalar fields: one best value per source file ──────────
        # The regex extraction can add 5-6 budget line-items all from the same
        # file.  Passing all of them to REDUCE overwhelms the model and causes it
        # to write a complex dict/list as the budget value → broken JSON.
        # We keep the LONGEST (most informative) entry per base filename.
        for key in SCHEMA_FIELDS_SCALAR:
            if len(merged[key]) <= 1:
                continue
            per_file: dict = {}
            for e in merged[key]:
                src = _base_src(e["source"])
                cur = per_file.get(src)
                if cur is None or len(e["text"]) > len(cur["text"]):
                    per_file[src] = e
            merged[key] = list(per_file.values())

        # ── Build compact fact summary ─────────────────────────────────────────
        # Format: FIELD | source | value  (one line per entry)
        fact_lines = []
        for key in SCHEMA_FIELDS_LIST + SCHEMA_FIELDS_SCALAR:
            for e in merged[key]:
                fact_lines.append(f"{key} | {e['source']} | {e['text']}")
        all_extracted_facts = "\n".join(fact_lines)   # kept for hallucination check corpus

        # ── Change 3: Hierarchical REDUCE ─────────────────────────────────────
        # If the merged fact list fits in one REDUCE call → single pass (fast).
        # If it overflows (large projects like 11_omnicore_platform) → split into
        # groups, run one REDUCE LLM call per group to produce partial specs, then
        # merge the partial specs in Python.  No extra LLM call for the merge —
        # conflicts are already detected deterministically by Python above.

        conflict_hints = ""
        if budget_conflict:
            conflict_hints += f"\nBUDGET CONFLICT: {budget_detail}"
        if timeline_conflict:
            conflict_hints += f"\nTIMELINE CONFLICT: {timeline_detail}"

        json_template = """{
  "project_overview": "<1-2 sentence summary in English of what the project is>",
  "goals":        [{"text": "<fact text>", "source": "<source>", "has_conflict": false, "conflict_details": ""}],
  "requirements": [{"text": "<fact text>", "source": "<source>", "has_conflict": false, "conflict_details": ""}],
  "technical_solution": {"text": "<fact text>", "source": "<source>", "has_conflict": false, "conflict_details": ""},
  "architecture":       {"text": "<fact text>", "source": "<source>", "has_conflict": false, "conflict_details": ""},
  "team":    [{"text": "<fact text>", "source": "<source>", "has_conflict": false, "conflict_details": ""}],
  "timeline":     {"text": "<fact text>", "source": "<source>", "has_conflict": false, "conflict_details": ""},
  "budget":       {"text": "<fact text>", "source": "<source>", "has_conflict": false, "conflict_details": ""},
  "risks":   [{"text": "<fact text>", "source": "<source>", "has_conflict": false, "conflict_details": ""}]
}"""

        def _build_reduce_instruction(facts_text: str, include_conflicts: bool = True) -> str:
            hints = conflict_hints if include_conflicts else ""
            return f"""You are a strict JSON generator. Fill the template below using ONLY the FACTS provided.

FACTS format — each line: FIELD | source | value

FIELD CLASSIFICATION (follow strictly):
• goals = HIGH-LEVEL business outcomes the project wants to achieve. Example: "Build a unified platform", "Improve operational efficiency".
  - Do NOT put technical quality attributes here (scalability, reliability, performance, throughput, durability).
  - Do NOT put specific functional features here (they go into requirements).
• requirements = SPECIFIC functional capabilities the system must support. Example: "Support 45 currencies", "AI churn prediction".
  - If the same requirement appears in two languages, keep ONLY the more detailed version.
• technical_solution = Programming languages, frameworks, databases, and tools used. Example: "Go, Python, Java, PostgreSQL, Kafka, Redis, Kubernetes".
  - Do NOT put scalability/reliability goals here.
• architecture = System design: services, components, deployment topology, security layers. Summarize in 2-3 sentences.
  - Do NOT dump raw config or 10+ lines of bullet points.
• team = Named people with roles, or team size numbers. Example: "Denis Krasnov (Lead Architect)", "11 backend developers".
• timeline = Project duration and key dates. Example: "20 months, release August 2026".
• budget = Total project cost. Example: "$4,200,000" or "30,000,000 tenge".
• risks = Business, technical, or regulatory risks.

RULES:
• Use ONLY the facts listed. Never invent or paraphrase beyond the given text.
• Output ALL text in English — every field, every list item, every string value. If source text is in any other language (Russian, Kazakh, etc.), translate it naturally into English. No exceptions: goals, requirements, team, risks, technical_solution, architecture, timeline, budget must all be in English.
• If a field has no facts, write "No data" in "text" and "" in "source".
• Never leave "text" as an empty string "".
• For list fields (goals, requirements, team, risks): one item per unique fact. DEDUPLICATE: if two facts say the same thing in different languages, keep only the more detailed one.
• For scalar fields (technical_solution, architecture, timeline, budget):
  - "text" must contain the ACTUAL VALUE, NOT a conflict description or goal statement.
  - copy the source of that value into "source".
• project_name: short name of the project (2–6 words) exactly as it appears in the source documents (e.g. a heading, title field, or named reference). If no explicit name is found, derive a concise label from the overview. Never use a full sentence.
• project_overview: write 1–2 sentences in English summarising what the project is about.
• Output ONLY the JSON object — no markdown, no commentary.

CONFLICT HINTS (pre-detected by the system):{hints if hints else " none"}
• If a conflict hint exists for budget/timeline → set has_conflict=true and paste the HINT TEXT into conflict_details. The "text" field must still contain the actual value.
• All other fields → has_conflict=false, conflict_details="".

TEMPLATE (replace every <fact text>/<source> with real values from FACTS):
{json_template}
"""

        def _call_reduce(facts_text: str, include_conflicts: bool = True) -> tuple:
            """One REDUCE LLM call. Returns (raw_response_str, token_count).
            Tries json_schema → json_object → plain text (in order of strictness).
            """
            instruction = _build_reduce_instruction(facts_text, include_conflicts)
            messages = [
                {"role": "system", "content": instruction},
                {"role": "user",   "content": f"FACTS:\n{facts_text}"}
            ]
            try:
                # Attempt with response format first
                resp = self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format=_REDUCE_RESPONSE_FORMAT,
                    temperature=0.0
                )
                tokens = resp.usage.total_tokens if resp.usage else 0
                return resp.choices[0].message.content, tokens
            except Exception as e:
                print("Warning: Reduce schema rejected, retrying without schema...")
                try:
                    resp = self.client.chat.completions.create(
                        model=model,
                        messages=messages,
                        temperature=0.0
                    )
                    tokens = resp.usage.total_tokens if resp.usage else 0
                    return resp.choices[0].message.content, tokens
                except Exception as retry_e:
                    import traceback
                    print("LLM Reduce Call completely failed:")
                    traceback.print_exc()
                    return "{}", 0

        def _merge_partial_specs(dicts: list) -> dict:
            """
            Merge a list of partial parsed-spec dicts (output of intermediate
            REDUCE calls) into one combined dict — pure Python, no LLM call.
            List fields are concatenated; scalar fields take the first non-empty
            value (conflicts are stamped by the Python detection step later).
            """
            NON_DATA = {"no data", "not specified", "data not found", "not available", ""}

            result: dict = {
                "project_name": "",
                "project_overview": "",
                **{k: [] for k in SCHEMA_FIELDS_LIST},
                **{k: {"text": "No data", "source": "",
                       "has_conflict": False, "conflict_details": ""}
                   for k in SCHEMA_FIELDS_SCALAR},
            }

            for d in dicts:
                if not isinstance(d, dict) or "error" in d:
                    continue

                # project_name — keep first useful one
                if not result["project_name"]:
                    pn = (d.get("project_name") or "").strip()
                    if pn and pn.lower() not in NON_DATA and "<" not in pn:
                        result["project_name"] = pn

                # project_overview — keep first useful one
                if not result["project_overview"]:
                    ov = (d.get("project_overview") or "").strip()
                    if ov and ov.lower() not in NON_DATA and "<" not in ov:
                        result["project_overview"] = ov

                # list fields — extend, skip empty placeholders
                for key in SCHEMA_FIELDS_LIST:
                    for item in (d.get(key) or []):
                        if not isinstance(item, dict):
                            continue
                        if (item.get("text") or "").strip().lower() in NON_DATA:
                            continue
                        result[key].append(item)

                # scalar fields — take first non-empty value
                for key in SCHEMA_FIELDS_SCALAR:
                    cur = result[key]
                    if cur.get("text", "").strip().lower() not in NON_DATA:
                        continue   # already filled
                    val = d.get(key)
                    if isinstance(val, dict):
                        vt = (val.get("text") or "").strip()
                        if vt and vt.lower() not in NON_DATA:
                            result[key] = val

            return result

        # ── Decide: single REDUCE or hierarchical ─────────────────────────────
        if len(all_extracted_facts) <= REDUCE_MAX_CHARS:
            # ── Fast path: fits in one call ───────────────────────────────────
            raw_content, tokens = _call_reduce(all_extracted_facts)
            total_tokens_used += tokens
        else:
            # ── Hierarchical path: split → partial REDUCEs → Python merge ─────
            lines = all_extracted_facts.split("\n")
            groups: list[list[str]] = []
            cur_grp: list[str] = []
            cur_len = 0
            for line in lines:
                ll = len(line) + 1
                if cur_len + ll > REDUCE_MAX_CHARS and cur_grp:
                    groups.append(cur_grp)
                    cur_grp, cur_len = [], 0
                cur_grp.append(line)
                cur_len += ll
            if cur_grp:
                groups.append(cur_grp)

            partial_dicts: list[dict] = []
            for i, grp_lines in enumerate(groups):
                grp_text = "\n".join(grp_lines)
                # Only pass conflict hints to the last group to avoid duplication
                raw_part, tokens = _call_reduce(
                    grp_text, include_conflicts=(i == len(groups) - 1)
                )
                total_tokens_used += tokens
                # Reuse _repair_json defined below — forward-declared via closure;
                # we'll parse after _repair_json is defined.
                partial_dicts.append(raw_part)   # store raw strings for now

            # _repair_json is defined in the helpers block below; parse after
            raw_content = None          # signal: use partial_dicts path
            _partial_raw_list = partial_dicts  # stash for post-helper use

        emit("Finalising…")
        end_time = time.time()
        duration_ms = int((end_time - start_time) * 1000)

        # ── helpers (defined before use) ─────────────────────────────────────
        def _sanitize_placeholders(obj):
            """
            Safety net: if the LLM copied template placeholder words into
            conflict_details (e.g. 'срок_A', 'сумма_B', 'файл_A') instead of
            real extracted values, clear the field and reset has_conflict=False.
            Also clears has_conflict=True when conflict_details ended up empty.
            """
            import re
            # Matches placeholder patterns the LLM sometimes copies from the template
            PLACEHOLDER = re.compile(
                r'\b(?:срок|сумма|файл|значение|value|term|file|part)_[A-Za-zА-Яа-я0-9]{1,2}\b'
                r'|\.{3}'    # literal "..." left in the template fields
                r'|\*\*ADR-\d+[^*]*\*\*',   # **ADR-001: Timeline Conflict** — arch-doc headers
                re.IGNORECASE
            )
            if not isinstance(obj, dict):
                return
            if 'has_conflict' in obj and 'conflict_details' in obj:
                details = obj.get('conflict_details') or ''
                if obj['has_conflict']:
                    if not details.strip() or PLACEHOLDER.search(details):
                        obj['has_conflict'] = False
                        obj['conflict_details'] = ''
            for val in obj.values():
                if isinstance(val, dict):
                    _sanitize_placeholders(val)
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict):
                            _sanitize_placeholders(item)

        def _sanitize_hallucinations(obj, source_corpus: str):
            """
            Second pass: walk every {text, source} leaf and check that at least
            ONE meaningful word from `text` actually appears somewhere in the
            combined extracted facts (source_corpus).  If there is zero overlap
            the model invented the text — wipe it and mark the field clearly so
            the UI can display it as missing rather than fabricated data.

            Threshold: at least 1 word of length ≥ 4 characters must appear in
            the corpus (case-insensitive).  Short words (prepositions, articles)
            are skipped to avoid false positives.
            """
            import re
            corpus_lower = source_corpus.lower()

            def has_overlap(text: str) -> bool:
                if not text or not text.strip():
                    return False
                # Skip generic fallback phrases — those are always "valid"
                low = text.lower()
                if ('no data' in low or 'not found' in low or 'not specified' in low):
                    return True
                # Long words (≥4 chars)
                words = re.findall(r'[а-яёa-z0-9]{4,}', text.lower())
                if any(w in corpus_lower for w in words):
                    return True
                # Numeric values: dollar amounts, month counts etc. can be short
                # (e.g. "$700" splits at comma → "700" = 3 chars, fails word check)
                nums = re.findall(r'\d+', text)
                return any(n in corpus_lower for n in nums if len(n) >= 2)

            if not isinstance(obj, dict):
                return
            if 'text' in obj and 'source' in obj:
                if not has_overlap(obj.get('text', '')):
                    obj['text'] = 'No data'
                    obj['source'] = ''
                    obj['has_conflict'] = False
                    obj['conflict_details'] = ''
            for val in obj.values():
                if isinstance(val, dict):
                    _sanitize_hallucinations(val, source_corpus)
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict):
                            _sanitize_hallucinations(item, source_corpus)

        def _check_cross_field_timeline(doc):
            """
            The LLM only checks timeline/budget within their own field.
            This pass looks for numeric month/week values that appear in
            goals or risks and differ from what timeline field says —
            then flags the timeline field as conflicted if so.
            """
            import re
            if not isinstance(doc, dict):
                return

            def months_in(text):
                """Extract all integer month/week numbers from a string."""
                nums = set()
                for m in re.finditer(r'(\d+)\s*(?:месяц|мес\b|недел)', text, re.IGNORECASE):
                    nums.add(int(m.group(1)))
                return nums

            # Collect all timeline numbers from every field
            all_nums = set()
            for key in ('goals', 'requirements', 'risks'):
                for item in (doc.get(key) or []):
                    text = item.get('text', '') if isinstance(item, dict) else str(item)
                    all_nums |= months_in(text)

            timeline = doc.get('timeline')
            if not isinstance(timeline, dict):
                return
            tl_nums = months_in(timeline.get('text', ''))

            # If timeline field has a number AND other fields have a different number
            conflicting = all_nums - tl_nums
            if tl_nums and conflicting:
                if not timeline.get('has_conflict'):
                    other_vals = ', '.join(str(n) + ' mo.' for n in sorted(conflicting))
                    tl_val = ', '.join(str(n) + ' mo.' for n in sorted(tl_nums))
                    timeline['has_conflict'] = True
                    timeline['conflict_details'] = (
                        f"Timeline conflict: timeline — {tl_val}; "
                        f"other fields — {other_vals}"
                    )

        # ── Multi-stage JSON repair ───────────────────────────────────────────
        # LLMs commonly output } where ] is expected (or vice-versa), leave
        # trailing commas, or add markdown fences.  We try progressively more
        # aggressive fixes before giving up.
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

            # Stage 3 — fix bracket mismatches: } where ] expected (or vice-versa)
            # Walk char-by-char tracking the real open-bracket stack so every
            # closer uses whatever bracket matches the opener.  Also closes any
            # brackets that were never closed.
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
                while stack:       # close any unclosed brackets
                    out.append(stack.pop())
                return "".join(out)

            fixed2 = _fix_brackets(fixed)
            try:
                return json.loads(fixed2)
            except Exception:
                pass

            # Stage 4 — also strip markdown fences and retry everything
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

            # Stage 5 — replace single-quoted string values with double-quoted.
            # The model sometimes writes: "text": '{"key": value}' which is
            # invalid JSON.  Replace 'value' → "value" carefully (not inside strings).
            def _fix_single_quotes(text: str) -> str:
                # Replace ': 'value'' → ': "value"' only outside existing double-quoted strings
                return re.sub(r"(?<=:\s)'((?:[^'\\]|\\.)*)'", r'"\1"', text)

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

        def _normalize_parsed(data: dict):
            """
            Coerce field types after JSON parse so the rest of the pipeline can
            assume a consistent shape:
              • Scalar fields (timeline, budget, etc.) must be dicts with
                {text, source, has_conflict, conflict_details}.
                If REDUCE returned a plain string or a list, convert it.
              • List fields (goals, requirements, team, risks) must be lists of
                {text, source, …} dicts.  If REDUCE returned a plain list of
                strings, wrap each string.
            """
            if not isinstance(data, dict):
                return
            EMPTY_SCALAR = {"text": "No data", "source": "",
                            "has_conflict": False, "conflict_details": ""}

            for key in SCHEMA_FIELDS_SCALAR:
                val = data.get(key)
                if val is None:
                    data[key] = dict(EMPTY_SCALAR)
                elif isinstance(val, list):
                    # e.g. "timeline": ["6 мес", "12 мес"]  →  join to one string
                    joined = "; ".join(
                        (v.get("text") if isinstance(v, dict) else str(v)).strip()
                        for v in val
                        if (v.get("text") if isinstance(v, dict) else str(v)).strip()
                    )
                    src = next(
                        (v.get("source", "") for v in val if isinstance(v, dict) and v.get("source")),
                        ""
                    )
                    data[key] = {"text": joined or "No data", "source": src,
                                 "has_conflict": False, "conflict_details": ""}
                elif isinstance(val, str):
                    data[key] = {"text": val.strip() or "No data", "source": "",
                                 "has_conflict": False, "conflict_details": ""}
                # else: already a dict — leave it

            for key in SCHEMA_FIELDS_LIST:
                val = data.get(key)
                if val is None:
                    data[key] = []
                elif isinstance(val, str):
                    data[key] = [{"text": val.strip(), "source": "",
                                  "has_conflict": False, "conflict_details": ""}] if val.strip() else []
                elif isinstance(val, list):
                    normalized = []
                    for item in val:
                        if isinstance(item, dict):
                            normalized.append(item)
                        elif isinstance(item, str) and item.strip():
                            normalized.append({"text": item.strip(), "source": "",
                                               "has_conflict": False, "conflict_details": ""})
                    data[key] = normalized
                # else: leave as-is (already a list of dicts)

        # Parse JSON output — now that _repair_json and _merge_partial_specs are defined
        if raw_content is not None:
            # ── Single-REDUCE path ────────────────────────────────────────────
            repaired = _repair_json(raw_content)
            try:
                if repaired is None:
                    raise ValueError("all JSON repair stages failed")
                parsed_data = repaired
                _normalize_parsed(parsed_data)
                _sanitize_placeholders(parsed_data)
                _sanitize_hallucinations(parsed_data, all_extracted_facts)
                _check_cross_field_timeline(parsed_data)
            except Exception:
                parsed_data = {"error": "Llama 3 returned invalid JSON", "raw_output": raw_content}
        else:
            # ── Hierarchical-REDUCE path — parse partials and merge ───────────
            parsed_partials = []
            for raw_part in _partial_raw_list:
                p = _repair_json(raw_part)
                if p and isinstance(p, dict):
                    _normalize_parsed(p)
                    _sanitize_placeholders(p)
                    _sanitize_hallucinations(p, all_extracted_facts)
                    parsed_partials.append(p)
            if parsed_partials:
                parsed_data = _merge_partial_specs(parsed_partials)
                _normalize_parsed(parsed_data)
                _check_cross_field_timeline(parsed_data)
            else:
                parsed_data = {"error": "Llama 3 returned invalid JSON in all parts", "raw_output": str(_partial_raw_list)}

        # ── Python-guaranteed post-processing ─────────────────────────────────
        # The REDUCE model sometimes writes "No data" for fields the MAP step
        # successfully extracted.  Fill those gaps directly from `merged` so the
        # final output always reflects everything the parser found.
        # Also: always stamp Python-detected conflict flags — never let the model
        # override what our deterministic comparison already proved.
        if isinstance(parsed_data, dict) and "error" not in parsed_data:

            def _is_empty(val):
                """Return True when a field carries a fallback/empty value."""
                if val is None:
                    return True
                if isinstance(val, dict):
                    t = (val.get("text") or "").strip().lower()
                    if t in ("", "no data", "not specified", "not mentioned", "not found"):
                        return True
                    if re.match(r"^not\s+(?:specified|mentioned|found|available|provided)\b", t):
                        return True
                    return False
                if isinstance(val, list):
                    return len(val) == 0 or all(
                        _is_empty(i) for i in val
                    )
                t = str(val).strip().lower()
                if t in ("", "no data", "not specified", "not mentioned", "not found"):
                    return True
                # "Not specified in the provided facts." and similar REDUCE fallbacks
                if re.match(r"^not\s+(?:specified|mentioned|found|available|provided)\b", t):
                    return True
                return False

            def _make_fact(entry):
                return {"text": entry["text"], "source": entry["source"],
                        "has_conflict": False, "conflict_details": ""}

            # Scalar fields: inject best merged value when REDUCE said "No data"
            for key in SCHEMA_FIELDS_SCALAR:
                if merged[key] and _is_empty(parsed_data.get(key)):
                    parsed_data[key] = _make_fact(merged[key][0])

            # List fields: inject all merged values when REDUCE said "No data"
            for key in SCHEMA_FIELDS_LIST:
                if merged[key] and _is_empty(parsed_data.get(key)):
                    parsed_data[key] = [_make_fact(e) for e in merged[key]]

            # Strip "No data" / "not specified" placeholder items that
            # sometimes slip into list fields alongside real values
            NON_DATA_LC = {"no data", "not specified", "not mentioned", "not found",
                           "not specified in the provided facts.", ""}
            for key in SCHEMA_FIELDS_LIST:
                items = parsed_data.get(key)
                if isinstance(items, list) and len(items) > 1:
                    cleaned = [i for i in items
                               if not (isinstance(i, dict) and
                                       (i.get("text") or "").strip().lower() in NON_DATA_LC)]
                    if cleaned:
                        parsed_data[key] = cleaned

            # Requirements: remove entries that look like budget section headings
            # (e.g. "Общий бюджет", "Фонд оплаты труда", "Инфраструктура") or
            # architecture section titles ("PostgreSQL Domain Databases",
            # "Event Store Schema") — single-phrase headings with no verb.
            _REQ_HEADING_NOISE = re.compile(
                r"^(?:Общий\s+бюджет|Фонд\s+оплаты\s+труда|Инфраструктура|"
                r"Маркетинг\s+и\s+продажи|Резерв|"
                r"PostgreSQL\s+Domain\s+Databases|Event\s+Store\s+Schema|"
                r"ClickHouse\s+Schema|Data\s+Retention\s+Policy)$",
                re.IGNORECASE,
            )
            req_items = parsed_data.get("requirements")
            if isinstance(req_items, list) and len(req_items) > 1:
                filtered_reqs = [
                    i for i in req_items
                    if not (isinstance(i, dict) and
                            _REQ_HEADING_NOISE.match((i.get("text") or "").strip()))
                ]
                if filtered_reqs:
                    parsed_data["requirements"] = filtered_reqs

            # Architecture / technical_solution: remove values that are just
            # Java package declarations or Python import lists extracted by the
            # code parsers (e.g. "['package io.cryptonest.test']").
            _CODE_NOISE = re.compile(
                r"^\s*\[?'?(?:package|import)\s+[\w\.]+", re.IGNORECASE
            )
            for key in ("architecture", "technical_solution"):
                fld = parsed_data.get(key)
                if isinstance(fld, dict):
                    if _CODE_NOISE.match(fld.get("text") or ""):
                        # Replace with best merged value if available
                        if merged[key]:
                            parsed_data[key] = _make_fact(merged[key][0])
                        else:
                            fld["text"] = "No data"

            # Team: remove entries that look like spec/API descriptions rather
            # than actual people, and pure numbers leaked from config.json.
            _SPEC_NOISE = re.compile(
                r"^(?:GET|POST|PUT|DELETE|PATCH)\s+/|https?://|"
                r"^(?:RESTful|OAuth|AES|HL7|FHIR|шифрован|аудит.лог|"
                # Technical component names that appear in architecture diagrams
                r"Kong\s+API\s+Gateway|Business\s+Domain\s+Services|"
                r"AI/ML\s+Services|Background\s+Workers|WebSocket\s+Hub|"
                r"OIDC\s+Provider|Auth\s+Service|RBAC\s+Model|"
                r"Notification\s+Hub|Event\s+Bus)",
                re.IGNORECASE,
            )
            # Code class-name suffixes — Java/Python class names extracted from
            # source files that are NOT people (e.g. StockMovementRepository,
            # WarehouseService, PaymentController, CashFlowForecaster).
            _CODE_CLASS_SUFFIX = re.compile(
                r"(?:Repository|Service|Controller|Handler|Manager|Factory|"
                r"Provider|Engine|Processor|Forecaster|Publisher|Reconciliation"
                r"Engine|Worker|Scheduler|Listener|Consumer|Producer|"
                r"Validator|Serializer|Deserializer|Mapper|Converter|"
                r"Client|Stub|Proxy|Adapter|Gateway|Broker|Registry|"
                r"Store|Cache|Queue|Bus|Hub|Router|Resolver|Builder|"
                r"Executor|Dispatcher|Aggregator|Collector|Reporter)s?$",
                re.IGNORECASE,
            )
            team_items = parsed_data.get("team")
            if isinstance(team_items, list) and len(team_items) > 1:
                cleaned_team = []
                for i in team_items:
                    if not isinstance(i, dict):
                        continue
                    txt = (i.get("text") or "").strip()
                    # Skip spec/API noise
                    if _SPEC_NOISE.search(txt):
                        continue
                    # Skip pure-number entries (e.g. "21", "52" from config.json values)
                    if re.match(r"^\d+$", txt):
                        continue
                    # Skip code class names ending in Repository/Service/Controller etc.
                    # These are Java/Python identifiers extracted from source files,
                    # not actual people or team roles.
                    # Match a single PascalCase/camelCase word with a code suffix.
                    if _CODE_CLASS_SUFFIX.search(txt) and re.match(r"^[A-Z][A-Za-z0-9]+$", txt):
                        continue
                    # Skip ALL-CAPS Cyrillic/Latin section headings that leaked from
                    # budget_draft.txt etc. (e.g. "ФИНАНСОВОЕ ПЛАНИРОВАНИЕ И БЮДЖЕТ").
                    # Heuristic: ≥ 8 chars, every letter is uppercase.
                    _letters_only = re.sub(r"[^а-яёa-zA-ZА-ЯЁ]", "", txt)
                    if (len(txt) >= 8 and _letters_only
                            and _letters_only == _letters_only.upper()):
                        continue
                    cleaned_team.append(i)
                if cleaned_team:
                    parsed_data["team"] = cleaned_team

            # ── Line-number prefix stripper ───────────────────────────────────
            # architecture.md lines are prefixed "[437] text" during MAP chunking.
            # Strip these "[NNN] -?" prefixes from every extracted text value so
            # they don't bleed into the final document output.
            _LINE_NUM_RE = re.compile(r"^\[\d+\]\s*[-–—]?\s*")

            def _strip_line_num(text: str) -> str:
                return _LINE_NUM_RE.sub("", text).strip()

            # ── Template placeholder filter ───────────────────────────────────
            # When MAP processes config.json or .py files, it sometimes copies
            # the instruction template text verbatim as a fact value, e.g.
            # "<any risk, problem, or concern mentioned — copy exactly>" or
            # "[any monetary amount or cost mentioned]" or "<fact text>".
            # These are recognisable patterns — filter them out.
            _TMPL_ANGLE  = re.compile(
                r"^<\s*(?:any\b|fact\s+text|source\b)",
                re.IGNORECASE
            )
            _TMPL_SQUARE = re.compile(
                r"^\[\s*any\b",
                re.IGNORECASE
            )
            # Also filter raw HTML/JS tags that slip in from PDF/DOCX artefacts
            _HTML_TAG_RE = re.compile(r"^<[a-zA-Z/!]")

            def _is_template_placeholder(text: str) -> bool:
                t = text.strip()
                if not t:
                    return True
                if _TMPL_ANGLE.match(t) or _TMPL_SQUARE.match(t):
                    return True
                # "<any X mentioned — copy exactly>" or "[any X mentioned]"
                if re.match(
                    r"^[<\[].{3,100}(?:mentioned|copy\s+exactly)[>\]]?$",
                    t, re.IGNORECASE
                ):
                    return True
                if _HTML_TAG_RE.match(t):
                    return True
                # "Not specified in the provided facts." / "Not mentioned" etc.
                if re.match(
                    r"^not\s+(?:specified|mentioned|found|available|provided)\b",
                    t, re.IGNORECASE
                ):
                    return True
                return False

            # Apply both transforms to ALL list fields
            for _key in SCHEMA_FIELDS_LIST:
                _items = parsed_data.get(_key)
                if not isinstance(_items, list):
                    continue
                _cleaned = []
                for _i in _items:
                    if not isinstance(_i, dict):
                        continue
                    _i["text"] = _strip_line_num(_i.get("text") or "")
                    if not _i["text"] or _is_template_placeholder(_i["text"]):
                        continue
                    _cleaned.append(_i)
                if _cleaned:
                    parsed_data[_key] = _cleaned

            # Apply line-number stripping to scalar field text values too
            for _key in SCHEMA_FIELDS_SCALAR:
                _fld = parsed_data.get(_key)
                if isinstance(_fld, dict):
                    _fld["text"] = _strip_line_num(_fld.get("text") or "")
                    # If the scalar text is itself a template placeholder,
                    # replace with the best real merged value for that field.
                    if _is_template_placeholder(_fld["text"]):
                        _best = next(
                            (e for e in merged.get(_key, [])
                             if e.get("text") and
                             not _is_template_placeholder(_strip_line_num(e["text"]))),
                            None
                        )
                        if _best:
                            _fld["text"]   = _strip_line_num(_best["text"])
                            _fld["source"] = _best["source"]
                        else:
                            _fld["text"]   = "No data"
                            _fld["source"] = ""

            # Budget text cleanup: if the model stored a Python-list repr or
            # JSON array string (e.g. "[{'amount': '30 000 000 тенге', ...}]"),
            # extract the first monetary amount with a simple regex.
            b = parsed_data.get("budget")
            if isinstance(b, dict):
                bt = (b.get("text") or "").strip()
                if bt.startswith("[") or bt.startswith("{") or bt.startswith("'"):
                    # Try to pull the first number+currency from the string
                    m = re.search(r"[\d\s]+(?:тенге|тнг|руб|usd|\$|€|₸)", bt, re.IGNORECASE)
                    if m:
                        b["text"] = m.group(0).strip()
                    elif merged["budget"]:
                        b["text"]   = merged["budget"][0]["text"]
                        b["source"] = merged["budget"][0]["source"]

            # Budget document-title filter: "ФИНАНСОВОЕ ПЛАНИРОВАНИЕ И БЮДЖЕТ"
            # is the title of the budget_draft.txt section, not a monetary value.
            # Detect: budget text has NO digits AND is in ALL-CAPS Cyrillic.
            b = parsed_data.get("budget")
            if isinstance(b, dict):
                bt = (b.get("text") or "").strip()
                if bt and not re.search(r"\d", bt):
                    # All-caps Cyrillic / Latin (document title) check
                    letters = re.sub(r"[^а-яёa-zА-ЯЁA-Z]", "", bt)
                    if letters and letters == letters.upper():
                        # Replace with the first merged budget entry that has a digit
                        _best_money = next(
                            (e for e in merged.get("budget", [])
                             if re.search(r"\d", e.get("text", "")) and
                             not _is_template_placeholder(e.get("text", ""))),
                            None
                        )
                        if _best_money:
                            b["text"]   = _best_money["text"]
                            b["source"] = _best_money["source"]

            # ── Audit-driven noise filters (5 rules) ──────────────────────────
            # Rule 1: Budget — suppress tiny line-items (< $100K) when the
            # merged budget set contains at least one major figure (≥ $1M).
            # Fixes "$80,000/year in cloud" leaking in as the headline budget
            # when the real project budget ($4.2M–$6.8M) is available.
            def _amount_usd(text: str) -> float:
                """Extract first USD-denominated amount; returns 0 if none."""
                t = text.replace("\u00a0", " ")
                # Match $X,XXX,XXX or X XXX XXX USD / $ / dollars
                m = re.search(
                    r"(?:\$|USD\s*)?\s*([\d][\d\s,.]*)\s*(?:USD|\$|dollars?)?",
                    t, re.IGNORECASE
                )
                if not m:
                    return 0.0
                num = re.sub(r"[\s,]", "", m.group(1))
                try:
                    val = float(num)
                except ValueError:
                    return 0.0
                # Heuristic: presence of $/USD in the string confirms USD
                if not re.search(r"\$|USD|dollar", t, re.IGNORECASE):
                    return 0.0
                return val

            _merged_budget = merged.get("budget", [])
            _has_major = any(
                _amount_usd(e.get("text", "")) >= 1_000_000
                for e in _merged_budget
            )
            if _has_major:
                b = parsed_data.get("budget")
                if isinstance(b, dict):
                    _cur_val = _amount_usd(b.get("text", ""))
                    if 0 < _cur_val < 100_000:
                        _best_big = next(
                            (e for e in _merged_budget
                             if _amount_usd(e.get("text", "")) >= 1_000_000 and
                             not _is_template_placeholder(e.get("text", ""))),
                            None
                        )
                        if _best_big:
                            b["text"]   = _strip_line_num(_best_big["text"])
                            b["source"] = _best_big["source"]

            # Rule 2: Requirements — drop entries that are a comma-separated
            # list of ≥3 PascalCase identifiers (Java/Python class dump, e.g.
            # "StockMovementRepository, LocationRepository, ShipmentRepository").
            _PASCAL_TOKEN = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b")
            def _is_class_list(text: str) -> bool:
                if "," not in text:
                    return False
                tokens = _PASCAL_TOKEN.findall(text)
                return len(tokens) >= 3

            _reqs = parsed_data.get("requirements")
            if isinstance(_reqs, list):
                parsed_data["requirements"] = [
                    i for i in _reqs
                    if isinstance(i, dict) and not _is_class_list(i.get("text") or "")
                ]

            # Rule 3: Architecture vs goals — if `architecture` scalar begins
            # with a goal-like prefix (Scalability:/Reliability:/Performance:/
            # Availability:/Developer velocity:), move it into goals and
            # replace architecture with the best merged architecture candidate.
            _GOAL_PREFIX = re.compile(
                r"^(?:Scalability|Reliability|Performance|Availability|"
                r"Data\s+integrity|Developer\s+velocity|Security|Usability)\s*:",
                re.IGNORECASE,
            )
            _arch = parsed_data.get("architecture")
            if isinstance(_arch, dict):
                _atxt = (_arch.get("text") or "").strip()
                if _GOAL_PREFIX.match(_atxt):
                    # Push into goals
                    _goals = parsed_data.setdefault("goals", [])
                    if isinstance(_goals, list):
                        _goals.append({
                            "text":              _atxt,
                            "source":            _arch.get("source", ""),
                            "has_conflict":      False,
                            "conflict_details":  "",
                        })
                    # Replace architecture with a better candidate
                    _best_arch = next(
                        (e for e in merged.get("architecture", [])
                         if e.get("text") and
                         not _GOAL_PREFIX.match(e["text"].strip()) and
                         not _is_template_placeholder(_strip_line_num(e["text"]))),
                        None
                    )
                    if _best_arch:
                        _arch["text"]   = _strip_line_num(_best_arch["text"])
                        _arch["source"] = _best_arch["source"]
                    else:
                        _arch["text"]   = "No data"
                        _arch["source"] = ""

            # Rule 4: Risks — drop bare ADR headers (e.g. "ADR-001: Timeline
            # Conflict", "ADR-002") that carry no body content.
            _ADR_HEADER = re.compile(r"^\*{0,2}ADR-\d+\b[^.\n]{0,48}\*{0,2}$",
                                     re.IGNORECASE)
            _risks = parsed_data.get("risks")
            if isinstance(_risks, list):
                parsed_data["risks"] = [
                    i for i in _risks
                    if isinstance(i, dict)
                    and not (len((i.get("text") or "").strip()) <= 50
                             and _ADR_HEADER.match((i.get("text") or "").strip()))
                ]

            # Rule 5: Goals — drop Kubernetes node-pool specs like
            # "ml-pool g4dn.xlarge" or "spot-pool m6i.2xlarge" that are
            # infra/architecture details, not project goals.
            _NODE_POOL = re.compile(
                r"^[a-z][a-z-]*-pool\s+[a-z0-9]+\.[a-z0-9]+\b",
                re.IGNORECASE,
            )
            _goals = parsed_data.get("goals")
            if isinstance(_goals, list):
                parsed_data["goals"] = [
                    i for i in _goals
                    if isinstance(i, dict)
                    and not _NODE_POOL.match((i.get("text") or "").strip())
                ]

            # Conflict flags: always trust Python detection over the model.
            # Also fix the common mistake where the model writes the conflict
            # description into the "text" field instead of the actual value.
            if budget_conflict and merged["budget"]:
                b = parsed_data.get("budget")
                if isinstance(b, dict):
                    # If text looks like a conflict description, replace with first real value
                    if ("conflict" in (b.get("text") or "").lower()
                            or _is_empty(b)):
                        b["text"]   = merged["budget"][0]["text"]
                        b["source"] = merged["budget"][0]["source"]
                    b["has_conflict"]     = True
                    b["conflict_details"] = budget_detail

            if timeline_conflict and merged["timeline"]:
                t = parsed_data.get("timeline")
                if isinstance(t, dict):
                    if ("conflict" in (t.get("text") or "").lower()
                            or _is_empty(t)):
                        t["text"]   = merged["timeline"][0]["text"]
                        t["source"] = merged["timeline"][0]["source"]
                    t["has_conflict"]     = True
                    t["conflict_details"] = timeline_detail

            # ── Final line-number stripping (after conflict flags may re-inject) ─
            # Conflict flags code can replace budget/timeline .text with a raw
            # merged[] value that still carries "[454] -" prefixes.  Re-strip here.
            for _key in SCHEMA_FIELDS_SCALAR:
                _fld = parsed_data.get(_key)
                if isinstance(_fld, dict) and _fld.get("text"):
                    _fld["text"] = _LINE_NUM_RE.sub("", _fld["text"]).strip()
                    # Also clean inside conflict_details (which may contain "[437]")
                    if _fld.get("conflict_details"):
                        _fld["conflict_details"] = re.sub(
                            r"\n?\[?\d+\]\s*[-–—]?\s*", " ", _fld["conflict_details"]
                        ).strip()

            # ── Deduplication pass (list fields) — exact + semantic ─────────────
            # Stage 1: exact dedup (normalised lowercase, collapsed whitespace)
            # Stage 2: semantic dedup — if two entries share ≥60% of significant
            #          words (len≥4), keep the longer (more detailed) one.
            def _significant_words(text: str) -> set:
                """Extract set of lowercase words ≥4 chars (skips prepositions)."""
                return {w for w in re.findall(r'[а-яёa-z0-9]{4,}', text.lower())}

            def _semantic_dedup(items: list) -> list:
                """Remove entries that are semantically redundant (same fact, different wording/language)."""
                if len(items) <= 1:
                    return items
                result = []
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    txt = (item.get('text') or '').strip()
                    if not txt:
                        continue
                    words = _significant_words(txt)
                    is_dup = False
                    for j, existing in enumerate(result):
                        ex_words = _significant_words((existing.get('text') or ''))
                        if not words or not ex_words:
                            continue
                        overlap = len(words & ex_words)
                        smaller = min(len(words), len(ex_words))
                        if smaller > 0 and overlap / smaller >= 0.60:
                            # Keep the longer (more detailed) entry
                            if len(txt) > len(existing.get('text') or ''):
                                result[j] = item
                            is_dup = True
                            break
                    if not is_dup:
                        result.append(item)
                return result

            for _key in SCHEMA_FIELDS_LIST:
                _items = parsed_data.get(_key)
                if not isinstance(_items, list) or len(_items) <= 1:
                    continue
                # Stage 1: exact dedup
                _seen: set = set()
                _deduped = []
                for _i in _items:
                    if not isinstance(_i, dict):
                        continue
                    _norm = re.sub(r"\s+", " ", (_i.get("text") or "").strip().lower())
                    if _norm and _norm not in _seen:
                        _seen.add(_norm)
                        _deduped.append(_i)
                # Stage 2: semantic dedup
                _deduped = _semantic_dedup(_deduped)
                if _deduped:
                    parsed_data[_key] = _deduped

            # ── Source backfill ────────────────────────────────────────────────
            # When REDUCE drops the source, try to recover it from merged[]
            # by matching the text against known extracted facts.
            for _key in SCHEMA_FIELDS_LIST:
                _items = parsed_data.get(_key)
                if not isinstance(_items, list):
                    continue
                for _item in _items:
                    if not isinstance(_item, dict):
                        continue
                    if (_item.get('source') or '').strip():
                        continue  # already has source
                    _itxt = (_item.get('text') or '').strip().lower()
                    if not _itxt:
                        continue
                    # Find best match in merged by word overlap
                    _item_words = _significant_words(_itxt)
                    _best_src = ''
                    _best_overlap = 0
                    for _m_entry in merged.get(_key, []):
                        _m_words = _significant_words(_m_entry.get('text', ''))
                        if not _m_words:
                            continue
                        _ov = len(_item_words & _m_words)
                        if _ov > _best_overlap:
                            _best_overlap = _ov
                            _best_src = _m_entry.get('source', '')
                    if _best_src and _best_overlap >= 2:
                        _item['source'] = _best_src

            # ── Conflict details summarization ─────────────────────────────────
            # Raw conflict_details can be 800+ chars of dumped dates/values.
            # Summarize to a readable format: "File1: value1 | File2: value2"
            def _summarize_conflict(detail: str) -> str:
                if not detail or len(detail) <= 250:
                    return detail
                # Parse "Conflict: file1 — "val1"; file2 — "val2"; ..."
                parts = re.findall(r'([\w._-]+(?:\.\w+)?)\s*[—–-]\s*"([^"]{1,100})', detail)
                if parts:
                    summary_parts = []
                    for fname, val in parts[:4]:  # max 4 sources
                        # Truncate individual values to 60 chars
                        val_short = val[:60] + '...' if len(val) > 60 else val
                        summary_parts.append(f'{fname}: "{val_short}"')
                    return ' | '.join(summary_parts)
                # Fallback: just truncate
                return detail[:240] + '...'

            for _key in SCHEMA_FIELDS_SCALAR:
                _fld = parsed_data.get(_key)
                if isinstance(_fld, dict) and _fld.get('conflict_details'):
                    _fld['conflict_details'] = _summarize_conflict(_fld['conflict_details'])

            # ── Truncate long scalar fields ────────────────────────────────────
            # Architecture and technical_solution should be readable summaries,
            # not raw config dumps. If >500 chars, extract key points.
            for _key in ('architecture', 'technical_solution'):
                _fld = parsed_data.get(_key)
                if not isinstance(_fld, dict):
                    continue
                _txt = (_fld.get('text') or '').strip()
                if len(_txt) <= 500:
                    continue
                # Split by newlines or semicolons, keep first 3-5 significant lines
                _lines = re.split(r'[\n;]+', _txt)
                _lines = [l.strip() for l in _lines if l.strip() and len(l.strip()) > 10]
                if len(_lines) > 5:
                    _fld['text'] = '; '.join(_lines[:5]) + f' (and {len(_lines)-5} more items)'

            # ── Filter garbage "No data" entries from list fields ──────────
            for _key in SCHEMA_FIELDS_LIST:
                _items = parsed_data.get(_key)
                if not isinstance(_items, list):
                    continue
                parsed_data[_key] = [
                    r for r in _items
                    if isinstance(r, dict)
                    and (r.get('text') or '').strip().lower()
                    not in {'no data', 'not specified', 'not mentioned', ''}
                ]

            # ── Source backfill for SCALAR fields ──────────────────────────────
            # Budget and timeline often lose their source in REDUCE.
            # Backfill from merged[] when the source is empty.
            for _key in SCHEMA_FIELDS_SCALAR:
                _fld = parsed_data.get(_key)
                if not isinstance(_fld, dict):
                    continue
                _src = (_fld.get('source') or '').strip()
                if _src and _src.lower() != 'no data':
                    continue  # already has a real source
                _ftxt = (_fld.get('text') or '').strip().lower()
                if not _ftxt or _ftxt == 'no data':
                    continue
                # Find best match in merged by word overlap
                _fld_words = _significant_words(_ftxt)
                _best_src = ''
                _best_ov = 0
                for _m in merged.get(_key, []):
                    _mw = _significant_words(_m.get('text', ''))
                    if not _mw:
                        continue
                    _ov = len(_fld_words & _mw)
                    if _ov > _best_ov:
                        _best_ov = _ov
                        _best_src = _m.get('source', '')
                if _best_src and _best_ov >= 1:
                    _fld['source'] = _best_src
                elif merged.get(_key):
                    # If word overlap fails, just use the first merged entry's source
                    _fld['source'] = merged[_key][0].get('source', '')

            # ── Replace "No data" source strings ───────────────────────────
            # The LLM sometimes writes "No data" as source instead of leaving
            # it empty. Replace with actual source from merged[] where possible.
            for _key in SCHEMA_FIELDS_LIST:
                _items = parsed_data.get(_key)
                if not isinstance(_items, list):
                    continue
                for _item in _items:
                    if not isinstance(_item, dict):
                        continue
                    _src = (_item.get('source') or '').strip()
                    if _src.lower() not in {'no data', 'no source'}:
                        continue
                    _item['source'] = ''  # Clear placeholder
                    # Try to backfill from merged
                    _itxt = (_item.get('text') or '').strip().lower()
                    _iw = _significant_words(_itxt)
                    _best_src = ''
                    _best_ov = 0
                    for _m in merged.get(_key, []):
                        _mw = _significant_words(_m.get('text', ''))
                        _ov = len(_iw & _mw) if _mw else 0
                        if _ov > _best_ov:
                            _best_ov = _ov
                            _best_src = _m.get('source', '')
                    if _best_src and _best_ov >= 2:
                        _item['source'] = _best_src

            # ── Team headcount conflict detection ─────────────────────────────
            # Detect cases like "4 фронтенд-разработчика" (concept_notes.txt) vs
            # "5 frontend разработчиков" (config.json) — same role, different count.
            _TEAM_COUNT_RE = re.compile(
                r'^(\d+)\s+(.+)',
                re.IGNORECASE
            )
            _team = parsed_data.get('team')
            if isinstance(_team, list) and len(_team) > 1:
                # Group by role similarity
                _role_groups: dict = {}  # normalized_role -> [(idx, count, source)]
                for _idx, _t in enumerate(_team):
                    if not isinstance(_t, dict):
                        continue
                    _m = _TEAM_COUNT_RE.match((_t.get('text') or '').strip())
                    if not _m:
                        continue
                    _count = int(_m.group(1))
                    _role = _m.group(2).strip().lower()
                    # Normalize: backend/бэкенд, frontend/фронтенд
                    _role_norm = _role
                    for _en, _ru_list in [
                        ('backend', ['бэкенд', 'бекенд']),
                        ('frontend', ['фронтенд']),
                        ('devops', ['девопс']),
                        ('data engineer', ['дата инженер']),
                    ]:
                        if _en in _role_norm:
                            _role_norm = _en
                        for _ru in _ru_list:
                            if _ru in _role_norm:
                                _role_norm = _en
                    # Strip common suffixes for matching
                    _role_norm = re.sub(
                        r'(разработчик\w*|инженер\w*|developer\w*|engineer\w*)',
                        '', _role_norm
                    ).strip(' -')
                    if _role_norm not in _role_groups:
                        _role_groups[_role_norm] = []
                    _role_groups[_role_norm].append((_idx, _count, _t.get('source', '')))

                # Flag conflicts where same role has different counts
                for _role_norm, _entries in _role_groups.items():
                    _counts = set(e[1] for e in _entries)
                    if len(_counts) <= 1:
                        continue
                    # Mark the later entries as conflicting
                    _detail_parts = [
                        f"{e[2] or '?'}: {e[1]}" for e in _entries
                    ]
                    _detail = ' vs '.join(_detail_parts)
                    for _idx, _count, _source in _entries:
                        _team[_idx]['has_conflict'] = True
                        _team[_idx]['conflict_details'] = _detail

        def count_conflicts(doc):
            count = 0
            if not isinstance(doc, dict): return 0
            for value in doc.values():
                if isinstance(value, dict) and value.get("has_conflict"):
                    count += 1
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict) and item.get("has_conflict"):
                            count += 1
            return count

        def _to_spec_document(rich):
            """
            Convert the rich {text, source, has_conflict, conflict_details} format
            into a spec-compliant document where scalar fields are plain strings
            and array fields are plain string lists.
            """
            def txt(f):
                if isinstance(f, dict):
                    return (f.get('text') or '').strip()
                if isinstance(f, list):
                    # REDUCE occasionally writes a list for a scalar field
                    parts = [txt(i) for i in f if txt(i)]
                    return "; ".join(parts)
                return str(f or '').strip()

            def lst(arr):
                if not isinstance(arr, list):
                    return []
                return [txt(i) for i in arr if i]

            return {
                "project_name":       (rich.get("project_name") or "").strip(),
                "project_overview":   rich.get("project_overview", ""),
                "goals":              lst(rich.get("goals")),
                "requirements":       lst(rich.get("requirements")),
                "technical_solution": txt(rich.get("technical_solution")),
                "architecture":       txt(rich.get("architecture")),
                "team":               lst(rich.get("team")),
                "timeline":           txt(rich.get("timeline")),
                "budget":             txt(rich.get("budget")),
                "risks":              lst(rich.get("risks")),
            }

        # Build both the spec-compliant document and the rich extended document
        spec_document = _to_spec_document(parsed_data) if "error" not in parsed_data else parsed_data

        return {
            "document":          spec_document,    # spec-compliant plain strings/lists
            "document_extended": parsed_data,       # rich {text,source,has_conflict,...} for UI
            "metadata": {
                "model_name": f"Local GPU Map-Reduce ({model})",
                "llm_calls": len(files_data) + 1,
                "total_tokens": total_tokens_used,
                "duration_ms": duration_ms,
                "conflicts_found": count_conflicts(parsed_data)
            },
            "trace": {
                "steps": [
                    "Parsing files",
                    f"Map: Extracting facts (files processed: {len(files_data)})",
                    "Reduce: Building JSON"
                ]
            }
        }
