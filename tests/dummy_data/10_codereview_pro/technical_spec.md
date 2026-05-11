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
