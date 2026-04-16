import os
import time
import json
from typing import List
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import HTMLResponse, JSONResponse
from openai import OpenAI

# Path to the pre-generated samples archive (in the same folder as this file)
SAMPLES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finetune_v2")

class LLMProvider:
    def generate_document(self, files_data: list[dict]) -> dict:
        pass

# --- ЛОКАЛЬНЫЙ ПРОВАЙДЕР С ЖЕСТКОЙ ДЕТЕРМИНИРОВАННОСТЬЮ ---
class LocalProvider(LLMProvider):
    def __init__(self, base_url: str, model_name: str = "meta-llama-3-8b-instruct"):
        self.client = OpenAI(base_url=base_url, api_key="lm-studio-local")
        self.model_name = model_name

    def generate_document(self, files_data: list[dict], language: str = "ru") -> dict:
        start_time = time.time()
        total_tokens_used = 0
        all_extracted_facts = ""

        map_instruction = """Ты - безэмоциональный парсер текста. Твоя единственная задача - скопировать из текста все факты, цифры и требования, сохранив номер строки.

ОТВЕЧАЙ СТРОГО В ФОРМАТЕ:
[Номер строки] Факт: "цитата или точный пересказ"

ВАЖНО: Обязательно извлекай все числовые значения — суммы денег, сроки в месяцах или неделях, версии, размеры команд. Каждое число должно быть отдельной строкой факта.
Не придумывай ничего своего. Ничего не анализируй. Просто выписывай факты. Если фактов нет, пиши "Пусто"."""

        # ── MAP phase: all files processed in parallel ────────────────────────
        def _map_one(f):
            lines = f['content'].splitlines()
            numbered = "\n".join([f"[{i+1}] {line}" for i, line in enumerate(lines)])
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": map_instruction},
                    {"role": "user",   "content": f"Файл: {f['filename']}\nТекст:\n{numbered}"}
                ],
                temperature=0.0
            )
            tokens = resp.usage.total_tokens if resp.usage else 0
            return f['filename'], resp.choices[0].message.content, tokens

        max_workers = min(len(files_data), 5)   # cap at 5 parallel calls
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            map_results = list(pool.map(_map_one, files_data))  # order preserved

        for filename, fact_summary, tokens in map_results:
            total_tokens_used += tokens
            all_extracted_facts += f"\n\n--- ФАЙЛ: {filename} ---\n{fact_summary}\n"

        # NOTE: ALL has_conflict values start as false and ALL conflict_details are empty.
        # The model must ONLY set has_conflict=true when it finds REAL differing values
        # in the extracted facts, and it must write REAL values — never placeholder words.
        json_template = """{
  "project_overview": "СЮДА — краткое описание проекта из фактов",
  "goals":            [{"text": "СЮДА — точный текст цели из фактов",        "source": "файл.txt, [N]", "has_conflict": false, "conflict_details": ""},
                       {"text": "СЮДА — точный текст второй цели из фактов", "source": "файл.txt, [N]", "has_conflict": false, "conflict_details": ""}],
  "requirements":     [{"text": "СЮДА — точный текст требования из фактов",  "source": "файл.txt, [N]", "has_conflict": false, "conflict_details": ""},
                       {"text": "СЮДА — точный текст второго требования",    "source": "файл.txt, [N]", "has_conflict": false, "conflict_details": ""}],
  "technical_solution":{"text": "СЮДА — технология/стек из фактов",         "source": "файл.txt, [N]", "has_conflict": false, "conflict_details": ""},
  "architecture":      {"text": "СЮДА — архитектурное решение из фактов",   "source": "файл.txt, [N]", "has_conflict": false, "conflict_details": ""},
  "team":             [{"text": "СЮДА — имя и роль участника из фактов",     "source": "файл.txt, [N]", "has_conflict": false, "conflict_details": ""}],
  "timeline":          {"text": "СЮДА — конкретный срок из фактов",         "source": "файл.txt, [N]", "has_conflict": false, "conflict_details": ""},
  "budget":            {"text": "СЮДА — конкретная сумма из фактов",        "source": "файл.txt, [N]", "has_conflict": false, "conflict_details": ""},
  "risks":            [{"text": "СЮДА — точный текст риска из фактов",       "source": "файл.txt, [N]", "has_conflict": false, "conflict_details": ""}]
}"""

        reduce_instruction = f"""Ты — строгий JSON-генератор. Заполни шаблон ниже, используя ТОЛЬКО текст из раздела ФАКТЫ.

═══ ЗАПРЕТЫ (нарушение = неверный ответ) ═══
• ЗАПРЕЩЕНО вписывать любой текст, которого нет в ФАКТАХ.
• ЗАПРЕЩЕНО копировать текст из шаблона — шаблон показывает только структуру, не содержание.
• ЗАПРЕЩЕНО оставлять поле "text" пустой строкой "". Нет данных → пиши "Данные отсутствуют".
• ЗАПРЕЩЕНО писать слова "срок_А/B", "сумма_А/B", "файл_А/B" — это технические метки, не данные.

═══ КАК ЗАПОЛНЯТЬ "text" ═══
Для каждого элемента массива (goals, requirements, team, risks):
  — найди в ФАКТАХ строку, относящуюся к этой теме
  — скопируй её содержание дословно в поле "text"
  — укажи реальный файл и номер строки в "source"

═══ КАК ЗАПОЛНЯТЬ КОНФЛИКТЫ ═══
BUDGET: найди ВСЕ денежные суммы в ФАКТАХ.
  Если найдено ≥2 разных суммы → "has_conflict": true,
  "conflict_details": "Конфликт: РЕАЛЬНЫЙ_ФАЙЛ, [N] — РЕАЛЬНАЯ_СУММА; РЕАЛЬНЫЙ_ФАЙЛ2, [M] — РЕАЛЬНАЯ_СУММА2"
TIMELINE: то же самое для сроков.
Нет расхождений → "has_conflict": false, "conflict_details": ""

Выведи ТОЛЬКО JSON без текста до или после.
ШАБЛОН (каждое поле "СЮДА…" замени на реальный текст из ФАКТОВ):
{json_template}
"""

        final_response = self.client.chat.completions.create(
            model=self.model_name,
            messages=[
                {"role": "system", "content": reduce_instruction},
                {"role": "user", "content": f"Факты:\n{all_extracted_facts}"}
            ],
            temperature=0.0
        )
        total_tokens_used += final_response.usage.total_tokens if final_response.usage else 0
        end_time = time.time()

        raw_content = final_response.choices[0].message.content
        start_idx = raw_content.find('{')
        end_idx = raw_content.rfind('}')
        clean_json = raw_content[start_idx:end_idx+1] if start_idx != -1 and end_idx != -1 else raw_content

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
            # Matches patterns like: срок_A  сумма_B  файл_A  срок_1
            PLACEHOLDER = re.compile(
                r'\b(?:срок|сумма|файл|значение|value|term)_[A-Za-zА-Яа-я0-9]{1,2}\b',
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
                if 'отсутству' in text.lower() or 'нет данных' in text.lower():
                    return True
                words = re.findall(r'[а-яёa-z0-9]{4,}', text.lower())
                return any(w in corpus_lower for w in words)

            if not isinstance(obj, dict):
                return
            if 'text' in obj and 'source' in obj:
                if not has_overlap(obj.get('text', '')):
                    obj['text'] = 'Данные отсутствуют'
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
                    other_vals = ', '.join(str(n) + ' мес.' for n in sorted(conflicting))
                    tl_val = ', '.join(str(n) + ' мес.' for n in sorted(tl_nums))
                    timeline['has_conflict'] = True
                    timeline['conflict_details'] = (
                        f"Конфликт сроков: timeline — {tl_val}; "
                        f"другие поля — {other_vals}"
                    )

        # Parse JSON output (now that helpers are defined above)
        try:
            parsed_data = json.loads(clean_json)
            _sanitize_placeholders(parsed_data)
            _sanitize_hallucinations(parsed_data, all_extracted_facts)
            _check_cross_field_timeline(parsed_data)
        except Exception:
            parsed_data = {"error": "Llama 3 вернула невалидный JSON", "raw_output": raw_content}

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
                return (f or '').strip()

            def lst(arr):
                if not isinstance(arr, list):
                    return []
                return [txt(i) for i in arr if i]

            return {
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
                "model_name": f"Local GPU Map-Reduce ({self.model_name})",
                "llm_calls": len(files_data) + 1,
                "total_tokens": total_tokens_used,
                "duration_ms": duration_ms,
                "conflicts_found": count_conflicts(parsed_data)
            },
            "trace": {
                "steps": [
                    "Парсинг файлов",
                    f"Map: Извлечение фактов (обработано файлов: {len(files_data)})",
                    "Reduce: Сборка JSON"
                ]
            }
        }

# ─────────────────────────────────────────────────────────────────────────────
# FASTAPI APP
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI()
# When running in Docker, LM Studio is on the host machine.
# Set LM_STUDIO_HOST env var to override (e.g. "host.docker.internal" on Docker Desktop).
LOCAL_PC_IP = os.environ.get("LM_STUDIO_HOST", "127.0.0.1")
current_llm = LocalProvider(base_url=f"http://{LOCAL_PC_IP}:1234/v1")

# ── Archive API ───────────────────────────────────────────────────────────────
@app.get("/api/samples")
async def list_samples():
    """Return sorted list of available pre-generated JSON samples."""
    if not os.path.isdir(SAMPLES_DIR):
        return JSONResponse({"files": [], "dir": SAMPLES_DIR})
    files = sorted(f for f in os.listdir(SAMPLES_DIR) if f.endswith(".json"))
    return JSONResponse({"files": files, "count": len(files)})

@app.get("/api/samples/{filename}")
async def get_sample(filename: str):
    """Return the content of one sample JSON."""
    # Security: only allow simple filenames, no path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = os.path.join(SAMPLES_DIR, filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="File not found")
    with open(path, encoding="utf-8") as f:
        return JSONResponse(json.load(f))

# ── Main page ─────────────────────────────────────────────────────────────────
@app.get("/")
async def main_page():
    html_content = r"""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Генератор проектной документации</title>
    <style id="theme-styles">
        :root {
            --primary: #4F46E5; --primary-hover: #4338CA;
            --bg: #F3F4F6; --card-bg: #FFFFFF;
            --text-main: #1F2937; --text-muted: #6B7280;
            --border: #E5E7EB;
            --source-bg: #DBEAFE; --source-text: #1E40AF;
            --green: #10B981; --green-hover: #059669;
            --conflict-bg: #FEF3C7; --conflict-text: #92400E;
            --shadow: 0 10px 15px -3px rgba(0,0,0,.1);
        }
        * { box-sizing: border-box; }
        body { font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text-main); padding: 40px 20px; margin: 0; line-height: 1.5; }
        .container { max-width: 800px; margin: 0 auto; background: var(--card-bg); padding: 40px; border-radius: 12px; box-shadow: 0 10px 15px -3px rgba(0,0,0,.1); }
        h1, h2, h3 { color: var(--text-main); }
        h1 { text-align: center; margin-top: 0; }
        p { color: var(--text-muted); }

        /* ── Tabs ── */
        .tab-bar { display: flex; gap: 8px; margin-bottom: 28px; border-bottom: 2px solid var(--border); padding-bottom: 0; }
        .tab-btn { background: none; border: none; padding: 10px 20px; font-size: 15px; font-weight: 600; color: var(--text-muted); cursor: pointer; border-bottom: 3px solid transparent; margin-bottom: -2px; border-radius: 0; width: auto; transition: color .2s, border-color .2s; }
        .tab-btn:hover { color: var(--primary); }
        .tab-btn.active { color: var(--primary); border-bottom-color: var(--primary); }

        /* ── Upload zone ── */
        .upload-zone { border: 2px dashed var(--border); padding: 32px; text-align: center; border-radius: 8px; margin-bottom: 20px; transition: border-color .3s; }
        .upload-zone:hover { border-color: var(--primary); }
        input[type="file"] { margin-bottom: 10px; }

        /* ── Buttons ── */
        button { background: var(--primary); color: white; padding: 12px 24px; border: none; border-radius: 6px; font-size: 16px; font-weight: 600; cursor: pointer; width: 100%; transition: background .2s; }
        button:hover { background: var(--primary-hover); }
        .btn-green { background: var(--green); }
        .btn-green:hover { background: var(--green-hover); }
        .btn-gray { background: var(--text-muted); }
        .btn-gray:hover { background: #4B5563; }
        .btn-row { display: flex; gap: 10px; margin-top: 10px; }
        .btn-row button { flex: 1; }

        /* ── Loading ── */
        #loading-screen { display: none; text-align: center; padding: 40px 0; }
        .spinner { width: 60px; height: 60px; border: 5px solid var(--border); border-top: 5px solid var(--primary); border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 20px; }
        @keyframes spin { to { transform: rotate(360deg); } }

        /* ── Progress Visualization ── */
        .progress-container { max-width: 600px; margin: 30px auto; text-align: left; }
        .phase-header { display: flex; align-items: center; gap: 10px; margin-bottom: 15px; font-weight: 600; color: var(--text-main); }
        .phase-badge { background: var(--primary); color: white; padding: 4px 12px; border-radius: 20px; font-size: 12px; }
        .file-progress-list { display: flex; flex-direction: column; gap: 8px; }
        .file-progress-item { display: flex; align-items: center; gap: 12px; padding: 10px 15px; background: var(--bg); border-radius: 8px; border: 1px solid var(--border); transition: all .3s; }
        .file-progress-item.processing { border-color: var(--primary); background: var(--source-bg); }
        .file-progress-item.done { border-color: var(--green); }
        .file-icon { font-size: 20px; }
        .file-name { flex: 1; font-size: 14px; color: var(--text-main); }
        .file-status { font-size: 12px; color: var(--text-muted); }
        .mini-spinner { width: 16px; height: 16px; border: 2px solid var(--border); border-top-color: var(--primary); border-radius: 50%; animation: spin 1s linear infinite; }
        .checkmark { color: var(--green); font-size: 18px; font-weight: bold; }
        .overall-progress { margin-top: 25px; }
        .progress-bar-bg { height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; }
        .progress-bar-fill { height: 100%; background: linear-gradient(90deg, var(--primary), var(--green)); width: 0%; transition: width .5s ease; border-radius: 4px; }
        .progress-stats { display: flex; justify-content: space-between; margin-top: 10px; font-size: 13px; color: var(--text-muted); }

        /* ── Result ── */
        #result-screen { display: none; }
        .result-section { margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
        .result-section h3 { color: var(--primary); margin-bottom: 8px; font-size: 18px; }
        ul { margin-top: 0; padding-left: 20px; }
        li { margin-bottom: 10px; color: var(--text-main); }
        .source-badge { display: inline-block; background: var(--source-bg); color: var(--source-text); font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 12px; margin-left: 8px; vertical-align: middle; }
        .meta-data { background: var(--bg); padding: 15px; border-radius: 6px; font-size: 14px; margin-top: 20px; border-left: 4px solid var(--primary); }

        /* ── Archive browser ── */
        .archive-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
        .archive-header h3 { margin: 0; font-size: 16px; }
        .archive-count { font-size: 13px; color: var(--text-muted); background: var(--bg); padding: 3px 10px; border-radius: 10px; }
        .archive-search { width: 100%; padding: 9px 12px; border: 1px solid var(--border); border-radius: 6px; font-size: 14px; margin-bottom: 12px; outline: none; }
        .archive-search:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(79,70,229,.15); }
        .archive-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; max-height: 380px; overflow-y: auto; padding-right: 4px; }
        .archive-card { border: 1px solid var(--border); border-radius: 8px; padding: 12px 14px; cursor: pointer; transition: border-color .2s, box-shadow .2s, background .2s; }
        .archive-card:hover { border-color: var(--primary); box-shadow: 0 2px 8px rgba(79,70,229,.15); background: #F5F3FF; }
        .archive-card .card-name { font-weight: 600; font-size: 13px; color: var(--text-main); }
        .archive-card .card-meta { font-size: 12px; color: var(--text-muted); margin-top: 4px; }
        .archive-card .card-conflicts { display: inline-block; font-size: 11px; font-weight: 600; margin-top: 6px; padding: 2px 8px; border-radius: 10px; background: #FEF3C7; color: #92400E; }
        .archive-card .card-conflicts.none { background: #D1FAE5; color: #065F46; }
        .archive-empty { text-align: center; padding: 40px 20px; color: var(--text-muted); font-size: 14px; }
        .divider { display: flex; align-items: center; gap: 12px; margin: 20px 0; color: var(--text-muted); font-size: 13px; }
        .divider::before, .divider::after { content: ''; flex: 1; height: 1px; background: var(--border); }

        /* ── JSON viewer source badge (viewer mode indicator) ── */
        .viewer-badge { display: inline-block; background: #EDE9FE; color: #6D28D9; font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 8px; margin-left: 10px; vertical-align: middle; }

        /* ── Completeness Score ── */
        .score-badge { display: inline-flex; align-items: center; gap: 6px; background: linear-gradient(135deg, var(--primary), var(--green)); color: white; padding: 6px 14px; border-radius: 20px; font-size: 14px; font-weight: 700; margin-left: 10px; vertical-align: middle; }
        .score-badge.low { background: linear-gradient(135deg, #EF4444, #F59E0B); }
        .score-badge.medium { background: linear-gradient(135deg, #F59E0B, #10B981); }

        /* ── Conflict Modal ── */
        .modal-overlay { display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.6); backdrop-filter: blur(4px); z-index: 2000; justify-content: center; align-items: center; padding: 20px; }
        .modal-content { background: var(--card-bg); border-radius: 16px; max-width: 700px; width: 100%; max-height: 80vh; overflow: hidden; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25); }
        .modal-header { display: flex; align-items: center; justify-content: space-between; padding: 20px 24px; border-bottom: 1px solid var(--border); }
        .modal-header h3 { margin: 0; color: var(--conflict-text); }
        .modal-close { background: none; border: none; font-size: 24px; color: var(--text-muted); cursor: pointer; width: auto; padding: 0; }
        .modal-body { padding: 24px; overflow-y: auto; max-height: 60vh; }
        .diff-container { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 20px; }
        .diff-box { background: var(--bg); border-radius: 8px; padding: 16px; border: 2px solid var(--border); }
        .diff-box.highlight { border-color: var(--conflict-text); background: var(--conflict-bg); }
        .diff-box h4 { margin: 0 0 10px; font-size: 13px; color: var(--text-muted); text-transform: uppercase; }
        .diff-box p { margin: 0; font-size: 14px; color: var(--text-main); }
        .conflict-actions { display: flex; gap: 10px; justify-content: center; margin-top: 20px; }
        .conflict-actions button { width: auto; padding: 10px 20px; }

        /* ── Enhanced Result Cards ── */
        .result-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; }
        .result-card { background: var(--bg); border-radius: 12px; padding: 20px; border: 1px solid var(--border); transition: transform .2s, box-shadow .2s; }
        .result-card:hover { transform: translateY(-2px); box-shadow: var(--shadow); }
        .result-card h4 { margin: 0 0 12px; color: var(--primary); font-size: 14px; text-transform: uppercase; }
        .result-card .value { font-size: 24px; font-weight: 700; color: var(--text-main); }
        .result-card .label { font-size: 12px; color: var(--text-muted); margin-top: 4px; }

        /* ── Animations ── */
        @keyframes fadeIn { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: translateY(0); } }
        .fade-in { animation: fadeIn 0.4s ease; }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
        .pulse { animation: pulse 2s ease-in-out infinite; }
    </style>
</head>
<body>
<div class="container">
    <h1>
        🧠 NeuralDocs
        <span style="font-size:12px;background:var(--primary);color:white;padding:4px 10px;border-radius:20px;vertical-align:middle;margin-left:8px;">AI</span>
    </h1>
    <p style="text-align:center;margin-top:-10px;margin-bottom:25px;color:var(--text-muted);">Интеллектуальный анализатор проектной документации</p>

    <!-- ═══════════════════════ UPLOAD SCREEN ═══════════════════════ -->
    <div id="upload-screen">
        <div class="tab-bar">
            <button class="tab-btn active" onclick="switchTab('generate')">📝 Создать документ</button>
            <button class="tab-btn" onclick="switchTab('load')">📂 Загрузить документ</button>
        </div>

        <!-- Tab 1: Generate -->
        <div id="tab-generate">
            <p style="text-align:center;margin-bottom:20px;">Загрузите файлы проекта — мы извлечем структурированную информацию и найдем противоречия между документами.</p>
            <form id="upload-form">
                <div class="upload-zone">
                    <p style="margin:0 0 15px;color:var(--text-muted);">📁 Перетащите файлы или выберите</p>
                    <input type="file" id="file-input" name="files" multiple required accept=".txt,.md,.json,.py,.java,.docx,.pdf">
                    <p style="margin:10px 0 0;font-size:12px;color:var(--text-muted);">Поддерживаемые форматы: TXT, MD, JSON, PY, Java, DOCX, PDF</p>
                </div>
                <button type="submit">🔍 Анализировать документы</button>
            </form>
        </div>

        <!-- Tab 2: Load JSON -->
        <div id="tab-load" style="display:none;">

            <!-- Local file picker -->
            <div class="upload-zone" id="json-drop-zone">
                <p style="margin:0 0 10px;font-weight:600;color:var(--text-main);">📤 Загрузить JSON с устройства</p>
                <input type="file" id="json-file-input" accept=".json">
                <p style="margin:8px 0 0;font-size:13px;color:var(--text-muted);">Откройте ранее сохраненный документ</p>
            </div>

            <div class="divider">или</div>

            <!-- Archive browser -->
            <div class="archive-header">
                <h3>📚 Библиотека примеров</h3>
                <span class="archive-count" id="archive-count">загрузка...</span>
            </div>
            <input class="archive-search" type="text" id="archive-search" placeholder="🔍 Поиск по проектам..." oninput="filterArchive()">
            <div class="archive-grid" id="archive-grid">
                <div class="archive-empty">Загрузка библиотеки...</div>
            </div>
        </div>
    </div>

    <!-- ═══════════════════════ LOADING SCREEN ═══════════════════════ -->
    <div id="loading-screen">
        <div class="spinner"></div>
        <h3>Анализ документов...</h3>
        <p style="color:var(--text-muted);">Нейросеть извлекает информацию из каждого файла</p>

        <div class="progress-container">
            <div class="phase-header">
                <span class="phase-badge">ШАГ 1</span>
                <span>Чтение и анализ файлов</span>
            </div>
            <div class="file-progress-list" id="file-progress-list">
                <!-- Dynamically populated -->
            </div>

            <div class="phase-header" style="margin-top: 20px;">
                <span class="phase-badge" style="background: var(--green);">ШАГ 2</span>
                <span>Сборка итогового документа</span>
            </div>
            <div class="overall-progress">
                <div class="progress-bar-bg">
                    <div class="progress-bar-fill" id="overall-progress-bar"></div>
                </div>
                <div class="progress-stats">
                    <span id="progress-text">Обработано: 0 файлов</span>
                    <span id="token-counter">0 токенов</span>
                </div>
            </div>
        </div>
    </div>

    <!-- ═══════════════════════ RESULT SCREEN ═══════════════════════ -->
    <div id="result-screen">
        <h2 id="result-title">📋 Структурированный документ</h2>
        <div id="parsed-content"></div>
        <div class="meta-data" id="meta-content"></div>
        <div class="btn-row" style="margin-top:20px;">
            <button class="btn-green" id="download-btn">📥 Скачать JSON</button>
            <button class="btn-gray" id="load-another-btn" style="display:none;">📄 Загрузить другой JSON</button>
        </div>
        <button class="btn-gray" id="reset-btn" style="margin-top:10px;">← Начать заново</button>
    </div>
</div>

<!-- ═══════════════════════ CONFLICT MODAL ═══════════════════════ -->
<div class="modal-overlay" id="conflict-modal" onclick="closeModalOnOverlay(event)">
    <div class="modal-content">
        <div class="modal-header">
            <h3>⚠️ Конфликт данных</h3>
            <button class="modal-close" onclick="closeConflictModal()">&times;</button>
        </div>
        <div class="modal-body">
            <p style="color: var(--text-muted); margin-bottom: 20px;">Обнаружены различия в данных из разных источников:</p>
            <div class="diff-container" id="diff-container">
                <!-- Dynamically populated -->
            </div>
            <p style="text-align: center; color: var(--text-muted); font-size: 13px;">Система автоматически выбрала последнее значение. Проверьте исходные документы.</p>
        </div>
    </div>
</div>

<script>
// ─────────────────────────────────────────────────────────────────────────────
// STATE
// ─────────────────────────────────────────────────────────────────────────────
let currentRawData = null;
let allArchiveFiles = [];   // [{name, conflicts, tokens, duration}]
let viewerMode = false;     // true when viewing a loaded JSON (not generated)

// ─────────────────────────────────────────────────────────────────────────────
// PROGRESS VISUALIZATION
// ─────────────────────────────────────────────────────────────────────────────
let fileProgressState = [];

function initFileProgress(fileNames) {
    fileProgressState = fileNames.map(name => ({ name, status: 'pending', tokens: 0 }));
    renderFileProgress();
}

function updateFileProgress(fileName, status, tokens = 0) {
    const file = fileProgressState.find(f => f.name === fileName);
    if (file) {
        file.status = status;
        file.tokens = tokens;
    }
    renderFileProgress();
    updateOverallProgress();
}

function renderFileProgress() {
    const container = document.getElementById('file-progress-list');
    container.innerHTML = fileProgressState.map(f => {
        const icon = f.status === 'done' ? '<span class="checkmark">✓</span>' :
                     f.status === 'processing' ? '<div class="mini-spinner"></div>' :
                     '<span style="color: var(--text-muted);">○</span>';
        const cls = f.status === 'processing' ? 'processing' : f.status === 'done' ? 'done' : '';
        const statusText = f.status === 'done' ? `${f.tokens} токенов` :
                           f.status === 'processing' ? 'Обработка...' : 'Ожидание';
        return `
            <div class="file-progress-item ${cls}">
                <span class="file-icon">📄</span>
                <span class="file-name">${f.name}</span>
                <span class="file-status">${icon} ${statusText}</span>
            </div>
        `;
    }).join('');
}

function updateOverallProgress() {
    const total = fileProgressState.length;
    const done = fileProgressState.filter(f => f.status === 'done').length;
    const percent = total > 0 ? (done / total) * 100 : 0;
    document.getElementById('overall-progress-bar').style.width = percent + '%';
    document.getElementById('progress-text').textContent = `Файлов обработано: ${done}/${total}`;
    const totalTokens = fileProgressState.reduce((sum, f) => sum + f.tokens, 0);
    document.getElementById('token-counter').textContent = totalTokens.toLocaleString() + ' токенов';
}

// ─────────────────────────────────────────────────────────────────────────────
// CONFLICT MODAL
// ─────────────────────────────────────────────────────────────────────────────
let currentConflict = null;

function showConflictModal(fieldName, conflictDetails, sources) {
    const modal = document.getElementById('conflict-modal');
    const container = document.getElementById('diff-container');

    // Parse conflict details to extract sources
    const diffHtml = sources.map((src, idx) => `
        <div class="diff-box ${idx === sources.length - 1 ? 'highlight' : ''}">
            <h4>${src.file}, строка ${src.line}</h4>
            <p>${src.value}</p>
        </div>
    `).join('');

    container.innerHTML = diffHtml;
    modal.style.display = 'flex';
}

function closeConflictModal() {
    document.getElementById('conflict-modal').style.display = 'none';
}

function closeModalOnOverlay(e) {
    if (e.target === e.currentTarget) closeConflictModal();
}

// ─────────────────────────────────────────────────────────────────────────────
// COMPLETENESS SCORE
// ─────────────────────────────────────────────────────────────────────────────
function calculateCompletenessScore(doc) {
    const fields = [
        { key: 'project_overview', weight: 10 },
        { key: 'goals', weight: 15, isArray: true },
        { key: 'requirements', weight: 15, isArray: true },
        { key: 'technical_solution', weight: 15 },
        { key: 'architecture', weight: 10 },
        { key: 'team', weight: 10, isArray: true },
        { key: 'timeline', weight: 10 },
        { key: 'budget', weight: 10 },
        { key: 'risks', weight: 5, isArray: true }
    ];

    let score = 0;
    fields.forEach(field => {
        const value = doc[field.key];
        if (field.isArray) {
            if (value && value.length > 0) {
                // Rich format: [{text: ...}]  |  Spec format: ["string", ...]
                const first = value[0];
                const text = (typeof first === 'object' && first !== null) ? (first.text || '') : String(first || '');
                if (text && !text.includes('отсутству')) score += field.weight;
            }
        } else {
            // Rich format: {text: ...}  |  Spec format: "string"
            const text = (value && typeof value === 'object') ? (value.text || '') : String(value || '');
            if (text && text.length > 10 && !text.includes('отсутству')) score += field.weight;
        }
    });

    return Math.round(score);
}

function getScoreClass(score) {
    if (score >= 80) return '';
    if (score >= 50) return 'medium';
    return 'low';
}

// ─────────────────────────────────────────────────────────────────────────────
// TAB SWITCHING
// ─────────────────────────────────────────────────────────────────────────────
function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.getElementById('tab-generate').style.display = 'none';
    document.getElementById('tab-load').style.display = 'none';

    if (tab === 'generate') {
        document.getElementById('tab-generate').style.display = 'block';
        document.querySelectorAll('.tab-btn')[0].classList.add('active');
    } else {
        document.getElementById('tab-load').style.display = 'block';
        document.querySelectorAll('.tab-btn')[1].classList.add('active');
        loadArchiveList();
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// GENERATE FORM
// ─────────────────────────────────────────────────────────────────────────────
document.getElementById('upload-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    viewerMode = false;

    const files = document.getElementById('file-input').files;
    const fileNames = Array.from(files).map(f => f.name);

    // Initialize progress visualization
    initFileProgress(fileNames);
    showScreen('loading');

    // Simulate progress for each file (since we don't have streaming yet)
    const progressInterval = setInterval(() => {
        const pendingFiles = fileProgressState.filter(f => f.status === 'pending');
        if (pendingFiles.length > 0) {
            const nextFile = pendingFiles[0];
            updateFileProgress(nextFile.name, 'processing');
            setTimeout(() => {
                updateFileProgress(nextFile.name, 'done', Math.floor(Math.random() * 500) + 200);
            }, 800 + Math.random() * 1000);
        }
    }, 1500);

    const formData = new FormData();
    for (let i = 0; i < files.length; i++) formData.append('files', files[i]);
    
    // Default language is Russian
    formData.append('language', 'ru');

    try {
        const resp = await fetch('/generate_document', { method: 'POST', body: formData });
        clearInterval(progressInterval);
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || 'Неизвестная ошибка сервера');
        }
        const data = await resp.json();
        showResult(data, false);
    } catch (err) {
        clearInterval(progressInterval);
        alert('Ошибка: ' + err.message);
        showScreen('upload');
    }
});

// ─────────────────────────────────────────────────────────────────────────────
// LOCAL JSON FILE PICKER
// ─────────────────────────────────────────────────────────────────────────────
document.getElementById('json-file-input').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
        try {
            const data = JSON.parse(ev.target.result);
            showResult(data, true, file.name);
        } catch {
            alert('Ошибка: файл не является валидным JSON');
        }
    };
    reader.readAsText(file, 'utf-8');
});

// ─────────────────────────────────────────────────────────────────────────────
// ARCHIVE BROWSER
// ─────────────────────────────────────────────────────────────────────────────
async function loadArchiveList() {
    if (allArchiveFiles.length > 0) return; // already loaded
    const grid = document.getElementById('archive-grid');
    try {
        const resp = await fetch('/api/samples');
        const data = await resp.json();
        document.getElementById('archive-count').textContent = `${data.count} файлов`;

        if (!data.files || data.files.length === 0) {
            grid.innerHTML = '<div class="archive-empty">Архив пуст. Запустите setup_v2.py для генерации образцов.</div>';
            return;
        }

        // Load metadata for each file (lightweight — just parse conflicts from filename hint via API)
        // We fetch all in parallel with Promise.all but limit batch to avoid flooding
        const BATCH = 20;
        allArchiveFiles = [];
        for (let i = 0; i < data.files.length; i += BATCH) {
            const batch = data.files.slice(i, i + BATCH);
            const results = await Promise.all(batch.map(name =>
                fetch(`/api/samples/${name}`)
                    .then(r => r.json())
                    .then(d => ({
                        name,
                        overview: (d.document && d.document.project_overview) ? d.document.project_overview.slice(0, 60) : '',
                        conflicts: (d.metadata && d.metadata.conflicts_found) || 0,
                        tokens: (d.metadata && d.metadata.total_tokens) || 0,
                        duration: (d.metadata && d.metadata.duration_ms) || 0,
                    }))
                    .catch(() => ({ name, overview: '', conflicts: 0, tokens: 0, duration: 0 }))
            ));
            allArchiveFiles.push(...results);
        }
        renderArchiveGrid(allArchiveFiles);
    } catch (err) {
        grid.innerHTML = `<div class="archive-empty">Не удалось загрузить архив: ${err.message}</div>`;
    }
}

function renderArchiveGrid(files) {
    const grid = document.getElementById('archive-grid');
    if (!files.length) {
        grid.innerHTML = '<div class="archive-empty">Ничего не найдено</div>';
        return;
    }
    grid.innerHTML = files.map(f => `
        <div class="archive-card" onclick="loadSampleByName('${f.name}')">
            <div class="card-name">📄 ${f.name}</div>
            <div class="card-meta" title="${f.overview}">${f.overview || 'Нет описания'}...</div>
            <div class="card-meta">🪙 ${f.tokens} токенов · ⏱ ${f.duration} мс</div>
            <span class="card-conflicts ${f.conflicts === 0 ? 'none' : ''}">
                ${f.conflicts === 0 ? '✓ Конфликтов нет' : '⚠️ Конфликтов: ' + f.conflicts}
            </span>
        </div>
    `).join('');
}

function filterArchive() {
    const q = document.getElementById('archive-search').value.toLowerCase();
    const filtered = allArchiveFiles.filter(f =>
        f.name.toLowerCase().includes(q) || f.overview.toLowerCase().includes(q)
    );
    renderArchiveGrid(filtered);
}

async function loadSampleByName(filename) {
    showScreen('loading');
    try {
        const resp = await fetch(`/api/samples/${encodeURIComponent(filename)}`);
        if (!resp.ok) throw new Error('Файл не найден');
        const data = await resp.json();
        showResult(data, true, filename);
    } catch (err) {
        alert('Ошибка загрузки: ' + err.message);
        showScreen('upload');
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// SHOW RESULT
// ─────────────────────────────────────────────────────────────────────────────
function showResult(data, isViewer, filename) {
    viewerMode = isViewer;
    currentRawData = data;

    const title = document.getElementById('result-title');
    const loadAnotherBtn = document.getElementById('load-another-btn');
    // Use the rich extended document for UI rendering if available (spec-compliant
    // plain-string `document` is for download/fine-tuning only)
    const doc = data.document_extended || data.document || {};

    // Calculate and show completeness score
    const score = calculateCompletenessScore(doc);
    const scoreClass = getScoreClass(score);
    const scoreEmoji = score >= 80 ? '✅' : score >= 50 ? '⚠️' : '❌';

    if (isViewer) {
        title.innerHTML = `Просмотр документа <span class="viewer-badge">📄 ${filename || 'JSON'}</span><span class="score-badge ${scoreClass}">${scoreEmoji} ${score}%</span>`;
        loadAnotherBtn.style.display = 'block';
    } else {
        title.innerHTML = `Результат генерации: <span class="score-badge ${scoreClass}">${scoreEmoji} ${score}%</span>`;
        loadAnotherBtn.style.display = 'none';
    }

    renderResults(data);
    showScreen('result');
}

// ─────────────────────────────────────────────────────────────────────────────
// SCREEN SWITCHER
// ─────────────────────────────────────────────────────────────────────────────
function showScreen(name) {
    document.getElementById('upload-screen').style.display  = name === 'upload'  ? 'block' : 'none';
    document.getElementById('loading-screen').style.display = name === 'loading' ? 'block' : 'none';
    document.getElementById('result-screen').style.display  = name === 'result'  ? 'block' : 'none';
}

// ─────────────────────────────────────────────────────────────────────────────
// RENDER RESULTS  (unchanged logic — used by both generate and viewer paths)
// ─────────────────────────────────────────────────────────────────────────────
function renderResults(data) {
    // Prefer rich extended document for UI (has source badges & conflict details).
    // Plain-string spec `document` is used for download/fine-tuning.
    const doc  = data.document_extended || data.document || {};
    const meta = data.metadata  || {};
    const container = document.getElementById('parsed-content');
    
    // Get current language from dropdown
    const currentLang = document.getElementById('output-language')?.value || 'ru';
    
    // Multilingual labels
    const labels = {
        ru: {
            project_overview: 'Обзор проекта',
            goals: 'Цели проекта',
            requirements: 'Требования',
            technical_solution: 'Техническое решение',
            architecture: 'Архитектура',
            team: 'Команда',
            timeline: 'Сроки',
            budget: 'Бюджет',
            risks: 'Риски',
            no_data: 'Нет данных',
            conflict_click: 'Конфликт (клик для деталей)',
            conflicts_found: 'Обнаружено противоречий',
            conflict_desc: 'Найдены несовместимые данные в документах:',
            metadata: 'Статистика обработки',
            files_processed: 'Файлов проанализировано',
            final_assembly: 'Сборка документа',
            tokens: 'Токенов обработано',
            duration: 'Время обработки',
            ms: 'мс'
        },
        en: {
            project_overview: 'Project Overview',
            goals: 'Project Goals',
            requirements: 'Requirements',
            technical_solution: 'Technical Solution',
            architecture: 'Architecture',
            team: 'Team',
            timeline: 'Timeline',
            budget: 'Budget',
            risks: 'Risks',
            no_data: 'No data available',
            conflict_click: 'Conflict (click for details)',
            conflicts_found: 'Conflicts detected',
            conflict_desc: 'Inconsistent data found across documents:',
            metadata: 'Processing statistics',
            files_processed: 'Files analyzed',
            final_assembly: 'Document assembly',
            tokens: 'Tokens processed',
            duration: 'Processing time',
            ms: 'ms'
        },
        kz: {
            project_overview: 'Жоба шолуы',
            goals: 'Жоба мақсаттары',
            requirements: 'Талаптар',
            technical_solution: 'Техникалық шешім',
            architecture: 'Архитектура',
            team: 'Команда',
            timeline: 'Мерзімдер',
            budget: 'Бюджет',
            risks: 'Тәуекелдер',
            no_data: 'Деректер жоқ',
            conflict_click: 'Қақтығыс (толықтыру үшін басыңыз)',
            conflicts_found: 'Қақтығыстар анықталды',
            conflict_desc: 'Құжаттарда сәйкес емес деректер табылды:',
            metadata: 'Өңдеу статистикасы',
            files_processed: 'Талданған файлдар',
            final_assembly: 'Құжатты жинау',
            tokens: 'Өңделген токендер',
            duration: 'Өңдеу уақыты',
            ms: 'мс'
        }
    };
    
    const t = labels[currentLang] || labels.ru;

    const makeFact = (fact, fieldName = '') => {
        // Handle plain string (spec format fallback)
        if (typeof fact === 'string') {
            return fact && fact.length > 1 && !fact.includes('отсутству')
                ? `<span>${fact}</span>`
                : `<span style="color:var(--text-muted);font-style:italic;">${t.no_data}</span>`;
        }
        if (!fact) return `<span style="color:var(--text-muted);font-style:italic;">${t.no_data}</span>`;
        // Rich format: if text is empty but source is present, show "Источник: …" hint
        if (!fact.text || !fact.text.trim()) {
            if (fact.source && !fact.source.includes('файл.txt')) {
                return `<span style="color:var(--text-muted);font-style:italic;">Нет текста</span><span class="source-badge">📄 ${fact.source}</span>`;
            }
            return `<span style="color:var(--text-muted);font-style:italic;">${t.no_data}</span>`;
        }
        const badgeStyle = (fact.source === 'Нет источника' || (fact.source || '').includes('отсутству'))
            ? 'background:#F3F4F6;color:#6B7280;' : '';
        let html = `<span>${fact.text}</span><span class="source-badge" style="${badgeStyle}">📄 ${fact.source || '—'}</span>`;
        if (fact.has_conflict) {
            const conflictId = `conflict-${fieldName}-${Math.random().toString(36).substr(2, 9)}`;
            // Parse conflict details to extract sources
            const sources = parseConflictDetails(fact.conflict_details);
            html += `
            <div style="margin-top:8px;margin-bottom:8px;background:var(--conflict-bg);border-left:4px solid #F59E0B;padding:10px 14px;font-size:13.5px;color:var(--conflict-text);border-radius:0 4px 4px 0;cursor:pointer;"
                 onclick='showConflictFromData(${JSON.stringify(fact.conflict_details).replace(/'/g, "&#39;")})'>
                <strong style="display:block;margin-bottom:4px;">⚠️ ${t.conflict_click}:</strong>
                ${fact.conflict_details}
            </div>`;
        }
        return html;
    };

    // Helper to parse conflict details
    function parseConflictDetails(details) {
        const sources = [];
        const regex = /([^;]+?) — ([^;]+)/g;
        let match;
        while ((match = regex.exec(details)) !== null) {
            const fileLine = match[1].trim();
            const value = match[2].trim();
            const fileMatch = fileLine.match(/(.+?),\s*\[(\d+)\]/);
            if (fileMatch) {
                sources.push({ file: fileMatch[1], line: fileMatch[2], value });
            } else {
                sources.push({ file: fileLine, line: '?', value });
            }
        }
        return sources.length > 0 ? sources : [{ file: 'Неизвестно', line: '?', value: details }];
    }

    window.showConflictFromData = function(conflictDetails) {
        const sources = parseConflictDetails(conflictDetails);
        const modal = document.getElementById('conflict-modal');
        const container = document.getElementById('diff-container');

        const diffHtml = sources.map((src, idx) => `
            <div class="diff-box ${idx === 0 ? 'highlight' : ''}">
                <h4>${src.file}, строка ${src.line}</h4>
                <p>${src.value}</p>
            </div>
        `).join('');

        container.innerHTML = diffHtml;
        modal.style.display = 'flex';
    };

    const makeFactList = (items) => {
        if (!items || items.length === 0) return `<p style="color:var(--text-muted);font-style:italic;">${t.no_data}</p>`;
        // Filter out items that are completely empty (empty string or object with empty text)
        const nonEmpty = items.filter(item => {
            if (typeof item === 'string') return item.trim().length > 0;
            if (typeof item === 'object' && item !== null) {
                // Keep items that have real text OR a real conflict to show
                const hasText = (item.text || '').trim().length > 0;
                const hasSource = item.source && !item.source.includes('файл.txt');
                return hasText || hasSource || item.has_conflict;
            }
            return false;
        });
        if (nonEmpty.length === 0) return `<p style="color:var(--text-muted);font-style:italic;">${t.no_data}</p>`;
        return `<ul>${nonEmpty.map(item => `<li>${makeFact(item)}</li>`).join('')}</ul>`;
    };

    // Conflict summary banner
    const conflictsCount = meta.conflicts_found || 0;
    let conflictBannerHtml = '';
    if (conflictsCount > 0) {
        const fieldLabels = {
            timeline: t.timeline, budget: t.budget,
            technical_solution: t.technical_solution, architecture: t.architecture,
            goals: t.goals, requirements: t.requirements, team: t.team, risks: t.risks
        };
        const conflictItems = [];
        ['timeline','budget','technical_solution','architecture'].forEach(key => {
            const f = doc[key];
            if (f && f.has_conflict && f.conflict_details)
                conflictItems.push(`<li><strong>${fieldLabels[key]}:</strong> ${f.conflict_details}</li>`);
        });
        ['goals','requirements','team','risks'].forEach(key => {
            (doc[key] || []).forEach((f, i) => {
                if (f && f.has_conflict && f.conflict_details)
                    conflictItems.push(`<li><strong>${fieldLabels[key]} [${i+1}]:</strong> ${f.conflict_details}</li>`);
            });
        });
        conflictBannerHtml = `
        <div style="background:#FEF3C7;border:2px solid #F59E0B;border-radius:8px;padding:16px 20px;margin-bottom:24px;">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
                <span style="font-size:22px;">⚠️</span>
                <strong style="font-size:16px;color:#92400E;">${t.conflicts_found}: ${conflictsCount}</strong>
            </div>
            <p style="margin:4px 0 0;color:#B45309;font-size:14px;">${t.conflict_desc}</p>
            <ul style="margin:8px 0 0;padding-left:20px;color:#92400E;font-size:13.5px;">${conflictItems.join('')}</ul>
        </div>`;
    }

    container.innerHTML = conflictBannerHtml + `
        <div class="result-section fade-in"><h3>${t.project_overview}</h3><p>${doc.project_overview || t.no_data}</p></div>
        <div class="result-section fade-in"><h3>${t.goals}</h3>${makeFactList(doc.goals)}</div>
        <div class="result-section fade-in"><h3>${t.requirements}</h3>${makeFactList(doc.requirements)}</div>
        <div class="result-section fade-in"><h3>${t.technical_solution}</h3><p>${makeFact(doc.technical_solution, 'technical_solution')}</p></div>
        <div class="result-section fade-in"><h3>${t.architecture}</h3><p>${makeFact(doc.architecture, 'architecture')}</p></div>
        <div class="result-section fade-in"><h3>${t.team}</h3>${makeFactList(doc.team)}</div>
        <div class="result-section fade-in">
            <h3>${t.timeline} & ${t.budget}</h3>
            <p><strong>${t.timeline}:</strong> ${makeFact(doc.timeline, 'timeline')}</p>
            <p><strong>${t.budget}:</strong> ${makeFact(doc.budget, 'budget')}</p>
        </div>
        <div class="result-section fade-in"><h3>${t.risks}</h3>${makeFactList(doc.risks)}</div>
    `;

    document.getElementById('meta-content').innerHTML = `
        <strong>${t.metadata}:</strong><br>
        ${t.files_processed}: ${(meta.llm_calls || 1) - 1}<br>
        ${t.final_assembly}: 1<br>
        ${t.conflicts_found}: <strong>${conflictsCount}</strong><br>
        ${t.tokens}: ${meta.total_tokens || 0} &nbsp;|&nbsp; ${t.duration}: ${meta.duration_ms || 0} ${t.ms}
    `;
}

// ─────────────────────────────────────────────────────────────────────────────
// BUTTONS
// ─────────────────────────────────────────────────────────────────────────────
document.getElementById('download-btn').addEventListener('click', () => {
    const blob = new Blob([JSON.stringify(currentRawData, null, 4)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = 'map_reduce_doc.json'; a.click();
    URL.revokeObjectURL(url);
});

document.getElementById('load-another-btn').addEventListener('click', () => {
    showScreen('upload');
    switchTab('load');
});

document.getElementById('reset-btn').addEventListener('click', () => {
    document.getElementById('file-input').value = '';
    document.getElementById('json-file-input').value = '';
    showScreen('upload');
    switchTab('generate');
});
</script>
</body>
</html>
"""
    return HTMLResponse(content=html_content)

# ── Generate endpoint ─────────────────────────────────────────────
@app.post("/generate_document")
async def generate_document(files: List[UploadFile] = File(...), language: str = Form("ru")):
    files_data = []
    for file in files:
        content = await file.read()
        text = content.decode('utf-8', errors='ignore')
        files_data.append({"filename": file.filename, "content": text})
    try:
        result = current_llm.generate_document(files_data, language=language)
        return result
    except Exception as e:
        error_msg = str(e)
        if "Connection error" in error_msg or "ConnectError" in error_msg:
            detail_msg = f"Не удалось подключиться к локальному серверу LM Studio по адресу {LOCAL_PC_IP}."
        else:
            detail_msg = f"Ошибка обработки: {error_msg}"
        raise HTTPException(status_code=500, detail=detail_msg)
