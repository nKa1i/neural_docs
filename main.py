import os
import time
import json
from typing import List
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
        # Language prompts
        lang_prompts = {
            "ru": {
                "map_instruction": """Ты - безэмоциональный парсер текста. Твоя единственная задача - скопировать из текста все факты, цифры и требования, сохранив номер строки.

ОТВЕЧАЙ СТРОГО В ФОРМАТЕ:
[Номер строки] Факт: "цитата или точный пересказ"

ВАЖНО: Обязательно извлекай все числовые значения — суммы денег, сроки в месяцах или неделях, версии, размеры команд. Каждое число должно быть отдельной строкой факта.
Не придумывай ничего своего. Ничего не анализируй. Просто выписывай факты. Если фактов нет, пиши "Пусто".""",
                "missing_data": "Данные отсутствуют"
            },
            "en": {
                "map_instruction": """You are an emotionless text parser. Your only task is to copy all facts, numbers and requirements from the text, preserving the line number.

ANSWER STRICTLY IN FORMAT:
[Line number] Fact: "quote or exact summary"

IMPORTANT: Always extract all numeric values — money amounts, deadlines in months or weeks, versions, team sizes. Each number should be a separate fact line.
Do not make up anything. Do not analyze anything. Just list the facts. If no facts, write "Empty".""",
                "missing_data": "No data available"
            },
            "kz": {
                "map_instruction": """Сіз - эмоциясыз мәтін талдаушысыз. Сіздің бірден бір міндетіңіз - мәтіннен барлық фактілерді, сандарды және талаптарды көшіру, жол нөмірін сақтай отырып.

ҚАТЫ ОТЫРЫП ЖАУАП БЕРІҢІЗ:
[Жол нөмірі] Факт: "дәйек немесе нақты қорытынды"

МАҢЫЗДЫ: Барлық сандық мәндерді әрдайым шығарып алыңыз — ақша сомалары, ай немесе апта бойынша мерзімдер, нұсқалар, топ өлшемдері. Әрбір сан жеке факт жолы болуы керек.
Ештеңе ойлап таппаңыз. Ештеңе талдамаңыз. Жай фактілерді тізімдеңіз. Фактілер жоқ болса, "Бос" деп жазыңыз.""",
                "missing_data": "Деректер жоқ"
            }
        }
        prompts = lang_prompts.get(language, lang_prompts["ru"])

        start_time = time.time()
        total_tokens_used = 0
        all_extracted_facts = ""

        map_instruction = prompts["map_instruction"]

        for f in files_data:
            lines = f['content'].splitlines()
            numbered_text = "\n".join([f"[{i+1}] {line}" for i, line in enumerate(lines)])
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": map_instruction},
                    {"role": "user", "content": f"Файл: {f['filename']}\nТекст:\n{numbered_text}"}
                ],
                temperature=0.0
            )
            fact_summary = response.choices[0].message.content
            total_tokens_used += response.usage.total_tokens if response.usage else 0
            all_extracted_facts += f"\n\n--- ФАЙЛ: {f['filename']} ---\n{fact_summary}\n"

        json_template = """{
          "project_overview": "general description",
          "goals": [{"text": "goal description", "source": "filename, line N", "has_conflict": false, "conflict_details": ""}],
          "requirements": [{"text": "requirement", "source": "filename, line N", "has_conflict": false, "conflict_details": ""}],
          "technical_solution": {"text": "solution", "source": "filename, line N", "has_conflict": false, "conflict_details": ""},
          "architecture": {"text": "architecture", "source": "filename, line N", "has_conflict": false, "conflict_details": ""},
          "team": [{"text": "team member", "source": "filename, line N", "has_conflict": false, "conflict_details": ""}],
          "timeline": {"text": "final deadline", "source": "filename, line N", "has_conflict": true, "conflict_details": "Conflict: file_A, [N] — deadline_A; file_B, [M] — deadline_B"},
          "budget": {"text": "final budget", "source": "filename, line N", "has_conflict": true, "conflict_details": "Conflict: file_A, [N] — amount_A; file_B, [M] — amount_B"},
          "risks": [{"text": "risk", "source": "filename, line N", "has_conflict": false, "conflict_details": ""}]
        }"""

        reduce_instruction = f"""
You are a strict JSON generator. Assemble the final document from the provided facts.

STRICT RULES:
1. SOURCES: Always specify file and line (e.g., "budget_draft.txt, [4]").
2. CONFLICT LOCALIZATION:
   - Write money conflicts ONLY in "budget" block.
   - Write deadline conflicts ONLY in "timeline" block.
   - FORBIDDEN to write about budget in "requirements" or "goals".
3. MANDATORY CONFLICT DETECTION ALGORITHM:
   a) Before writing "budget" field, find ALL money mentions across ALL files. If amounts differ — set "has_conflict": true AND fill "conflict_details" in format: "Conflict: [file A, line N] — [amount A]; [file B, line M] — [amount B]".
   b) Before writing "timeline" field, find ALL deadline mentions across ALL files. Compare deadlines from ALL files — having two different numeric values is a conflict regardless of context. If deadlines differ — set "has_conflict": true AND fill "conflict_details" in same format.
   c) FORBIDDEN to leave "conflict_details" empty if "has_conflict" is true.
4. If no data for field, write "{prompts['missing_data']}".
5. Output must be in {language} language.

Output ONLY JSON strictly following the template below. No text before or after brackets {{ and }}.
TEMPLATE:
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

        try:
            parsed_data = json.loads(clean_json)
        except Exception:
            parsed_data = {"error": "Llama 3 вернула невалидный JSON", "raw_output": raw_content}

        duration_ms = int((end_time - start_time) * 1000)

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

        return {
            "document": parsed_data,
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
LOCAL_PC_IP = "127.0.0.1"
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
            <button class="tab-btn" onclick="switchTab('load')">� Открыть сохраненный</button>
        </div>

        <!-- Tab 1: Generate -->
        <div id="tab-generate">
            <div class="language-selector" style="text-align:center;margin-bottom:20px;">
                <label style="font-size:14px;color:var(--text-muted);margin-right:10px;">Язык выходного документа:</label>
                <select id="output-language" style="padding:8px 15px;border:1px solid var(--border);border-radius:6px;font-size:14px;background:var(--card-bg);color:var(--text-main);cursor:pointer;">
                    <option value="ru">🇷🇺 Русский</option>
                    <option value="en">🇬🇧 English</option>
                    <option value="kz">🇰🇿 Қазақша</option>
                </select>
            </div>
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
                <h3>� Библиотека примеров</h3>
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
            if (value && value.length > 0 && value[0].text && !value[0].text.includes('отсутству')) {
                score += field.weight;
            }
        } else {
            if (value && value.text && !value.text.includes('отсутству')) {
                score += field.weight;
            } else if (value && typeof value === 'string' && value.length > 10) {
                score += field.weight;
            }
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
    
    // Add selected language
    const selectedLang = document.getElementById('output-language').value;
    formData.append('language', selectedLang);

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
    const doc = data.document || {};

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
    const doc  = data.document  || {};
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
        if (!fact || !fact.text) return t.no_data;
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
        if (!items || items.length === 0) return `<p>${t.no_data}</p>`;
        return `<ul>${items.map(item => `<li>${makeFact(item)}</li>`).join('')}</ul>`;
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
