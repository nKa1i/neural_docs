"""
setup_v2.py
Creates 10 company project folders (each with .txt/.md/.json/.py/.java files)
then generates 100 fine-tuning JSON samples in the map-reduce document format.
"""
import json, os, random

BASE        = os.path.dirname(os.path.abspath(__file__))
CO_DIR      = os.path.join(BASE, "company_projects")
FT_DIR      = os.path.join(BASE, "finetune_v2")
os.makedirs(CO_DIR, exist_ok=True)
os.makedirs(FT_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────────────────────────────────────
def item(text, source, conflict=False, details=""):
    return {"text": text, "source": source, "has_conflict": conflict, "conflict_details": details}

def field(text, source, conflict=False, details=""):
    return {"text": text, "source": source, "has_conflict": conflict, "conflict_details": details}

def meta(calls, tokens, ms, conflicts):
    return {
        "model_name": "Local GPU Map-Reduce (meta-llama-3-8b-instruct)",
        "llm_calls": calls,
        "total_tokens": tokens,
        "duration_ms": ms,
        "conflicts_found": conflicts,
    }

def trace(n_files, extra_steps=None):
    steps = [
        "Парсинг файлов",
        f"Map: Извлечение фактов (обработано файлов: {n_files})",
        "Reduce: Сборка JSON",
    ]
    if extra_steps:
        steps += extra_steps
    return {"steps": steps}

def sample(doc, n_files, calls, tokens, ms):
    conflicts = 0
    for k in ["timeline", "budget", "technical_solution", "architecture"]:
        v = doc.get(k)
        if isinstance(v, dict) and v.get("has_conflict"):
            conflicts += 1
    for k in ["goals", "requirements", "team", "risks"]:
        for it in doc.get(k, []):
            if it.get("has_conflict"):
                conflicts += 1
    return {
        "document": doc,
        "metadata": meta(calls, tokens, ms, conflicts),
        "trace": trace(n_files),
    }

# ─────────────────────────────────────────────────────────────────────────────
# COMPANY FILES (10 companies)
# ─────────────────────────────────────────────────────────────────────────────
FILES = {}

# ── 01 NeonPhantom Studio ────────────────────────────────────────────────────
FILES["01_neon_phantom"] = {
"concept_notes.txt": """\
1. Общая концепция
   NeonPhantom — action-игра в жанре техно-магия, киберпанк и тёмное фэнтези.
2. Платформа
   PC (Steam), возможный порт на консоли.
3. Ключевые механики
   Вселение в врагов, захват их способностей, стелс-режим.
4. Боевая система
   Хардкорная боёвка: смерть с одного удара в режиме «Кошмар».
5. Команда
   Я (кодер/геймдизайнер), 3D-художник на аутсорс.
6. Сроки
   Релиз через 8 месяцев от старта.
7. Монетизация
   Единоразовая покупка, без DLC на старте.
8. Риски и альтернативный срок
   При задержке с 3D-ассетами — перенос на 12 месяцев.
""",
"budget_draft.txt": """\
1. Источник финансирования
   Личные накопления разработчика.
2. Статьи расходов
   — 3D-аутсорс: 300 000 тенге
   — Движок (лицензия): 50 000 тенге
   — Маркетинг: 150 000 тенге
3. Архитектура: синглплеер, без серверной части.
4. Итог по черновику А
   Общий бюджет: 500 000 тенге.
5. Итог по пересмотру (февраль)
   После уточнения у художника — 700 000 тенге.
""",
"mechanics.md": """\
# Механики NeonPhantom

## 1. Передвижение
Магические нити для притягивания к объектам (аналог grappling hook).

## 2. Боевой баланс
Враги наносят высокий урон — игрок должен использовать уклонение.

## 3. Вселение
Нажать [E] рядом с ослабленным врагом. Лимит: 3 вселения подряд.

## 4. Прогрессия
Дерево навыков с 5 ветками. Очки навыков — за боссов.

## 5. Бюджет на механики (из таблицы расходов)
Разработка механик: 200 000 тенге — конфликт с budget_draft.txt [4].
""",
"config.json": """\
{
  "project": "NeonPhantom",
  "engine": "Godot 4.2",
  "language": "GDScript + C#",
  "platform": ["PC", "Steam"],
  "architecture": "singleplayer",
  "target_fps": 60,
  "build_tool": "GitHub Actions"
}
""",
"main_game.py": """\
# NeonPhantom — core loop (prototype)
class GameManager:
    VERSION = \"0.3-alpha\"
    MAX_POSSESSIONS = 3

    def start_level(self, level_id: int):
        print(f\"Loading level {level_id}\")

    def possess_enemy(self, enemy_id: int, possession_count: int) -> bool:
        if possession_count >= self.MAX_POSSESSIONS:
            return False
        return True
""",
"EntitySystem.java": """\
package io.neonphantom.engine;
public class EntitySystem {
    private static final int MAX_ENTITIES = 512;
    private static final float ENEMY_BASE_DAMAGE = 45.0f; // hardcoded high damage
    public void spawnEnemy(String type, float x, float y) {
        System.out.println(\"Spawning \" + type + \" at (\" + x + \",\" + y + \")\");
    }
}
""",
}

# ── 02 ArcadeForge Games ─────────────────────────────────────────────────────
FILES["02_arcadeforge"] = {
"concept_notes.txt": """\
1. Концепция
   ArcadeForge — мобильная аркадная гонка с процедурными трассами.
2. Платформы
   iOS и Android (кроссплатформа через Unity).
3. Цели
   Войти в топ-100 App Store в категории Racing за первые 3 месяца.
4. Монетизация
   Free-to-play: косметика, сезонный пропуск.
5. Команда
   2 программиста, 1 UI-дизайнер, 1 звукорежиссёр.
6. Срок
   MVP через 6 месяцев, полный релиз через 10 месяцев.
""",
"budget_draft.txt": """\
1. Бюджет утверждён на сумму 2 000 000 тенге.
2. Unity лицензия: 120 000 тенге/год.
3. Маркетинг (UA): 800 000 тенге.
4. Пересмотренный бюджет после переговоров с UA-агентством: 2 500 000 тенге.
5. Срок по дорожной карте: MVP через 5 месяцев (конфликт с concept_notes [6]).
""",
"requirements.md": """\
# Требования ArcadeForge

## Функциональные
- Процедурная генерация трасс (алгоритм Wave Function Collapse)
- Мультиплеер: до 4 игроков онлайн
- Офлайн-режим с сохранением прогресса

## Нефункциональные
- Загрузка уровня < 2 секунды на iPhone 12
- 60 FPS на Android mid-range (Snapdragon 720G)

## Риски
- Процедурная генерация может давать непроходимые трассы
- Unity multiplayer SDK — платный при > 200 DAU
""",
"config.json": """\
{
  "project": "ArcadeForge",
  "engine": "Unity 2023 LTS",
  "language": "C#",
  "platforms": ["iOS", "Android"],
  "architecture": "client-server",
  "server_provider": "Photon",
  "min_ios": "14.0",
  "min_android_api": 26
}
""",
"RaceEngine.java": """\
package com.arcadeforge.engine;
public class RaceEngine {
    public static final int MAX_PLAYERS = 4;
    public static final int TRACK_SEED_RANGE = 999999;
    public void generateTrack(int seed) {
        System.out.println(\"Generating track with seed: \" + seed);
    }
    public boolean validateTrack(int[][] grid) {
        // TODO: pathfinding validation — risk of unpassable tracks
        return true;
    }
}
""",
"track_generator.py": """\
import random
class TrackGenerator:
    TILE_TYPES = [\"straight\", \"curve_l\", \"curve_r\", \"jump\", \"obstacle\"]
    def generate(self, seed: int, length: int = 50):
        random.seed(seed)
        return [random.choice(self.TILE_TYPES) for _ in range(length)]
""",
}

# ── 03 DataVault Analytics ───────────────────────────────────────────────────
FILES["03_datavault"] = {
"concept_notes.txt": """\
1. Продукт
   DataVault — SaaS-платформа для B2B аналитики данных в реальном времени.
2. Целевая аудитория
   Средний и крупный бизнес (50–5000 сотрудников).
3. Цели продукта
   Заменить Excel-отчёты дашбордами с авто-обновлением каждые 5 минут.
4. Команда
   CTO, 3 бэкенд-разработчика, 1 фронтенд, 1 DevOps, 1 аналитик данных.
5. Срок выхода на рынок
   Публичная бета через 9 месяцев.
6. Цена
   Базовый план: $99/месяц, Про: $299/месяц.
""",
"budget_draft.txt": """\
1. Инвестиционный раунд: $150 000 (ангельский).
2. Инфраструктура AWS: $3 000/месяц.
3. Команда (6 чел): $80 000/месяц суммарно.
4. Срок до исчерпания runway: 18 месяцев.
5. Пересмотр цены: Базовый план $149/месяц по результатам custdev.
   Конфликт с concept_notes.txt [6] — там $99/месяц.
6. Итоговый бюджет фазы 1: $150 000.
""",
"architecture.md": """\
# Архитектура DataVault

## Backend
- Python (FastAPI) + Apache Kafka для стриминга
- PostgreSQL (OLTP) + ClickHouse (OLAP)
- Деплой: AWS EKS (Kubernetes)

## Frontend
- React 18 + TypeScript
- Recharts для дашбордов

## Безопасность
- SOC 2 Type II compliance (цель)
- Шифрование AES-256 at rest

## Риски
- ClickHouse — сложная операционная поддержка
- Kafka при < 1000 RPS избыточна, рассмотреть Redis Streams
""",
"config.json": """\
{
  "project": "DataVault",
  "version": "0.1.0",
  "backend": "FastAPI",
  "db_oltp": "PostgreSQL 15",
  "db_olap": "ClickHouse 23.8",
  "streaming": "Apache Kafka",
  "cloud": "AWS",
  "region": "eu-central-1",
  "pricing_basic_usd": 149
}
""",
"ingestion_service.py": """\
from kafka import KafkaConsumer
import clickhouse_driver

class IngestionService:
    BATCH_SIZE = 1000
    FLUSH_INTERVAL_SEC = 5

    def __init__(self, kafka_topic: str, ch_table: str):
        self.topic = kafka_topic
        self.table = ch_table

    def run(self):
        consumer = KafkaConsumer(self.topic)
        batch = []
        for msg in consumer:
            batch.append(msg.value)
            if len(batch) >= self.BATCH_SIZE:
                self._flush(batch)
                batch = []

    def _flush(self, batch):
        # write to ClickHouse
        pass
""",
"DashboardController.java": """\
package io.datavault.api;
import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping(\"/api/v1/dashboards\")
public class DashboardController {
    private static final int REFRESH_INTERVAL_MINUTES = 5;
    @GetMapping(\"/{id}\")
    public String getDashboard(@PathVariable String id) {
        return \"{\\\"id\\\":\\\"\" + id + \"\\\"}\";
    }
}
""",
}

# ── 04 SwiftPay ──────────────────────────────────────────────────────────────
FILES["04_swiftpay"] = {
"concept_notes.txt": """\
1. Продукт
   SwiftPay — мобильное приложение для мгновенных P2P-переводов.
2. Рынок
   Казахстан, Кыргызстан, Узбекистан (первый этап).
3. Цели
   Обработка 10 000 транзакций/сутки к концу первого года.
4. Команда
   2 iOS-разработчика, 2 Android, 1 бэкенд, 1 QA, 1 продакт.
5. Срок
   Запуск в App Store и Google Play — Q2 2026.
6. Лицензия
   Получение лицензии платёжной системы от НБ РК — 4 месяца.
7. Риски
   Задержка лицензии сдвигает релиз на Q3 2026.
""",
"budget_draft.txt": """\
1. Бюджет раунда Pre-Seed: 30 000 000 тенге.
2. Разработка (7 чел × 6 мес): 18 000 000 тенге.
3. Инфраструктура (облако + HSM): 4 000 000 тенге.
4. Юридические расходы (лицензия): 3 000 000 тенге.
5. Маркетинг: 5 000 000 тенге.
6. ИТОГО: 30 000 000 тенге.
7. Пересмотренный бюджет (после аудита безопасности): 35 000 000 тенге.
   Конфликт: concept_notes [бюджет не упомянут] vs budget_draft [1] — 30M vs 35M.
""",
"security_requirements.md": """\
# Требования безопасности SwiftPay

## Стандарты
- PCI DSS Level 1 (цель для > 6M транзакций/год)
- PCI DSS Level 2 на старте (до 6M транзакций)

## Шифрование
- TLS 1.3 в транзите
- AES-256 at rest
- HSM для ключей

## Аутентификация
- Биометрия (Face ID / Fingerprint)
- PIN как фолбэк
- 2FA для переводов > 50 000 тенге

## Риски
- HSM — высокая стоимость (1 500 000 тенге единоразово)
- PCI DSS аудит занимает 3–6 месяцев
""",
"config.json": """\
{
  "project": "SwiftPay",
  "version": "1.0.0-rc",
  "backend_lang": "Go",
  "db": "PostgreSQL 15",
  "cache": "Redis 7",
  "cloud": "Yandex Cloud",
  "regions": ["kz-north-1"],
  "pci_dss_level": 2,
  "max_tx_per_day": 10000
}
""",
"payment_processor.py": """\
import hashlib, hmac
class PaymentProcessor:
    MAX_AMOUNT_KZT = 5_000_000
    DAILY_LIMIT_KZT = 1_000_000

    def validate_transfer(self, amount: float, sender_id: str) -> bool:
        if amount > self.MAX_AMOUNT_KZT:
            return False
        return True

    def sign_payload(self, payload: bytes, secret: bytes) -> str:
        return hmac.new(secret, payload, hashlib.sha256).hexdigest()
""",
"TransactionService.java": """\
package kz.swiftpay.service;
import java.math.BigDecimal;
public class TransactionService {
    private static final BigDecimal MAX_TX = new BigDecimal(\"5000000\");
    private static final int TIMEOUT_MS = 3000;
    public boolean processTransfer(String from, String to, BigDecimal amount) {
        if (amount.compareTo(MAX_TX) > 0) return false;
        System.out.println(\"Transfer \" + from + \" -> \" + to + \" : \" + amount);
        return true;
    }
}
""",
}

# ── 05 MindMap AI ────────────────────────────────────────────────────────────
FILES["05_mindmap_ai"] = {
"concept_notes.txt": """\
1. Продукт
   MindMap AI — ИИ-ассистент для структурирования заметок и идей.
2. Ключевая фича
   Авто-генерация интеллект-карт из неструктурированного текста.
3. Цели
   1 000 платных пользователей за первые 6 месяцев после релиза.
4. Команда
   1 ML-инженер, 1 фулстек-разработчик, 1 дизайнер (парт-тайм).
5. Срок
   Приватная бета через 4 месяца.
6. Цена подписки
   $9.99/месяц (индивидуальный план).
7. ИИ-модель
   Локальная LLM (Mistral 7B) для приватности данных.
""",
"budget_draft.txt": """\
1. Бутстрап-финансирование: $20 000 личных средств.
2. GPU-сервер (аренда): $800/месяц.
3. Инфраструктура (Vercel + Supabase): $200/месяц.
4. Цена подписки пересмотрена: $14.99/месяц (конфликт с concept_notes [6]).
5. Расходы на 12 месяцев: $18 000.
6. Резерв: $2 000.
""",
"ml_requirements.md": """\
# ML-требования MindMap AI

## Модель
- Mistral 7B Instruct (локально) — concept_notes [7]
- Альтернатива: GPT-4o API (конфликт: concept_notes говорит о локальной модели)

## Производительность
- Генерация карты из 500 слов: < 3 секунды
- Поддержка оффлайн-режима (только локальная модель)

## Форматы вывода
- JSON (для рендера карты)
- Markdown (для экспорта)

## Риски
- Mistral 7B требует GPU VRAM ≥ 8GB на устройстве пользователя
- GPT-4o API: стоимость растёт линейно с числом пользователей
""",
"config.json": """\
{
  "project": "MindMapAI",
  "model_primary": "gpt-4o-api",
  "model_fallback": "mistral-7b-local",
  "subscription_price_usd": 14.99,
  "max_nodes_per_map": 200,
  "export_formats": ["json", "markdown", "png"],
  "backend": "FastAPI",
  "frontend": "Next.js 14"
}
""",
"mind_mapper.py": """\
from openai import OpenAI
class MindMapper:
    MODEL = \"gpt-4o\"  # conflicts with concept_notes [7] which says Mistral 7B local
    MAX_TOKENS = 2048

    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    def generate_map(self, text: str) -> dict:
        resp = self.client.chat.completions.create(
            model=self.MODEL,
            messages=[{\"role\": \"user\", \"content\": f\"Build a mind map JSON from: {text}\"}],
            max_tokens=self.MAX_TOKENS,
        )
        return {\"raw\": resp.choices[0].message.content}
""",
"NodeRenderer.java": """\
package ai.mindmap.render;
import java.util.List;
import java.util.Map;
public class NodeRenderer {
    public static final int MAX_DEPTH = 5;
    public String renderToMarkdown(Map<String, Object> node, int depth) {
        String indent = \"  \".repeat(depth);
        return indent + \"- \" + node.get(\"label\");
    }
}
""",
}

# ── 06 EcoTrack ──────────────────────────────────────────────────────────────
FILES["06_ecotrack"] = {
"concept_notes.txt": """\
1. Продукт
   EcoTrack — IoT-платформа для мониторинга качества воздуха и воды.
2. Клиенты
   Муниципалитеты и промышленные предприятия.
3. Цели
   Разместить 500 датчиков в Алматы к концу года.
4. Протокол датчиков
   MQTT 3.1.1 через LTE-M / NB-IoT.
5. Команда
   1 IoT-инженер, 1 бэкенд, 1 embedded-разработчик, 1 продажник.
6. Срок
   Пилот (50 датчиков) через 3 месяца.
7. Хранение данных
   90 дней в горячем хранилище, архив 5 лет.
""",
"budget_draft.txt": """\
1. Грантовое финансирование (МЦРИАП): 15 000 000 тенге.
2. Стоимость 1 датчика: 25 000 тенге. Для 500 — 12 500 000 тенге.
3. Облако и DevOps: 1 500 000 тенге/год.
4. Хранение данных (пересмотр): 30 дней горячее, 1 год архив.
   Конфликт с concept_notes [7] — там 90 дней и 5 лет.
5. Итого бюджет: 15 000 000 тенге.
""",
"iot_architecture.md": """\
# Архитектура EcoTrack

## Протокол
MQTT 3.1.1 — concept_notes [4]
CoAP рассматривается для датчиков с батарейным питанием (альтернатива, конфликт).

## Брокер
Eclipse Mosquitto → AWS IoT Core (для масштаба)

## Обработка
- AWS Lambda для триггеров по порогам
- TimescaleDB для временных рядов

## Дашборд
- Grafana (self-hosted)

## Риски
- NB-IoT покрытие в районах вне Алматы — < 60%
- Батарея датчика: 6 месяцев при MQTT heartbeat 1 мин
""",
"config.json": """\
{
  "project": "EcoTrack",
  "protocol": "CoAP",
  "broker": "AWS IoT Core",
  "db": "TimescaleDB",
  "retention_hot_days": 30,
  "retention_archive_years": 1,
  "sensors_target": 500,
  "pilot_sensors": 50
}
""",
"sensor_collector.py": """\
import paho.mqtt.client as mqtt
class SensorCollector:
    TOPIC_PREFIX = \"ecotrack/sensors/\"
    QOS = 1
    def __init__(self, broker_host: str, port: int = 1883):
        self.client = mqtt.Client()
        self.broker = broker_host
        self.port = port
    def on_message(self, client, userdata, msg):
        print(f\"Data from {msg.topic}: {msg.payload.decode()}\")
    def start(self):
        self.client.on_message = self.on_message
        self.client.connect(self.broker, self.port)
        self.client.subscribe(f\"{self.TOPIC_PREFIX}#\", self.QOS)
        self.client.loop_forever()
""",
"SensorGateway.java": """\
package kz.ecotrack.gateway;
public class SensorGateway {
    private static final String PROTOCOL = \"MQTT\"; // code uses MQTT, config says CoAP
    private static final int HEARTBEAT_INTERVAL_SEC = 60;
    public void registerSensor(String sensorId, double lat, double lon) {
        System.out.println(\"Registered: \" + sensorId + \" at \" + lat + \",\" + lon);
    }
}
""",
}

# ── 07 HealthSync ────────────────────────────────────────────────────────────
FILES["07_healthsync"] = {
"concept_notes.txt": """\
1. Продукт
   HealthSync — платформа обмена медицинскими данными между клиниками.
2. Стандарт
   HL7 FHIR R4 для интероперабельности.
3. Цели
   Подключить 20 клиник Алматы к единому реестру за 12 месяцев.
4. Команда
   1 архитектор, 2 бэкенд, 1 фронтенд, 1 медицинский консультант, 1 QA.
5. Срок
   MVP (5 клиник) через 6 месяцев.
6. Бюджет
   Государственный контракт: 80 000 000 тенге.
7. Резервное копирование
   Ежечасное, RPO = 1 час.
""",
"budget_draft.txt": """\
1. Контракт Министерства здравоохранения: 80 000 000 тенге.
2. Инфраструктура (защищённое облако Казахстан): 8 000 000 тенге/год.
3. Разработка и интеграция: 50 000 000 тенге.
4. Обучение персонала клиник: 5 000 000 тенге.
5. Резерв 10%: 8 000 000 тенге.
6. ИТОГО: 71 000 000 тенге. Экономия 9M на маркетинге.
7. Резервное копирование: ежедневное (конфликт с concept_notes [7] — ежечасное).
""",
"fhir_spec.md": """\
# FHIR R4 Требования HealthSync

## Ресурсы
- Patient, Observation, DiagnosticReport, MedicationRequest

## API
- RESTful FHIR API
- OAuth 2.0 + SMART on FHIR

## Безопасность
- Шифрование AES-256
- Аудит-лог всех обращений к данным пациентов

## Соответствие
- Закон РК «О персональных данных»
- Приказ МЗ РК №907

## Риски
- Интеграция с 1С:Медицина (legacy) — нестандартный API
- Разные версии HL7 у старых клиник (v2.x vs FHIR R4)
""",
"config.json": """\
{
  "project": "HealthSync",
  "fhir_version": "R4",
  "auth": "OAuth2 + SMART on FHIR",
  "db": "PostgreSQL 15",
  "backup_frequency": "daily",
  "rpo_hours": 24,
  "cloud": "KazCloud (certified)",
  "encryption": "AES-256"
}
""",
"fhir_client.py": """\
import requests
class FHIRClient:
    FHIR_VERSION = \"R4\"
    def __init__(self, base_url: str, token: str):
        self.base_url = base_url
        self.headers = {\"Authorization\": f\"Bearer {token}\",
                        \"Content-Type\": \"application/fhir+json\"}
    def get_patient(self, patient_id: str) -> dict:
        r = requests.get(f\"{self.base_url}/Patient/{patient_id}\", headers=self.headers)
        r.raise_for_status()
        return r.json()
""",
"PatientRepository.java": """\
package kz.healthsync.repository;
import java.util.Optional;
public class PatientRepository {
    // RPO set to 1h in concept_notes but config says daily backup
    private static final int BACKUP_INTERVAL_HOURS = 24; // conflict
    public Optional<String> findById(String patientId) {
        System.out.println(\"Querying patient: \" + patientId);
        return Optional.empty();
    }
}
""",
}

# ── 08 LogiFlow ──────────────────────────────────────────────────────────────
FILES["08_logiflow"] = {
"concept_notes.txt": """\
1. Продукт
   LogiFlow — SaaS для управления цепочками поставок малого бизнеса.
2. Целевая аудитория
   Интернет-магазины и дистрибьюторы в СНГ.
3. Цели
   Автоматизировать 80% рутинных задач (заказы, склад, доставка).
4. Интеграции
   Kaspi.kz, 1С, Wildberries, Ozon через REST API.
5. Команда
   1 PM, 2 бэкенд, 1 фронтенд, 1 QA.
6. Срок
   Коммерческий релиз через 7 месяцев.
7. Пропускная способность
   До 50 000 заказов/сутки.
""",
"budget_draft.txt": """\
1. Финансирование: венчурный раунд $200 000.
2. Разработка (5 чел × 8 мес): $120 000.
3. Инфраструктура (GCP): $5 000/месяц × 8 = $40 000.
4. Пересмотр: срок увеличен до 9 месяцев (конфликт с concept_notes [6]).
5. Пропускная способность (revised): 10 000 заказов/сутки на старте.
   Конфликт с concept_notes [7] — там 50 000.
6. ИТОГО: $200 000.
""",
"api_design.md": """\
# API LogiFlow

## Стиль
REST + JSON (v1). GraphQL рассматривается для v2.

## Ключевые эндпоинты
- POST /orders — создание заказа
- GET /orders/{id} — статус заказа
- POST /shipments — создание отправления
- GET /warehouse/stock — остатки

## Интеграции
- Webhook для Kaspi.kz и Wildberries
- OAuth 2.0 для 1С-коннектора

## Риски
- Kaspi API нестабилен: задержки до 10 сек
- Wildberries меняет API без предупреждения
""",
"config.json": """\
{
  "project": "LogiFlow",
  "api_version": "v1",
  "api_style": "REST",
  "db": "PostgreSQL 15",
  "queue": "RabbitMQ",
  "cloud": "GCP",
  "max_orders_per_day": 10000,
  "release_months": 9
}
""",
"order_service.py": """\
from dataclasses import dataclass
from enum import Enum

class OrderStatus(Enum):
    PENDING = \"pending\"
    PROCESSING = \"processing\"
    SHIPPED = \"shipped\"
    DELIVERED = \"delivered\"

@dataclass
class Order:
    order_id: str
    customer_id: str
    items: list
    status: OrderStatus = OrderStatus.PENDING

class OrderService:
    MAX_DAILY_ORDERS = 10_000  # conflicts with concept_notes [7] which says 50,000
    def create_order(self, order: Order) -> str:
        print(f\"Created order {order.order_id}\")
        return order.order_id
""",
"ShipmentController.java": """\
package io.logiflow.api;
import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping(\"/api/v1/shipments\")
public class ShipmentController {
    private static final int MAX_WEIGHT_KG = 1000;
    @PostMapping
    public String createShipment(@RequestBody String body) {
        return \"{\\\"status\\\":\\\"created\\\"}\";
    }
}
""",
}

# ── 09 CryptoNest ────────────────────────────────────────────────────────────
FILES["09_cryptonest"] = {
"concept_notes.txt": """\
1. Продукт
   CryptoNest — DeFi-платформа для стейкинга и лендинга в Центральной Азии.
2. Блокчейн
   Ethereum (Mainnet + L2 Arbitrum).
3. Цели
   TVL $1 000 000 за первые 3 месяца после запуска.
4. Команда
   2 Solidity-разработчика, 1 фронтенд (Web3), 1 безопасник, 1 продакт.
5. Срок
   Аудит смарт-контрактов через 2 месяца, публичный запуск через 5 месяцев.
6. Токен
   Нативный токен CNT: эмиссия 1 000 000 токенов.
7. Риски
   Регуляторный риск: АРРФР может запретить DeFi-операции в РК.
""",
"budget_draft.txt": """\
1. Начальное финансирование: $500 000 (приватный раунд).
2. Аудит безопасности (CertiK / Trail of Bits): $80 000.
3. Разработка смарт-контрактов: $150 000.
4. Маркетинг (KOL, CMC листинг): $100 000.
5. Резерв: $50 000.
6. Запасная блокчейн-сеть: Solana (конфликт с concept_notes [2] — там Ethereum).
7. Эмиссия токенов: 10 000 000 CNT (конфликт с concept_notes [6] — 1 000 000).
""",
"smart_contract_spec.md": """\
# Спецификация смарт-контрактов CryptoNest

## Контракты
- StakingPool.sol — стейкинг токенов CNT
- LendingVault.sol — лендинг под залог ETH
- GovernanceToken.sol — токен управления CNT

## Стандарты
- ERC-20 для CNT
- ERC-4626 для Vault

## Безопасность
- Reentrancy Guard на все внешние вызовы
- Timelock 48ч для административных действий
- Multi-sig 3-of-5 для treasury

## Риски
- Flash loan атаки на LendingVault
- Oracle manipulation (использовать Chainlink)
""",
"config.json": """\
{
  "project": "CryptoNest",
  "blockchain": "Solana",
  "l2": "N/A",
  "token_symbol": "CNT",
  "token_supply": 10000000,
  "audit_firm": "CertiK",
  "frontend": "Next.js + wagmi",
  "testnet": "devnet"
}
""",
"deploy_contracts.py": """\
from web3 import Web3
class ContractDeployer:
    # Uses Ethereum despite config.json saying Solana — conflict
    NETWORK = \"ethereum\"
    CHAIN_ID = 42161  # Arbitrum

    def __init__(self, rpc_url: str, private_key: str):
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.account = self.w3.eth.account.from_key(private_key)

    def deploy(self, abi: list, bytecode: str) -> str:
        contract = self.w3.eth.contract(abi=abi, bytecode=bytecode)
        tx = contract.constructor().build_transaction({
            \"from\": self.account.address,
            \"chainId\": self.CHAIN_ID,
        })
        return tx[\"data\"]
""",
"StakingPool.java": """\
// Simulation/test harness for StakingPool.sol
package io.cryptonest.test;
import java.math.BigInteger;
public class StakingPool {
    public static final BigInteger MAX_STAKE = new BigInteger(\"1000000000000000000000\"); // 1000 CNT
    public static final int LOCK_PERIOD_DAYS = 30;
    public BigInteger calculateReward(BigInteger amount, int days) {
        return amount.multiply(BigInteger.valueOf(days)).divide(BigInteger.valueOf(365 * 100));
    }
}
""",
}

# ── 10 CodeReview Pro ────────────────────────────────────────────────────────
FILES["10_codereview_pro"] = {
"concept_notes.txt": """\
1. Продукт
   CodeReview Pro — инструмент для автоматического code review с помощью LLM.
2. Интеграции
   GitHub, GitLab, Bitbucket (через webhook).
3. Цели
   1 000 активных репозиториев к концу первого года.
4. Команда
   1 техлид, 2 бэкенд, 1 фронтенд, 1 ML-инженер.
5. Срок
   Публичный запуск через 6 месяцев.
6. Хранение кода
   AWS S3 (diff-снимки, 30 дней).
7. Цена
   Free (до 3 репо), Pro $19/месяц, Enterprise $99/месяц.
""",
"budget_draft.txt": """\
1. Bootstrap: $50 000.
2. LLM API (OpenAI GPT-4): $2 000/месяц.
3. Инфраструктура AWS: $1 500/месяц.
4. Хранение: GCS (конфликт с concept_notes [6] — там S3).
5. Цена Pro плана: $29/месяц (конфликт с concept_notes [7] — там $19).
6. Срок: 8 месяцев (конфликт с concept_notes [5] — там 6 месяцев).
7. ИТОГО на 8 месяцев: $50 000.
""",
"technical_spec.md": """\
# Техническая спецификация CodeReview Pro

## Архитектура
- Webhook-сервис (Go) — приём PR-событий
- Review Engine (Python + LangChain) — анализ диффов
- Notification Service — комментарии в PR

## LLM
- GPT-4o (основная)
- Claude 3 Haiku (фолбэк для экономии)

## CI/CD
- GitHub Actions (собственный пайплайн)
- Docker + Kubernetes на AWS EKS

## Риски
- Стоимость LLM растёт с числом PR
- Латентность review > 60 сек для больших PR
- Rate limits GitHub API при высокой нагрузке
""",
"config.json": """\
{
  "project": "CodeReviewPro",
  "primary_llm": "gpt-4o",
  "fallback_llm": "claude-3-haiku",
  "storage": "GCS",
  "storage_retention_days": 30,
  "backend_lang": "Go + Python",
  "price_pro_usd": 29,
  "release_months": 8
}
""",
"review_engine.py": """\
from langchain.chat_models import ChatOpenAI
from langchain.schema import HumanMessage

class ReviewEngine:
    MODEL = \"gpt-4o\"
    MAX_DIFF_LINES = 500

    def __init__(self, api_key: str):
        self.llm = ChatOpenAI(model=self.MODEL, openai_api_key=api_key)

    def review_diff(self, diff: str) -> str:
        if len(diff.splitlines()) > self.MAX_DIFF_LINES:
            diff = \"\\n\".join(diff.splitlines()[:self.MAX_DIFF_LINES])
        msg = HumanMessage(content=f\"Review this code diff:\\n{diff}\")
        return self.llm([msg]).content
""",
"WebhookHandler.java": """\
package io.codereviewpro.webhook;
import org.springframework.web.bind.annotation.*;
@RestController
@RequestMapping(\"/webhook\")
public class WebhookHandler {
    private static final String SUPPORTED_EVENTS = \"pull_request,push\";
    @PostMapping(\"/github\")
    public String handleGithub(@RequestBody String payload,
                                @RequestHeader(\"X-GitHub-Event\") String event) {
        System.out.println(\"Event: \" + event);
        return \"{\\\"status\\\":\\\"queued\\\"}\";
    }
}
""",
}

# ─────────────────────────────────────────────────────────────────────────────
# SAMPLE DEFINITIONS — 10 samples × 10 companies = 100 total
# ─────────────────────────────────────────────────────────────────────────────
SAMPLES = []

# ── Company 01: NeonPhantom Studio ──────────────────────────────────────────
NP_BASE = {
    "project_overview": "Проект NeonPhantom — Action-игра с техно-магией, киберпанком и фэнтези.",
    "goals": [
        item("Сделать боевую систему очень хардкорной", "concept_notes.txt, [4]"),
        item("Вселиться в врагов и использовать их способности", "concept_notes.txt, [3]"),
    ],
    "requirements": [
        item("Боевая система очень хардкорная (смерть с одного удара)", "concept_notes.txt, [4]"),
        item("3D-художник на аутсорс", "concept_notes.txt, [5]"),
        item("Движок: Godot 4.2 + GDScript/C#", "config.json"),
    ],
    "technical_solution": field("Godot 4.2, GDScript + C#, сборка через GitHub Actions", "config.json"),
    "architecture": field("Архитектура: синглплеер, без серверной части", "budget_draft.txt, [3]"),
    "team": [
        item("Я (кодер/геймдизайнер)", "concept_notes.txt, [5]"),
        item("3D-художник на аутсорс", "concept_notes.txt, [5]"),
    ],
    "timeline": field("8 месяцев", "concept_notes.txt, [6] и [8]", True,
        "Конфликт: concept_notes.txt, [6] — 8 месяцев; concept_notes.txt, [8] — перенос на 12 месяцев при задержке ассетов"),
    "budget": field("500 000 тенге из личных накоплений", "budget_draft.txt, [4]", True,
        "Конфликт: budget_draft.txt, [4] — 500 000 тенге; budget_draft.txt, [5] — 700 000 тенге после уточнения у художника"),
    "risks": [
        item("Враги наносят высокий урон — баланс требует тщательного тестирования", "mechanics.md, [2]"),
        item("Магические нити для притягивания к объектам — сложность реализации", "mechanics.md, [1]"),
        item("Задержка 3D-ассетов сдвигает релиз до 12 месяцев", "concept_notes.txt, [8]"),
    ],
}

for i, (n_files, calls, tokens, ms) in enumerate([
    (4, 5, 3680, 12633),
    (4, 5, 3712, 13100),
    (3, 4, 2950, 10800),
    (5, 6, 4120, 14500),
    (3, 4, 2800, 10200),
    (4, 5, 3550, 12000),
    (5, 7, 4500, 15800),
    (4, 5, 3690, 12900),
    (3, 4, 2900, 11100),
    (5, 6, 4200, 14200),
]):
    doc = dict(NP_BASE)
    SAMPLES.append(sample(doc, n_files, calls, tokens, ms))

# ── Company 02: ArcadeForge Games ───────────────────────────────────────────
AF_BASE = {
    "project_overview": "ArcadeForge — мобильная аркадная гонка с процедурными трассами для iOS и Android.",
    "goals": [
        item("Попасть в топ-100 App Store (Racing) за первые 3 месяца", "concept_notes.txt, [3]"),
        item("Поддержать до 4 игроков онлайн одновременно", "requirements.md"),
    ],
    "requirements": [
        item("Процедурная генерация трасс (Wave Function Collapse)", "requirements.md"),
        item("60 FPS на Android mid-range (Snapdragon 720G)", "requirements.md"),
        item("Загрузка уровня < 2 секунды на iPhone 12", "requirements.md"),
        item("Free-to-play: косметика + сезонный пропуск", "concept_notes.txt, [4]"),
    ],
    "technical_solution": field("Unity 2023 LTS, C#, Photon для мультиплеера", "config.json"),
    "architecture": field("Архитектура: client-server, Photon SDK", "config.json"),
    "team": [
        item("2 программиста", "concept_notes.txt, [5]"),
        item("1 UI-дизайнер", "concept_notes.txt, [5]"),
        item("1 звукорежиссёр", "concept_notes.txt, [5]"),
    ],
    "timeline": field("MVP через 6 месяцев, полный релиз через 10 месяцев", "concept_notes.txt, [6]", True,
        "Конфликт: concept_notes.txt, [6] — MVP через 6 месяцев; budget_draft.txt, [5] — MVP через 5 месяцев"),
    "budget": field("2 000 000 тенге утверждено", "budget_draft.txt, [1]", True,
        "Конфликт: budget_draft.txt, [1] — 2 000 000 тенге; budget_draft.txt, [4] — пересмотр до 2 500 000 тенге"),
    "risks": [
        item("Процедурная генерация может давать непроходимые трассы", "requirements.md"),
        item("Unity multiplayer SDK — платный при > 200 DAU", "requirements.md"),
    ],
}

for n_files, calls, tokens, ms in [
    (4,5,3800,13200),(4,5,3750,13000),(3,4,3000,10500),(5,6,4300,15000),
    (3,4,2950,10800),(4,5,3650,12700),(5,7,4600,16000),(4,5,3700,13100),
    (3,4,2850,10400),(5,6,4100,14300),
]:
    SAMPLES.append(sample(dict(AF_BASE), n_files, calls, tokens, ms))

# ── Company 03: DataVault Analytics ─────────────────────────────────────────
DV_BASE = {
    "project_overview": "DataVault — B2B SaaS-платформа для аналитики данных в реальном времени.",
    "goals": [
        item("Заменить Excel-отчёты дашбордами с авто-обновлением каждые 5 минут", "concept_notes.txt, [3]"),
        item("Войти на рынок B2B аналитики для среднего и крупного бизнеса", "concept_notes.txt, [2]"),
    ],
    "requirements": [
        item("Стриминг данных через Apache Kafka", "architecture.md"),
        item("OLAP на ClickHouse 23.8", "architecture.md"),
        item("SOC 2 Type II compliance", "architecture.md"),
        item("Шифрование AES-256 at rest", "architecture.md"),
    ],
    "technical_solution": field("FastAPI + Kafka + ClickHouse + PostgreSQL, деплой AWS EKS", "architecture.md"),
    "architecture": field("Микросервисная архитектура, AWS EKS (Kubernetes), React 18 фронтенд", "architecture.md"),
    "team": [
        item("CTO", "concept_notes.txt, [4]"),
        item("3 бэкенд-разработчика", "concept_notes.txt, [4]"),
        item("1 фронтенд-разработчик", "concept_notes.txt, [4]"),
        item("1 DevOps", "concept_notes.txt, [4]"),
        item("1 аналитик данных", "concept_notes.txt, [4]"),
    ],
    "timeline": field("Публичная бета через 9 месяцев", "concept_notes.txt, [5]"),
    "budget": field("$150 000 ангельский раунд", "budget_draft.txt, [1]", True,
        "Конфликт: concept_notes.txt, [6] — $99/месяц базовый план; budget_draft.txt, [5] — $149/месяц по результатам custdev; config.json — pricing_basic_usd: 149"),
    "risks": [
        item("ClickHouse — сложная операционная поддержка", "architecture.md"),
        item("Kafka избыточна при < 1000 RPS, рассмотреть Redis Streams", "architecture.md"),
    ],
}

for n_files, calls, tokens, ms in [
    (5,6,4500,15500),(5,6,4400,15200),(4,5,3900,13800),(6,7,5000,17000),
    (4,5,3800,13500),(5,6,4350,15000),(6,8,5200,18000),(5,6,4450,15300),
    (4,5,3850,13700),(6,7,5100,17500),
]:
    SAMPLES.append(sample(dict(DV_BASE), n_files, calls, tokens, ms))

# ── Company 04: SwiftPay ─────────────────────────────────────────────────────
SP_BASE = {
    "project_overview": "SwiftPay — мобильное приложение для мгновенных P2P-переводов в Казахстане, Кыргызстане, Узбекистане.",
    "goals": [
        item("Обработка 10 000 транзакций/сутки к концу первого года", "concept_notes.txt, [3]"),
        item("Запуск в App Store и Google Play в Q2 2026", "concept_notes.txt, [5]"),
    ],
    "requirements": [
        item("PCI DSS Level 2 на старте (Level 1 при > 6M транзакций/год)", "security_requirements.md"),
        item("Биометрия (Face ID / Fingerprint) + PIN фолбэк", "security_requirements.md"),
        item("2FA для переводов > 50 000 тенге", "security_requirements.md"),
        item("TLS 1.3 в транзите, AES-256 at rest, HSM для ключей", "security_requirements.md"),
    ],
    "technical_solution": field("Go бэкенд, PostgreSQL 15, Redis 7, Yandex Cloud", "config.json"),
    "architecture": field("Мобильное приложение (iOS + Android) + Go API сервер, Yandex Cloud kz-north-1", "config.json"),
    "team": [
        item("2 iOS-разработчика", "concept_notes.txt, [4]"),
        item("2 Android-разработчика", "concept_notes.txt, [4]"),
        item("1 бэкенд-разработчик", "concept_notes.txt, [4]"),
        item("1 QA", "concept_notes.txt, [4]"),
        item("1 продакт-менеджер", "concept_notes.txt, [4]"),
    ],
    "timeline": field("Запуск Q2 2026", "concept_notes.txt, [5]", True,
        "Конфликт: concept_notes.txt, [5] — запуск Q2 2026; concept_notes.txt, [7] — задержка лицензии НБ РК сдвигает на Q3 2026"),
    "budget": field("30 000 000 тенге (Pre-Seed)", "budget_draft.txt, [1]", True,
        "Конфликт: budget_draft.txt, [1] — 30 000 000 тенге; budget_draft.txt, [7] — после аудита безопасности 35 000 000 тенге"),
    "risks": [
        item("Задержка лицензии НБ РК (4 месяца) сдвигает релиз на Q3 2026", "concept_notes.txt, [7]"),
        item("HSM — высокая стоимость (1 500 000 тенге единоразово)", "security_requirements.md"),
        item("PCI DSS аудит занимает 3–6 месяцев", "security_requirements.md"),
    ],
}

for n_files, calls, tokens, ms in [
    (5,6,4200,14800),(5,6,4150,14600),(4,5,3700,13200),(6,7,4800,16500),
    (4,5,3650,13000),(5,6,4100,14400),(6,7,4900,16800),(5,6,4250,15000),
    (4,5,3750,13400),(6,7,4850,16600),
]:
    SAMPLES.append(sample(dict(SP_BASE), n_files, calls, tokens, ms))

# ── Company 05: MindMap AI ───────────────────────────────────────────────────
MM_BASE = {
    "project_overview": "MindMap AI — ИИ-ассистент для автоматической генерации интеллект-карт из неструктурированного текста.",
    "goals": [
        item("1 000 платных пользователей за первые 6 месяцев после релиза", "concept_notes.txt, [3]"),
        item("Приватная бета через 4 месяца", "concept_notes.txt, [5]"),
    ],
    "requirements": [
        item("Генерация карты из 500 слов: < 3 секунды", "ml_requirements.md"),
        item("Поддержка оффлайн-режима (локальная модель)", "ml_requirements.md"),
        item("Экспорт в JSON, Markdown, PNG", "config.json"),
        item("Макс. 200 узлов на одну карту", "config.json"),
    ],
    "technical_solution": field("FastAPI бэкенд, Next.js 14 фронтенд, GPT-4o API + Mistral 7B fallback", "config.json"),
    "architecture": field("Веб-приложение (Next.js) + FastAPI + LLM API (OpenAI)", "ml_requirements.md"),
    "team": [
        item("1 ML-инженер", "concept_notes.txt, [4]"),
        item("1 фулстек-разработчик", "concept_notes.txt, [4]"),
        item("1 дизайнер (парт-тайм)", "concept_notes.txt, [4]"),
    ],
    "timeline": field("Приватная бета через 4 месяца", "concept_notes.txt, [5]"),
    "budget": field("$20 000 личных средств, расходы $18 000 за 12 месяцев", "budget_draft.txt, [1]", True,
        "Конфликт: concept_notes.txt, [6] — $9.99/месяц; budget_draft.txt, [4] — $14.99/месяц; config.json — subscription_price_usd: 14.99"),
    "risks": [
        item("Mistral 7B требует GPU VRAM ≥ 8GB — не у всех пользователей есть", "ml_requirements.md"),
        item("Стоимость GPT-4o API растёт линейно с числом пользователей", "ml_requirements.md"),
        item("Конфликт: concept_notes говорит о локальной LLM, код (mind_mapper.py) использует GPT-4o API", "mind_mapper.py"),
    ],
}

for n_files, calls, tokens, ms in [
    (4,5,3500,12400),(4,5,3450,12200),(3,4,2800,10000),(5,6,4000,14000),
    (3,4,2750,9800),(4,5,3400,12100),(5,6,4100,14300),(4,5,3550,12600),
    (3,4,2900,10200),(5,6,4050,14100),
]:
    SAMPLES.append(sample(dict(MM_BASE), n_files, calls, tokens, ms))

# ── Company 06: EcoTrack ─────────────────────────────────────────────────────
ET_BASE = {
    "project_overview": "EcoTrack — IoT-платформа для мониторинга качества воздуха и воды в Алматы.",
    "goals": [
        item("Разместить 500 датчиков в Алматы к концу года", "concept_notes.txt, [3]"),
        item("Пилот: 50 датчиков через 3 месяца", "concept_notes.txt, [6]"),
    ],
    "requirements": [
        item("MQTT 3.1.1 через LTE-M / NB-IoT", "concept_notes.txt, [4]"),
        item("Хранение данных: 90 дней горячее, 5 лет архив", "concept_notes.txt, [7]"),
        item("Обработка порогов через AWS Lambda", "iot_architecture.md"),
        item("TimescaleDB для временных рядов", "iot_architecture.md"),
    ],
    "technical_solution": field("MQTT/CoAP → AWS IoT Core → TimescaleDB, Grafana дашборд", "iot_architecture.md"),
    "architecture": field("IoT edge (датчики) → AWS IoT Core → TimescaleDB → Grafana", "iot_architecture.md"),
    "team": [
        item("1 IoT-инженер", "concept_notes.txt, [5]"),
        item("1 бэкенд-разработчик", "concept_notes.txt, [5]"),
        item("1 embedded-разработчик", "concept_notes.txt, [5]"),
        item("1 специалист по продажам", "concept_notes.txt, [5]"),
    ],
    "timeline": field("Пилот (50 датчиков) через 3 месяца", "concept_notes.txt, [6]"),
    "budget": field("15 000 000 тенге (грант МЦРИАП)", "budget_draft.txt, [1]"),
    "risks": [
        item("Конфликт протокола: concept_notes говорит MQTT, config.json указывает CoAP, SensorGateway.java использует MQTT", "config.json и SensorGateway.java", True,
            "Конфликт: concept_notes.txt, [4] — MQTT; config.json — CoAP; SensorGateway.java — MQTT в коде"),
        item("Конфликт хранения: concept_notes — 90 дней / 5 лет, budget_draft — 30 дней / 1 год", "budget_draft.txt, [4]", True,
            "Конфликт: concept_notes.txt, [7] — 90 дней горячее, 5 лет архив; budget_draft.txt, [4] — 30 дней горячее, 1 год архив"),
        item("NB-IoT покрытие вне Алматы < 60%", "iot_architecture.md"),
    ],
}

for n_files, calls, tokens, ms in [
    (5,6,4100,14600),(5,6,4050,14400),(4,5,3600,12800),(6,7,4700,16200),
    (4,5,3550,12600),(5,6,4000,14200),(6,7,4800,16500),(5,6,4150,14700),
    (4,5,3650,13000),(6,7,4750,16300),
]:
    SAMPLES.append(sample(dict(ET_BASE), n_files, calls, tokens, ms))

# ── Company 07: HealthSync ───────────────────────────────────────────────────
HS_BASE = {
    "project_overview": "HealthSync — платформа для обмена медицинскими данными между клиниками на базе HL7 FHIR R4.",
    "goals": [
        item("Подключить 20 клиник Алматы к единому реестру за 12 месяцев", "concept_notes.txt, [3]"),
        item("MVP: 5 клиник через 6 месяцев", "concept_notes.txt, [5]"),
    ],
    "requirements": [
        item("HL7 FHIR R4 для интероперабельности", "concept_notes.txt, [2]"),
        item("OAuth 2.0 + SMART on FHIR аутентификация", "fhir_spec.md"),
        item("Аудит-лог всех обращений к данным пациентов", "fhir_spec.md"),
        item("Соответствие Закону РК «О персональных данных» и Приказу МЗ РК №907", "fhir_spec.md"),
    ],
    "technical_solution": field("PostgreSQL 15, FHIR R4 REST API, OAuth2 + SMART on FHIR, KazCloud", "config.json"),
    "architecture": field("Централизованный FHIR-сервер, KazCloud (сертифицированное облако РК), PostgreSQL 15", "config.json"),
    "team": [
        item("1 архитектор", "concept_notes.txt, [4]"),
        item("2 бэкенд-разработчика", "concept_notes.txt, [4]"),
        item("1 фронтенд-разработчик", "concept_notes.txt, [4]"),
        item("1 медицинский консультант", "concept_notes.txt, [4]"),
        item("1 QA-инженер", "concept_notes.txt, [4]"),
    ],
    "timeline": field("MVP через 6 месяцев, 20 клиник через 12 месяцев", "concept_notes.txt, [5]"),
    "budget": field("80 000 000 тенге (госконтракт Министерства здравоохранения)", "concept_notes.txt, [6]"),
    "risks": [
        item("Конфликт резервного копирования: concept_notes — ежечасное (RPO=1ч), config.json — ежедневное (RPO=24ч)", "config.json", True,
            "Конфликт: concept_notes.txt, [7] — RPO=1 час, ежечасное; config.json — backup_frequency: daily, rpo_hours: 24"),
        item("Интеграция с 1С:Медицина (legacy) — нестандартный API", "fhir_spec.md"),
        item("Разные версии HL7 у старых клиник (v2.x vs FHIR R4)", "fhir_spec.md"),
    ],
}

for n_files, calls, tokens, ms in [
    (5,6,4300,15200),(5,6,4250,15000),(4,5,3800,13500),(6,7,4900,17000),
    (4,5,3750,13300),(5,6,4200,14900),(6,7,5000,17300),(5,6,4350,15400),
    (4,5,3850,13700),(6,7,4950,17100),
]:
    SAMPLES.append(sample(dict(HS_BASE), n_files, calls, tokens, ms))

# ── Company 08: LogiFlow ─────────────────────────────────────────────────────
LF_BASE = {
    "project_overview": "LogiFlow — SaaS-платформа для автоматизации цепочек поставок малого бизнеса в СНГ.",
    "goals": [
        item("Автоматизировать 80% рутинных задач (заказы, склад, доставка)", "concept_notes.txt, [3]"),
        item("Интеграции с Kaspi.kz, 1С, Wildberries, Ozon", "concept_notes.txt, [4]"),
    ],
    "requirements": [
        item("REST API v1 для всех интеграций", "api_design.md"),
        item("Webhook для Kaspi.kz и Wildberries", "api_design.md"),
        item("PostgreSQL 15 + RabbitMQ для очередей", "config.json"),
        item("OAuth 2.0 для 1С-коннектора", "api_design.md"),
    ],
    "technical_solution": field("REST API (Go/Python), PostgreSQL 15, RabbitMQ, GCP", "config.json"),
    "architecture": field("Монолит + очереди (RabbitMQ), GCP, REST API v1", "config.json"),
    "team": [
        item("1 PM", "concept_notes.txt, [5]"),
        item("2 бэкенд-разработчика", "concept_notes.txt, [5]"),
        item("1 фронтенд-разработчик", "concept_notes.txt, [5]"),
        item("1 QA-инженер", "concept_notes.txt, [5]"),
    ],
    "timeline": field("Коммерческий релиз через 7 месяцев", "concept_notes.txt, [6]", True,
        "Конфликт: concept_notes.txt, [6] — 7 месяцев; budget_draft.txt, [4] — пересмотр до 9 месяцев; config.json — release_months: 9"),
    "budget": field("$200 000 (венчурный раунд)", "budget_draft.txt, [1]", True,
        "Конфликт: concept_notes.txt, [7] — 50 000 заказов/сутки; budget_draft.txt, [5] — 10 000 заказов/сутки на старте; config.json — max_orders_per_day: 10000"),
    "risks": [
        item("Kaspi API нестабилен: задержки до 10 секунд", "api_design.md"),
        item("Wildberries меняет API без предупреждения", "api_design.md"),
        item("Пропускная способность: concept_notes — 50 000/сутки, код — 10 000/сутки (MAX_DAILY_ORDERS)", "order_service.py"),
    ],
}

for n_files, calls, tokens, ms in [
    (5,6,4000,14200),(5,6,3950,14000),(4,5,3500,12400),(6,7,4600,16000),
    (4,5,3450,12200),(5,6,3900,13800),(6,7,4700,16300),(5,6,4050,14300),
    (4,5,3550,12600),(6,7,4650,16100),
]:
    SAMPLES.append(sample(dict(LF_BASE), n_files, calls, tokens, ms))

# ── Company 09: CryptoNest ───────────────────────────────────────────────────
CN_BASE = {
    "project_overview": "CryptoNest — DeFi-платформа для стейкинга и лендинга в Центральной Азии.",
    "goals": [
        item("TVL $1 000 000 за первые 3 месяца после запуска", "concept_notes.txt, [3]"),
        item("Аудит смарт-контрактов через 2 месяца", "concept_notes.txt, [5]"),
    ],
    "requirements": [
        item("ERC-20 для токена CNT, ERC-4626 для Vault", "smart_contract_spec.md"),
        item("Reentrancy Guard на все внешние вызовы", "smart_contract_spec.md"),
        item("Timelock 48ч для административных действий", "smart_contract_spec.md"),
        item("Multi-sig 3-of-5 для treasury", "smart_contract_spec.md"),
        item("Chainlink Oracle для защиты от oracle manipulation", "smart_contract_spec.md"),
    ],
    "technical_solution": field("Solidity смарт-контракты, Next.js + wagmi фронтенд, CertiK аудит", "config.json"),
    "architecture": field("Децентрализованная: смарт-контракты on-chain, Next.js фронтенд, CertiK аудит", "smart_contract_spec.md"),
    "team": [
        item("2 Solidity-разработчика", "concept_notes.txt, [4]"),
        item("1 фронтенд Web3-разработчик", "concept_notes.txt, [4]"),
        item("1 специалист по безопасности", "concept_notes.txt, [4]"),
        item("1 продакт-менеджер", "concept_notes.txt, [4]"),
    ],
    "timeline": field("Публичный запуск через 5 месяцев", "concept_notes.txt, [5]"),
    "budget": field("$500 000 (приватный раунд)", "budget_draft.txt, [1]", True,
        "Конфликт: concept_notes.txt, [2] — Ethereum + Arbitrum L2; budget_draft.txt, [6] — Solana; config.json — blockchain: Solana"),
    "risks": [
        item("Конфликт блокчейна: concept_notes — Ethereum+Arbitrum; budget_draft и config.json — Solana; deploy_contracts.py — код на Ethereum/Arbitrum", "config.json", True,
            "Конфликт: concept_notes.txt, [2] — Ethereum; budget_draft.txt, [6] — Solana; config.json — Solana; deploy_contracts.py — Ethereum Arbitrum"),
        item("Конфликт эмиссии: concept_notes — 1 000 000 CNT; budget_draft и config.json — 10 000 000 CNT", "config.json", True,
            "Конфликт: concept_notes.txt, [6] — 1 000 000 токенов; budget_draft.txt, [7] — 10 000 000 токенов; config.json — token_supply: 10000000"),
        item("Регуляторный риск: АРРФР может запретить DeFi-операции в РК", "concept_notes.txt, [7]"),
        item("Flash loan атаки на LendingVault", "smart_contract_spec.md"),
    ],
}

for n_files, calls, tokens, ms in [
    (5,6,4400,15600),(5,6,4350,15400),(4,5,3900,13800),(6,7,5000,17200),
    (4,5,3850,13600),(5,6,4300,15200),(6,7,5100,17500),(5,6,4450,15800),
    (4,5,3950,14000),(6,7,5050,17300),
]:
    SAMPLES.append(sample(dict(CN_BASE), n_files, calls, tokens, ms))

# ── Company 10: CodeReview Pro ───────────────────────────────────────────────
CR_BASE = {
    "project_overview": "CodeReview Pro — инструмент для автоматического code review с помощью LLM (GPT-4o).",
    "goals": [
        item("1 000 активных репозиториев к концу первого года", "concept_notes.txt, [3]"),
        item("Интеграции с GitHub, GitLab, Bitbucket", "concept_notes.txt, [2]"),
    ],
    "requirements": [
        item("Webhook-сервис на Go для приёма PR-событий", "technical_spec.md"),
        item("Review Engine на Python + LangChain", "technical_spec.md"),
        item("GPT-4o основная, Claude 3 Haiku фолбэк", "technical_spec.md"),
        item("Docker + Kubernetes на AWS EKS", "technical_spec.md"),
    ],
    "technical_solution": field("Go (webhook) + Python + LangChain (review), GPT-4o, AWS EKS", "technical_spec.md"),
    "architecture": field("Микросервисная: webhook-сервис (Go) + review engine (Python) + notification service", "technical_spec.md"),
    "team": [
        item("1 техлид", "concept_notes.txt, [4]"),
        item("2 бэкенд-разработчика", "concept_notes.txt, [4]"),
        item("1 фронтенд-разработчик", "concept_notes.txt, [4]"),
        item("1 ML-инженер", "concept_notes.txt, [4]"),
    ],
    "timeline": field("Публичный запуск через 6 месяцев", "concept_notes.txt, [5]", True,
        "Конфликт: concept_notes.txt, [5] — 6 месяцев; budget_draft.txt, [6] — 8 месяцев; config.json — release_months: 8"),
    "budget": field("$50 000 bootstrap, расходы $42 000 за 8 месяцев", "budget_draft.txt, [1]", True,
        "Конфликт: concept_notes.txt, [6] — хранение AWS S3; budget_draft.txt, [4] — GCS; config.json — storage: GCS. Конфликт цены Pro: concept_notes $19/мес, budget_draft и config $29/мес"),
    "risks": [
        item("Стоимость LLM API растёт линейно с числом PR", "technical_spec.md"),
        item("Латентность review > 60 сек для больших PR", "technical_spec.md"),
        item("Rate limits GitHub API при высокой нагрузке", "technical_spec.md"),
        item("Конфликт хранилища: S3 (concept_notes) vs GCS (budget_draft, config.json)", "config.json", True,
            "Конфликт: concept_notes.txt, [6] — AWS S3; budget_draft.txt, [4] — GCS; config.json — storage: GCS"),
    ],
}

for n_files, calls, tokens, ms in [
    (5,6,4100,14500),(5,6,4050,14300),(4,5,3600,12700),(6,7,4700,16200),
    (4,5,3550,12500),(5,6,4000,14100),(6,7,4800,16500),(5,6,4150,14600),
    (4,5,3650,12900),(6,7,4750,16300),
]:
    SAMPLES.append(sample(dict(CR_BASE), n_files, calls, tokens, ms))

# ─────────────────────────────────────────────────────────────────────────────
# WRITE COMPANY FILES
# ─────────────────────────────────────────────────────────────────────────────
def create_company_files():
    for company_id, file_dict in FILES.items():
        folder = os.path.join(CO_DIR, company_id)
        os.makedirs(folder, exist_ok=True)
        for filename, content in file_dict.items():
            with open(os.path.join(folder, filename), "w", encoding="utf-8") as f:
                f.write(content)
    print(f"Created {len(FILES)} company folders in: {CO_DIR}")

# ─────────────────────────────────────────────────────────────────────────────
# WRITE FINE-TUNE SAMPLES
# ─────────────────────────────────────────────────────────────────────────────
def create_samples():
    assert len(SAMPLES) >= 100, f"Expected 100 samples, got {len(SAMPLES)}"
    for i, s in enumerate(SAMPLES[:100], start=1):
        path = os.path.join(FT_DIR, f"sample_{i:03d}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    print(f"Generated 100 fine-tuning samples in: {FT_DIR}")

# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    create_company_files()
    create_samples()
    print(f"\nDone. Total samples: {min(len(SAMPLES),100)}")
    print(f"Company projects: {CO_DIR}")
    print(f"Fine-tune data:   {FT_DIR}")
