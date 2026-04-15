import time
import json
from typing import List
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse
from openai import OpenAI

class LLMProvider:
    # Теперь мы передаем не сплошной текст, а список файлов
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

        # ==========================================
        # ЭТАП 1: MAP (Бездумное извлечение фактов)
        # ==========================================
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
                temperature=0.0 # СТРОГО 0.0 - никакого креатива
            )
            fact_summary = response.choices[0].message.content
            total_tokens_used += response.usage.total_tokens if response.usage else 0
            
            all_extracted_facts += f"\n\n--- ФАЙЛ: {f['filename']} ---\n{fact_summary}\n"

        # ==========================================
        # ЭТАП 2: REDUCE (Жесткая сборка JSON)
        # ==========================================
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
           в) ЗАПРЕЩЕНО оставлять "conflict_details" пустой строкой, если "has_conflict" равно true. Пустая строка при has_conflict=true — это ошибка.
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
            temperature=0.0 # СТРОГО 0.0
        )
        total_tokens_used += final_response.usage.total_tokens if final_response.usage else 0
        end_time = time.time()

        raw_content = final_response.choices[0].message.content
        
        # Парсер JSON
        start_idx = raw_content.find('{')
        end_idx = raw_content.rfind('}')
        
        if start_idx != -1 and end_idx != -1:
            clean_json = raw_content[start_idx:end_idx+1]
        else:
            clean_json = raw_content
            
        try:
            parsed_data = json.loads(clean_json)
        except Exception as e:
            parsed_data = {"error": "Llama 3 вернула невалидный JSON", "raw_output": raw_content}

        duration_ms = int((end_time - start_time) * 1000)

        def count_conflicts(doc: dict) -> int:
            count = 0
            if not isinstance(doc, dict):
                return 0
            for value in doc.values():
                if isinstance(value, dict) and value.get("has_conflict"):
                    count += 1
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, dict) and item.get("has_conflict"):
                            count += 1
            return count

        conflicts_found = count_conflicts(parsed_data)

        return {
            "document": parsed_data,
            "metadata": {
                "model_name": f"Local GPU Map-Reduce ({self.model_name})",
                "llm_calls": len(files_data) + 1,
                "total_tokens": total_tokens_used,
                "duration_ms": duration_ms,
                "conflicts_found": conflicts_found
            },
            "trace": {
                "steps": [
                    "Парсинг файлов", 
                    f"Map: Извлечение фактов (обработано файлов: {len(files_data)})",
                    "Reduce: Сборка JSON"
                ]
            }
        }

# --- НАСТРОЙКА СЕРВЕРА ---
app = FastAPI()

# Твой локальный IP
LOCAL_PC_IP = "127.0.0.1" 
current_llm = LocalProvider(base_url=f"http://{LOCAL_PC_IP}:1234/v1")

# --- ИНТЕРФЕЙС (Остался без изменений, только чуть поправил текст) ---
@app.get("/")
async def main_page():
    html_content = """
    <!DOCTYPE html>
    <html lang="ru">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Генератор проектной документации</title>
        <style>
            :root { --primary: #4F46E5; --primary-hover: #4338CA; --bg: #F3F4F6; --card-bg: #FFFFFF; --text-main: #1F2937; --text-muted: #6B7280; --border: #E5E7EB; --source-bg: #DBEAFE; --source-text: #1E40AF; }
            body { font-family: 'Segoe UI', system-ui, -apple-system, sans-serif; background-color: var(--bg); color: var(--text-main); padding: 40px 20px; margin: 0; line-height: 1.5; }
            .container { max-width: 800px; margin: 0 auto; background: var(--card-bg); padding: 40px; border-radius: 12px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1); }
            h1, h2, h3 { color: var(--text-main); } h1 { text-align: center; margin-top: 0; } p { color: var(--text-muted); }
            .upload-zone { border: 2px dashed var(--border); padding: 40px; text-align: center; border-radius: 8px; margin-bottom: 20px; transition: border-color 0.3s; }
            .upload-zone:hover { border-color: var(--primary); } input[type="file"] { margin-bottom: 15px; }
            button { background-color: var(--primary); color: white; padding: 12px 24px; border: none; border-radius: 6px; font-size: 16px; font-weight: 600; cursor: pointer; width: 100%; transition: background-color 0.2s; }
            button:hover { background-color: var(--primary-hover); }
            #loading-screen { display: none; text-align: center; padding: 40px 0; }
            .spinner { width: 50px; height: 50px; border: 5px solid var(--border); border-top: 5px solid var(--primary); border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 20px auto; }
            @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
            #result-screen { display: none; }
            .result-section { margin-bottom: 24px; padding-bottom: 16px; border-bottom: 1px solid var(--border); }
            .result-section h3 { color: var(--primary); margin-bottom: 8px; font-size: 18px; }
            ul { margin-top: 0; padding-left: 20px; } li { margin-bottom: 10px; color: var(--text-main); }
            .source-badge { display: inline-block; background-color: var(--source-bg); color: var(--source-text); font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 12px; margin-left: 8px; vertical-align: middle; }
            .meta-data { background: var(--bg); padding: 15px; border-radius: 6px; font-size: 14px; margin-top: 20px; border-left: 4px solid var(--primary); }
            #download-btn { background-color: #10B981; margin-top: 20px; } #download-btn:hover { background-color: #059669; }
        </style>
    </head>
    <body>
    <div class="container">
        <h1>Генератор документации <span style="font-size: 14px; background: #FEF3C7; color: #D97706; padding: 4px 8px; border-radius: 8px; vertical-align: top;">Map-Reduce</span></h1>
        
        <div id="upload-screen">
            <p style="text-align: center;">Система анализирует каждый файл <strong>изолированно</strong>, защищая от переполнения памяти, а затем объединяет факты.</p>
            <form id="upload-form">
                <div class="upload-zone">
                    <input type="file" id="file-input" name="files" multiple required accept=".txt,.md,.json,.py,.java">
                </div>
                <button type="submit" id="submit-btn">Анализировать (Map-Reduce)</button>
            </form>
        </div>

        <div id="loading-screen">
            <div class="spinner"></div>
            <h3>Архитектура Map-Reduce в работе...</h3>
            <p>Шаг 1: Индивидуальный анализ файлов<br>Шаг 2: Синтез и поиск противоречий<br><em>Это может занять 10-30 секунд.</em></p>
        </div>

        <div id="result-screen">
            <h2>Результат генерации:</h2>
            <div id="parsed-content"></div>
            <div class="meta-data" id="meta-content"></div>
            <button id="download-btn">📥 Скачать JSON</button>
            <button id="reset-btn" style="background-color: var(--text-muted); margin-top: 10px;">Начать заново</button>
        </div>
    </div>

    <script>
        const form = document.getElementById('upload-form');
        let currentRawData = null;

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            document.getElementById('upload-screen').style.display = 'none';
            document.getElementById('loading-screen').style.display = 'block';

            const formData = new FormData();
            const files = document.getElementById('file-input').files;
            for (let i = 0; i < files.length; i++) formData.append('files', files[i]);

            try {
                const response = await fetch('/generate_document', { method: 'POST', body: formData });
                if (!response.ok) {
                    const errData = await response.json();
                    throw new Error(errData.detail || 'Неизвестная ошибка сервера');
                }
                const data = await response.json();
                currentRawData = data;
                renderResults(data);
                document.getElementById('loading-screen').style.display = 'none';
                document.getElementById('result-screen').style.display = 'block';
            } catch (error) {
                alert('Ошибка: ' + error.message);
                document.getElementById('loading-screen').style.display = 'none';
                document.getElementById('upload-screen').style.display = 'block';
            }
        });

        function renderResults(data) {
            const doc = data.document;
            const meta = data.metadata;
            const container = document.getElementById('parsed-content');

            const makeFact = (fact) => {
                if (!fact || !fact.text) return 'Нет данных';
                const badgeColor = (fact.source === "Нет источника" || fact.source.includes("отсутству")) ? "background: #F3F4F6; color: #6B7280;" : "";
                let html = `<span>${fact.text}</span> <span class="source-badge" style="${badgeColor}">📄 ${fact.source}</span>`;

                if (fact.has_conflict) {
                    html += `
                    <div style="margin-top: 8px; margin-bottom: 8px; background-color: #FEF3C7; border-left: 4px solid #F59E0B; padding: 10px 14px; font-size: 13.5px; color: #92400E; border-radius: 0 4px 4px 0;">
                        <strong style="display: block; margin-bottom: 4px; color: #B45309;">⚠️ Обнаружен конфликт:</strong>
                        ${fact.conflict_details}
                    </div>`;
                }
                return html;
            };

            const makeFactList = (items) => {
                if (!items || items.length === 0) return '<p>Нет данных</p>';
                return `<ul>${items.map(item => `<li>${makeFact(item)}</li>`).join('')}</ul>`;
            };

            // --- CONFLICT SUMMARY BANNER ---
            const conflictsCount = meta.conflicts_found || 0;
            let conflictBannerHtml = '';

            if (conflictsCount > 0) {
                const conflictItems = [];
                const singleFields = ['timeline', 'budget', 'technical_solution', 'architecture'];
                const listFields   = ['goals', 'requirements', 'team', 'risks'];
                const labels = {
                    timeline: 'Сроки', budget: 'Бюджет',
                    technical_solution: 'Техническое решение', architecture: 'Архитектура',
                    goals: 'Цели', requirements: 'Требования', team: 'Команда', risks: 'Риски'
                };

                singleFields.forEach(key => {
                    const f = doc[key];
                    if (f && f.has_conflict && f.conflict_details)
                        conflictItems.push(`<li><strong>${labels[key]}:</strong> ${f.conflict_details}</li>`);
                });
                listFields.forEach(key => {
                    (doc[key] || []).forEach((f, i) => {
                        if (f && f.has_conflict && f.conflict_details)
                            conflictItems.push(`<li><strong>${labels[key]} [${i+1}]:</strong> ${f.conflict_details}</li>`);
                    });
                });

                conflictBannerHtml = `
                <div style="background-color:#FEF3C7;border:2px solid #F59E0B;border-radius:8px;padding:16px 20px;margin-bottom:24px;">
                    <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
                        <span style="font-size:22px;">⚠️</span>
                        <strong style="font-size:16px;color:#92400E;">Обнаружено противоречий: ${conflictsCount}</strong>
                    </div>
                    <p style="margin:4px 0 0;color:#B45309;font-size:14px;">Следующие поля содержат несовместимые данные из разных файлов:</p>
                    <ul style="margin:8px 0 0;padding-left:20px;color:#92400E;font-size:13.5px;">
                        ${conflictItems.join('')}
                    </ul>
                </div>`;
            }
            // --- END BANNER ---

            container.innerHTML = conflictBannerHtml + `
                <div class="result-section"><h3>Обзор проекта</h3><p>${doc.project_overview}</p></div>
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
                Опрошено файлов (Map): ${meta.llm_calls - 1} шт.<br>
                Финальная сборка (Reduce): 1 вызов<br>
                Конфликтов обнаружено: <strong>${conflictsCount}</strong><br>
                Токенов обработано: ${meta.total_tokens} | Время полного цикла: ${meta.duration_ms} мс
            `;
        }
        document.getElementById('download-btn').addEventListener('click', () => {
            const blob = new Blob([JSON.stringify(currentRawData, null, 4)], { type: "application/json" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a'); a.href = url; a.download = "map_reduce_doc.json";
            a.click(); URL.revokeObjectURL(url);
        });
        document.getElementById('reset-btn').addEventListener('click', () => {
            document.getElementById('file-input').value = '';
            document.getElementById('result-screen').style.display = 'none';
            document.getElementById('upload-screen').style.display = 'block';
        });
    </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# ОБНОВЛЕННЫЙ ЭНДПОИНТ: Теперь мы не склеиваем текст, а передаем список файлов
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