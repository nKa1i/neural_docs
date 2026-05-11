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
