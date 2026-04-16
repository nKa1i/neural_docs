import os
import time
import json
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException
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

    def generate_document(self, files_data: list[dict]) -> dict:
        start_time = time.time()
        total_tokens_used = 0
        all_extracted_facts = ""

        map_instruction = """
        Ты - безэмоциональный парсер текста. Твоя единственная задача - скопировать из текста все факты, цифры и требования, сохранив номер строки.

        ОТВЕЧАЙ СТРОГО В ФОРМАТЕ:
        [Номер строки] Факт: "цитата или точный пересказ"

        ВАЖНО: Обязательно извлекай все числовые значения — суммы денег, сроки в месяцах или неделях, версии, размеры команд. Каждое число должно быть отдельной строкой факта.
        Не придумывай ничего своего. Ничего не анализируй. Просто выписывай факты. Если фактов нет, пиши "Пусто".
        """

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

        json_template = """
        {
          "project_overview": "строка с общим описанием",
          "goals": [{"text": "цель", "source": "имя_файла, строка N", "has_conflict": false, "conflict_details": ""}],
          "requirements": [{"text": "требование", "source": "имя_файла, строка N", "has_conflict": false, "conflict_details": ""}],
          "technical_solution": {"text": "решение", "source": "имя_файла, строка N", "has_conflict": false, "conflict_details": ""},
          "architecture": {"text": "архитектура", "source": "имя_файла, строка N", "has_conflict": false, "conflict_details": ""},
          "team": [{"text": "команда", "source": "имя_файла, строка N", "has_conflict": false, "conflict_details": ""}],
          "timeline": {"text": "наибольший или итоговый срок", "source": "имя_файла, строка N", "has_conflict": true, "conflict_details": "Конфликт: файл_A, [N] — срок_A; файл_B, [M] — срок_B"},
          "budget": {"text": "итоговый бюджет", "source": "имя_файла, строка N", "has_conflict": true, "conflict_details": "Конфликт: файл_A, [N] — сумма_A; файл_B, [M] — сумма_B"},
          "risks": [{"text": "риск", "source": "имя_файла, строка N", "has_conflict": false, "conflict_details": ""}]
        }
        """

        reduce_instruction = f"""
        Ты - строгий JSON-генератор. Собери итоговый документ из переданных фактов.

        ЖЕСТКИЕ ПРАВИЛА:
        1. ИСТОЧНИКИ: Всегда указывай файл и строку (например: "budget_draft.txt, [4]").
        2. ЛОКАЛИЗАЦИЯ КОНФЛИКТОВ:
           - Конфликты по деньгам пиши ТОЛЬКО в блок "budget".
           - Конфликты по срокам пиши ТОЛЬКО в блок "timeline".
           - ЗАПРЕЩЕНО писать о бюджете в "requirements" или "goals".
        3. ОБНАРУЖЕНИЕ КОНФЛИКТОВ — ОБЯЗАТЕЛЬНЫЙ АЛГОРИТМ:
           а) Перед записью поля "budget" найди ВСЕ упоминания денежных сумм во всех файлах. Если суммы различаются — установи "has_conflict": true И ОБЯЗАТЕЛЬНО заполни "conflict_details" в формате: "Конфликт: [файл A, строка N] — [сумма A]; [файл B, строка M] — [сумма B]".
           б) Перед записью поля "timeline" найди ВСЕ упоминания сроков во всех файлах. Сравни сроки из ВСЕХ файлов — наличие двух разных числовых значений (например, "8 месяцев" и "12 месяцев") является конфликтом независимо от контекста. Если сроки различаются — установи "has_conflict": true И заполни "conflict_details" в том же формате.
           в) ЗАПРЕЩЕНО оставлять "conflict_details" пустой строкой, если "has_conflict" равно true.
        4. Если данных для поля нет, пиши "Данные отсутствуют".

        Выведи ТОЛЬКО JSON строго по шаблону ниже. Никакого текста до или после скобок {{ и }}.
        ШАБЛОН:
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
    <style>
        :root {
            --primary: #4F46E5; --primary-hover: #4338CA;
            --bg: #F3F4F6; --card-bg: #FFFFFF;
            --text-main: #1F2937; --text-muted: #6B7280;
            --border: #E5E7EB;
            --source-bg: #DBEAFE; --source-text: #1E40AF;
            --green: #10B981; --green-hover: #059669;
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
        .spinner { width: 50px; height: 50px; border: 5px solid var(--border); border-top: 5px solid var(--primary); border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 20px; }
        @keyframes spin { to { transform: rotate(360deg); } }

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
    </style>
</head>
<body>
<div class="container">
    <h1>
        Документация
        <span style="font-size:14px;background:#FEF3C7;color:#D97706;padding:4px 8px;border-radius:8px;vertical-align:top;">Map-Reduce</span>
    </h1>

    <!-- ═══════════════════════ UPLOAD SCREEN ═══════════════════════ -->
    <div id="upload-screen">
        <div class="tab-bar">
            <button class="tab-btn active" onclick="switchTab('generate')">⚙️ Генерировать</button>
            <button class="tab-btn" onclick="switchTab('load')">📄 Загрузить JSON</button>
        </div>

        <!-- Tab 1: Generate -->
        <div id="tab-generate">
            <p style="text-align:center;">Система анализирует каждый файл <strong>изолированно</strong>, защищая от переполнения памяти, а затем объединяет факты.</p>
            <form id="upload-form">
                <div class="upload-zone">
                    <input type="file" id="file-input" name="files" multiple required accept=".txt,.md,.json,.py,.java">
                </div>
                <button type="submit">Анализировать (Map-Reduce)</button>
            </form>
        </div>

        <!-- Tab 2: Load JSON -->
        <div id="tab-load" style="display:none;">

            <!-- Local file picker -->
            <div class="upload-zone" id="json-drop-zone">
                <p style="margin:0 0 10px;font-weight:600;color:var(--text-main);">Загрузить JSON с устройства</p>
                <input type="file" id="json-file-input" accept=".json">
                <p style="margin:8px 0 0;font-size:13px;">Поддерживаются файлы формата map_reduce_doc.json</p>
            </div>

            <div class="divider">или выберите из архива</div>

            <!-- Archive browser -->
            <div class="archive-header">
                <h3>📂 Архив образцов</h3>
                <span class="archive-count" id="archive-count">загрузка...</span>
            </div>
            <input class="archive-search" type="text" id="archive-search" placeholder="🔍  Поиск по названию файла..." oninput="filterArchive()">
            <div class="archive-grid" id="archive-grid">
                <div class="archive-empty">Загрузка архива...</div>
            </div>
        </div>
    </div>

    <!-- ═══════════════════════ LOADING SCREEN ═══════════════════════ -->
    <div id="loading-screen">
        <div class="spinner"></div>
        <h3>Архитектура Map-Reduce в работе...</h3>
        <p>Шаг 1: Индивидуальный анализ файлов<br>Шаг 2: Синтез и поиск противоречий<br><em>Это может занять 10-30 секунд.</em></p>
    </div>

    <!-- ═══════════════════════ RESULT SCREEN ═══════════════════════ -->
    <div id="result-screen">
        <h2 id="result-title">Результат генерации:</h2>
        <div id="parsed-content"></div>
        <div class="meta-data" id="meta-content"></div>
        <div class="btn-row" style="margin-top:20px;">
            <button class="btn-green" id="download-btn">📥 Скачать JSON</button>
            <button class="btn-gray" id="load-another-btn" style="display:none;">📄 Загрузить другой JSON</button>
        </div>
        <button class="btn-gray" id="reset-btn" style="margin-top:10px;">← Начать заново</button>
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
    showScreen('loading');

    const formData = new FormData();
    const files = document.getElementById('file-input').files;
    for (let i = 0; i < files.length; i++) formData.append('files', files[i]);

    try {
        const resp = await fetch('/generate_document', { method: 'POST', body: formData });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || 'Неизвестная ошибка сервера');
        }
        const data = await resp.json();
        showResult(data, false);
    } catch (err) {
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

    if (isViewer) {
        title.innerHTML = `Просмотр документа <span class="viewer-badge">📄 ${filename || 'JSON'}</span>`;
        loadAnotherBtn.style.display = 'block';
    } else {
        title.innerHTML = 'Результат генерации:';
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

    const makeFact = (fact) => {
        if (!fact || !fact.text) return 'Нет данных';
        const badgeStyle = (fact.source === 'Нет источника' || (fact.source || '').includes('отсутству'))
            ? 'background:#F3F4F6;color:#6B7280;' : '';
        let html = `<span>${fact.text}</span><span class="source-badge" style="${badgeStyle}">📄 ${fact.source || '—'}</span>`;
        if (fact.has_conflict) {
            html += `
            <div style="margin-top:8px;margin-bottom:8px;background:#FEF3C7;border-left:4px solid #F59E0B;padding:10px 14px;font-size:13.5px;color:#92400E;border-radius:0 4px 4px 0;">
                <strong style="display:block;margin-bottom:4px;color:#B45309;">⚠️ Обнаружен конфликт:</strong>
                ${fact.conflict_details}
            </div>`;
        }
        return html;
    };

    const makeFactList = (items) => {
        if (!items || items.length === 0) return '<p>Нет данных</p>';
        return `<ul>${items.map(item => `<li>${makeFact(item)}</li>`).join('')}</ul>`;
    };

    // Conflict summary banner
    const conflictsCount = meta.conflicts_found || 0;
    let conflictBannerHtml = '';
    if (conflictsCount > 0) {
        const labels = {
            timeline: 'Сроки', budget: 'Бюджет',
            technical_solution: 'Техническое решение', architecture: 'Архитектура',
            goals: 'Цели', requirements: 'Требования', team: 'Команда', risks: 'Риски'
        };
        const conflictItems = [];
        ['timeline','budget','technical_solution','architecture'].forEach(key => {
            const f = doc[key];
            if (f && f.has_conflict && f.conflict_details)
                conflictItems.push(`<li><strong>${labels[key]}:</strong> ${f.conflict_details}</li>`);
        });
        ['goals','requirements','team','risks'].forEach(key => {
            (doc[key] || []).forEach((f, i) => {
                if (f && f.has_conflict && f.conflict_details)
                    conflictItems.push(`<li><strong>${labels[key]} [${i+1}]:</strong> ${f.conflict_details}</li>`);
            });
        });
        conflictBannerHtml = `
        <div style="background:#FEF3C7;border:2px solid #F59E0B;border-radius:8px;padding:16px 20px;margin-bottom:24px;">
            <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
                <span style="font-size:22px;">⚠️</span>
                <strong style="font-size:16px;color:#92400E;">Обнаружено противоречий: ${conflictsCount}</strong>
            </div>
            <p style="margin:4px 0 0;color:#B45309;font-size:14px;">Следующие поля содержат несовместимые данные из разных файлов:</p>
            <ul style="margin:8px 0 0;padding-left:20px;color:#92400E;font-size:13.5px;">${conflictItems.join('')}</ul>
        </div>`;
    }

    container.innerHTML = conflictBannerHtml + `
        <div class="result-section"><h3>Обзор проекта</h3><p>${doc.project_overview || 'Нет данных'}</p></div>
        <div class="result-section"><h3>Цели</h3>${makeFactList(doc.goals)}</div>
        <div class="result-section"><h3>Требования</h3>${makeFactList(doc.requirements)}</div>
        <div class="result-section"><h3>Техническое решение</h3><p>${makeFact(doc.technical_solution)}</p></div>
        <div class="result-section"><h3>Архитектура</h3><p>${makeFact(doc.architecture)}</p></div>
        <div class="result-section"><h3>Команда</h3>${makeFactList(doc.team)}</div>
        <div class="result-section">
            <h3>Сроки и Бюджет</h3>
            <p><strong>Время:</strong> ${makeFact(doc.timeline)}</p>
            <p><strong>Бюджет:</strong> ${makeFact(doc.budget)}</p>
        </div>
        <div class="result-section"><h3>Риски</h3>${makeFactList(doc.risks)}</div>
    `;

    document.getElementById('meta-content').innerHTML = `
        <strong>Метаданные архитектуры Map-Reduce:</strong><br>
        Опрошено файлов (Map): ${(meta.llm_calls || 1) - 1} шт.<br>
        Финальная сборка (Reduce): 1 вызов<br>
        Конфликтов обнаружено: <strong>${conflictsCount}</strong><br>
        Токенов обработано: ${meta.total_tokens || 0} &nbsp;|&nbsp; Время полного цикла: ${meta.duration_ms || 0} мс
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

# ── Generate endpoint (unchanged) ─────────────────────────────────────────────
@app.post("/generate_document")
async def generate_document(files: List[UploadFile] = File(...)):
    files_data = []
    for file in files:
        content = await file.read()
        text = content.decode('utf-8', errors='ignore')
        files_data.append({"filename": file.filename, "content": text})
    try:
        result = current_llm.generate_document(files_data)
        return result
    except Exception as e:
        error_msg = str(e)
        if "Connection error" in error_msg or "ConnectError" in error_msg:
            detail_msg = f"Не удалось подключиться к локальному серверу LM Studio по адресу {LOCAL_PC_IP}."
        else:
            detail_msg = f"Ошибка обработки: {error_msg}"
        raise HTTPException(status_code=500, detail=detail_msg)
