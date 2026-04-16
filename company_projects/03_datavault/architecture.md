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
