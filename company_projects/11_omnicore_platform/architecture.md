# OmniCore Platform — Architecture & Technical Design Document

**Version:** 2.4  
**Status:** Draft (under review)  
**Authors:** Denis Krasnov (Chief Architect), Kirill Osipov (CTO), Alexey Volkov (Tech Lead Backend)  
**Last Updated:** 2025-02-20  
**Review Deadline:** 2025-03-15

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Context](#2-system-context)
3. [Architecture Principles](#3-architecture-principles)
4. [High-Level Architecture](#4-high-level-architecture)
5. [Microservices Decomposition](#5-microservices-decomposition)
6. [Data Architecture](#6-data-architecture)
7. [Event-Driven Design](#7-event-driven-design)
8. [API Design](#8-api-design)
9. [Security Architecture](#9-security-architecture)
10. [Infrastructure & Deployment](#10-infrastructure--deployment)
11. [ML Platform Architecture](#11-ml-platform-architecture)
12. [Observability Stack](#12-observability-stack)
13. [Performance & Scalability](#13-performance--scalability)
14. [Disaster Recovery](#14-disaster-recovery)
15. [Migration Strategy](#15-migration-strategy)
16. [Open Questions & Conflicts](#16-open-questions--conflicts)

---

## 1. Executive Summary

OmniCore Platform is a cloud-native, event-driven ERP system designed to unify 17 business domains under a single platform with native AI capabilities. The architecture prioritises:

- **Scalability**: horizontal scaling to 100,000+ concurrent users
- **Reliability**: 99.99% uptime for Enterprise tier
- **Data integrity**: exactly-once event processing, ACID transactions
- **Developer velocity**: contract-first API development, full IaC

The system is built on 47 independent microservices communicating via gRPC (synchronous) and Apache Kafka (asynchronous), deployed on Kubernetes across 3 cloud regions.

**Key architectural decision**: The platform uses a **shared-nothing** microservice design — each service owns its data store. Cross-service data access happens only through events or well-defined API contracts, never via shared database tables.

---

## 2. System Context

### 2.1 External Actors

| Actor | Interaction | Protocol |
|-------|-------------|----------|
| End Users (ERP operators) | Web UI / Mobile App | HTTPS + WebSocket |
| Enterprise Admins | Admin Console | HTTPS |
| External ERP Systems (SAP, 1C) | Bi-directional sync | REST + SFTP + EDIFACT |
| Banks (12 integrations) | Transaction sync | Open Banking API (ISO 20022) |
| Government APIs (KZ/RU) | Tax reporting | SOAP/REST (legacy) |
| IoT Devices / SCADA | Sensor data ingestion | MQTT 5.0 + HTTP |
| Partner SaaS Tools | Webhooks + API | REST + Webhooks |
| Mobile clients (iOS/Android) | Field operations | GraphQL + REST |

### 2.2 Internal System Boundaries

```
┌─────────────────────────────────────────────────────────┐
│                    OmniCore Platform                      │
│                                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │ Finance  │  │ Manufact │  │  WMS     │  │  CRM   │  │
│  │  Core    │  │  Core    │  │          │  │        │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │ Supply   │  │   HR     │  │  BI &    │  │  AI    │  │
│  │  Chain   │  │ Payroll  │  │Analytics │  │ Engine │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘  │
│                   ... 9 more modules ...                  │
│                                                           │
│  ┌────────────────────────────────────────────────────┐  │
│  │              Event Bus (Apache Kafka)               │  │
│  └────────────────────────────────────────────────────┘  │
│  ┌───────────┐  ┌───────────┐  ┌───────────────────┐    │
│  │ API Gate  │  │  Auth     │  │  Notification Hub  │    │
│  │  (Kong)   │  │  Service  │  │                    │    │
│  └───────────┘  └───────────┘  └───────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Architecture Principles

### 3.1 Core Principles

**P1: Domain Isolation**  
Each business domain (Finance, WMS, HR, etc.) is a bounded context with its own team, codebase, and data store. No cross-domain database joins.

**P2: Event Sourcing for Critical Domains**  
Finance Core, Manufacturing Core, and Inventory use event sourcing. The event log is the source of truth; read models are projections.

**P3: CQRS Pattern**  
All write operations are commands; read operations use separate read models. Read replicas are eventual-consistent (target lag < 500ms).

**P4: API-First Design**  
All service contracts are defined in OpenAPI 3.1 / Proto3 before implementation. Contract tests via Pact ensure compatibility.

**P5: Zero-Trust Security**  
Every service-to-service call is authenticated via mTLS (Istio). No implicit trust even within the cluster.

**P6: Observability First**  
Every service emits structured logs, Prometheus metrics, and distributed traces. SLOs are defined in code and validated in CI.

**P7: Immutable Infrastructure**  
No manual changes to production. All changes go through GitOps (ArgoCD). Config is code.

### 3.2 Architectural Trade-offs

| Decision | Chosen | Rejected | Reason |
|----------|--------|----------|--------|
| Service communication | gRPC + Kafka | REST-only | Performance at scale, strong contracts |
| DB per service | Yes (Shared-nothing) | Shared DB | Prevents tight coupling, enables independent scaling |
| Frontend | Next.js SSR + CSR | Pure SPA | SEO, performance, per-route rendering strategy |
| Event system | Kafka | RabbitMQ | Durability, replayability, throughput |
| Container platform | Kubernetes | ECS / Nomad | Industry standard, talent availability |
| IaC | Terraform | Pulumi / CDK | Team familiarity, provider coverage |
| API versioning | URL-based (/v1, /v2) | Header-based | Explicit, cacheable, easy to route |

---

## 4. High-Level Architecture

### 4.1 Three-Tier Zone Model

```
ZONE 1: DMZ (Internet-facing)
├── AWS CloudFront (CDN)
├── AWS WAF (DDoS + OWASP rules)
├── Kong API Gateway 3.6 (rate limiting, auth, routing)
└── Load Balancer (NLB, cross-AZ)

ZONE 2: Application Tier (Kubernetes)
├── Business Domain Services (47 microservices)
├── AI/ML Services (Triton + Python workers)
├── Background Workers (Celery + Go workers)
└── WebSocket Hub (real-time notifications)

ZONE 3: Data Tier (Managed + Self-hosted)
├── PostgreSQL 16.2 (Patroni HA) — OLTP
├── ClickHouse 24.3 (sharded cluster) — OLAP
├── Redis 7.2 (Sentinel) — Cache + Sessions
├── Kafka 3.7 (5 brokers) — Event streaming
├── Elasticsearch 8.13 — Full-text search
├── Neo4j 5.20 — Supply chain graph
└── S3 / MinIO — Object storage
```

### 4.2 Multi-Region Topology

```
PRIMARY: AWS us-east-1 (Virginia)
├── Full stack deployment
├── Primary write cluster (PostgreSQL)
├── Kafka lead brokers
└── AI/ML training jobs

SECONDARY: AWS eu-central-1 (Frankfurt) — GDPR boundary
├── Full stack deployment (EU customers)
├── PostgreSQL replica + local writes for EU-resident data
├── Kafka MirrorMaker 2 replication
└── Independent ClickHouse cluster

TERTIARY: Yandex Cloud ru-central1 (Moscow) — 152-FZ
├── Full stack deployment (RU customers)
├── Data sovereignty: all RU data stays in RU
└── Air-gapped from AWS (no cross-region replication)

QUATERNARY: Kazakhtelecom Cloud (Almaty) — future (Q3 2026)
└── KZ government compliance (planned)
```

### 4.3 Request Flow (typical user action)

```
User browser
  → CloudFront (cache static assets, TLS termination)
  → WAF (rules check)
  → Kong Gateway (rate limit check, JWT validation, routing)
  → Auth Service (token introspection, RBAC check)
  → Target Microservice (business logic)
    → PostgreSQL (write) OR
    → Redis (cache read) OR
    → Kafka (event publish)
  → Response (JSON/gRPC-JSON)
  → Client
```

---

## 5. Microservices Decomposition

### 5.1 Service Registry (47 services)

| # | Service Name | Language | Responsibilities | DB | Scaling |
|---|-------------|----------|------------------|----|---------|
| 1 | api-gateway | Kong (Lua) | Routing, rate limiting, auth | Redis | Stateless × 4 |
| 2 | auth-service | Go | OAuth2, OIDC, SAML, LDAP | PostgreSQL + Redis | × 3 |
| 3 | user-service | Go | User profiles, RBAC, tenancy | PostgreSQL | × 2 |
| 4 | finance-core | Go | GL, AP/AR, reconciliation | PostgreSQL (event store) | × 4 |
| 5 | budget-service | Go | Budgeting, forecasting | PostgreSQL + ClickHouse | × 2 |
| 6 | payroll-service | Java | Salary calc, tax, 50+ jurisdictions | PostgreSQL | × 3 |
| 7 | invoice-service | Go | Invoice generation, e-invoice (КЗ/РФ) | PostgreSQL | × 2 |
| 8 | manufacturing-core | Go | Production orders, BOM, routing | PostgreSQL (event store) | × 4 |
| 9 | quality-control | Go | QC checks, ISO 9001 compliance | PostgreSQL | × 2 |
| 10 | scada-adapter | Python | SCADA/OPC-UA integration | TimescaleDB | × 2 |
| 11 | wms-core | Go | Warehouse ops, RFID, addressing | PostgreSQL (event store) | × 4 |
| 12 | inventory-service | Go | Stock levels, ABC analysis | PostgreSQL + Redis | × 3 |
| 13 | drone-service | Python | Drone inventory control, CV pipeline | PostgreSQL + S3 | × 2 |
| 14 | supply-chain | Go | Procurement, SRM, tenders | PostgreSQL + Neo4j | × 3 |
| 15 | route-optimizer | Python | VRP solving, ML route prediction | PostgreSQL | × 2 |
| 16 | transport-mgmt | Go | Fleet, tracking, TMS integration | PostgreSQL + TimescaleDB | × 2 |
| 17 | demand-forecast | Python | LSTM + Prophet models | PostgreSQL + MLflow | × 2 |
| 18 | crm-core | Go | Customer 360, opportunities | PostgreSQL | × 3 |
| 19 | churn-prediction | Python | XGBoost model serving | PostgreSQL + Triton | × 2 |
| 20 | cpq-service | Go | Configure, Price, Quote | PostgreSQL + Redis | × 2 |
| 21 | hr-core | Go | Employee records, org chart | PostgreSQL | × 2 |
| 22 | recruitment | Go | ATS, AI resume screening | PostgreSQL + Elasticsearch | × 2 |
| 23 | lms-adapter | Go | Learning management integration | PostgreSQL | × 1 |
| 24 | performance-mgmt | Go | OKR/KPI tracking | PostgreSQL | × 2 |
| 25 | bi-core | Python | OLAP queries, report engine | ClickHouse | × 4 |
| 26 | dashboard-service | Go | Dashboard config, widget store | PostgreSQL + Redis | × 2 |
| 27 | export-service | Go | Excel/PDF report export | PostgreSQL + S3 | × 2 |
| 28 | ai-engine | Python | LLM orchestration, embeddings | PostgreSQL + pgvector | × 3 |
| 29 | doc-intelligence | Python | OCR, document classification, extraction | PostgreSQL + S3 | × 2 |
| 30 | anomaly-detection | Python | Real-time anomaly ML | TimescaleDB + Triton | × 2 |
| 31 | fraud-detection | Python | GNN-based fraud scoring | PostgreSQL + Neo4j + Triton | × 2 |
| 32 | asset-management | Go | Fixed assets, depreciation | PostgreSQL | × 2 |
| 33 | maintenance-mgmt | Go | Preventive maintenance, work orders | PostgreSQL | × 2 |
| 34 | project-mgmt | Go | Projects, milestones, Gantt | PostgreSQL | × 2 |
| 35 | procurement | Go | Purchase orders, vendor portal | PostgreSQL | × 2 |
| 36 | customs-compliance | Go | HS codes, customs declarations | PostgreSQL | × 2 |
| 37 | doc-management | Go | Document storage, versioning, DMS | PostgreSQL + S3 | × 2 |
| 38 | notification-hub | Go | Email, SMS, push, webhook dispatch | PostgreSQL + Redis | × 3 |
| 39 | audit-log | Go | Immutable audit trail | PostgreSQL (append-only) | × 2 |
| 40 | config-service | Go | Dynamic configuration, feature flags | PostgreSQL + Redis | × 2 |
| 41 | scheduler | Go | Cron jobs, task scheduling | PostgreSQL + Redis | × 2 |
| 42 | integration-hub | Go | External ERP adapters (SAP, 1C) | PostgreSQL + RabbitMQ | × 2 |
| 43 | bank-connector | Go | Open Banking API, reconciliation | PostgreSQL | × 2 |
| 44 | iot-ingestion | Go | MQTT, IoT sensor data ingestion | TimescaleDB | × 3 |
| 45 | search-service | Go | Full-text search, autocomplete | Elasticsearch | × 2 |
| 46 | file-service | Go | File upload, S3 proxy, virus scan | S3 + PostgreSQL | × 2 |
| 47 | billing-service | Go | SaaS billing, Stripe integration | PostgreSQL | × 2 |

### 5.2 Service Size Guidelines

- Target: < 10,000 lines of Go code per service (excluding tests)
- Each service: 1 team, max 5 engineers
- Independent deployment: each service has its own CI/CD pipeline
- Database: each service owns ≤ 3 database schemas

---

## 6. Data Architecture

### 6.1 PostgreSQL Domain Databases

Each major domain has an isolated PostgreSQL database:

| Domain | Database Name | Size Estimate (Year 1) | Key Tables |
|--------|--------------|------------------------|------------|
| Finance | omni_finance | 50 GB | journal_entries, accounts, transactions |
| Manufacturing | omni_manufacturing | 30 GB | production_orders, bom_items, work_centers |
| WMS | omni_wms | 80 GB | locations, stock_movements, shipments |
| HR | omni_hr | 5 GB | employees, payroll_runs, attendance |
| CRM | omni_crm | 20 GB | customers, opportunities, interactions |
| Auth | omni_auth | 2 GB | users, roles, sessions, tokens |

### 6.2 Event Store Schema (Finance Core example)

```sql
-- Event sourcing: immutable append-only event log
CREATE TABLE financial_events (
    event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_id    UUID NOT NULL,           -- e.g. journal_entry_id
    aggregate_type  VARCHAR(64) NOT NULL,    -- e.g. 'JournalEntry'
    event_type      VARCHAR(64) NOT NULL,    -- e.g. 'JournalEntryPosted'
    event_version   INTEGER NOT NULL,
    payload         JSONB NOT NULL,
    metadata        JSONB NOT NULL,          -- user_id, trace_id, timestamp
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_fin_events_aggregate ON financial_events (aggregate_id, event_version);

-- Read model (projection) - eventually consistent
CREATE TABLE gl_account_balances (
    account_id      UUID PRIMARY KEY,
    account_code    VARCHAR(20) NOT NULL,
    balance_debit   NUMERIC(18,4) DEFAULT 0,
    balance_credit  NUMERIC(18,4) DEFAULT 0,
    currency        CHAR(3) NOT NULL,
    last_event_id   UUID REFERENCES financial_events(event_id),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
```

### 6.3 ClickHouse Schema (BI Analytics)

```sql
-- Fact table for financial transactions (ClickHouse)
CREATE TABLE finance_transactions_fact (
    date            Date,
    datetime        DateTime64(3),
    transaction_id  UUID,
    tenant_id       UUID,
    account_debit   String,
    account_credit  String,
    amount          Decimal(18, 4),
    currency        FixedString(3),
    exchange_rate   Float64,
    amount_usd      Decimal(18, 4),
    document_type   LowCardinality(String),
    cost_center     String,
    project_id      Nullable(UUID)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (tenant_id, date, transaction_id)
SETTINGS index_granularity = 8192;

-- Warehouse movement fact table
CREATE TABLE wms_movements_fact (
    date            Date,
    datetime        DateTime64(3),
    movement_id     UUID,
    warehouse_id    UUID,
    location_from   String,
    location_to     String,
    sku_id          UUID,
    quantity        Decimal(18, 4),
    unit_of_measure LowCardinality(String),
    movement_type   LowCardinality(String),  -- IN, OUT, TRANSFER, ADJUST
    operator_id     UUID
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(date)
ORDER BY (warehouse_id, date, movement_id);
```

### 6.4 Data Retention Policy

| Data Type | Hot Storage | Warm Storage | Cold Storage | Delete After |
|-----------|-------------|--------------|--------------|--------------|
| Financial events | PostgreSQL, 2 years | S3 Parquet, 5 years | S3 Glacier | 10 years (legal) |
| WMS movements | PostgreSQL, 1 year | ClickHouse, 5 years | S3 Glacier | 7 years |
| IoT/sensor data | TimescaleDB, 90 days | ClickHouse, 2 years | S3 Glacier | 5 years |
| Audit logs | PostgreSQL, 3 years | S3, 7 years | Never delete | — |
| User sessions | Redis, 24h | — | — | 30 days |
| ML model artifacts | S3, indefinite | — | — | Manual |

---

## 7. Event-Driven Design

### 7.1 Kafka Topic Naming Convention

```
{domain}.{entity}.{event_type}.{version}

Examples:
  finance.journal-entry.posted.v1
  wms.stock-movement.created.v1
  manufacturing.production-order.completed.v1
  hr.employee.hired.v1
  crm.opportunity.won.v1
```

### 7.2 Key Kafka Topics

| Topic | Producers | Consumers | Partitions | Retention |
|-------|-----------|-----------|------------|-----------|
| finance.journal-entry.posted.v1 | finance-core | bi-core, audit-log, budget-service | 12 | 7 days |
| wms.stock-movement.created.v1 | wms-core | inventory-service, demand-forecast, bi-core | 24 | 7 days |
| manufacturing.production-order.*.v1 | manufacturing-core | wms-core, supply-chain, bi-core | 12 | 7 days |
| crm.customer.*.v1 | crm-core | churn-prediction, notification-hub | 6 | 7 days |
| hr.payroll-run.completed.v1 | payroll-service | finance-core, notification-hub | 3 | 30 days |
| iot.sensor-data.v1 | iot-ingestion | anomaly-detection, scada-adapter | 48 | 24 hours |
| audit.event.v1 | ALL services | audit-log | 24 | 90 days |

### 7.3 Event Schema (Avro with Schema Registry)

```json
{
  "type": "record",
  "name": "StockMovementCreated",
  "namespace": "com.omnicore.wms.events.v1",
  "fields": [
    {"name": "event_id", "type": "string"},
    {"name": "event_type", "type": "string"},
    {"name": "occurred_at", "type": {"type": "long", "logicalType": "timestamp-millis"}},
    {"name": "tenant_id", "type": "string"},
    {"name": "warehouse_id", "type": "string"},
    {"name": "sku_id", "type": "string"},
    {"name": "quantity_delta", "type": "double"},
    {"name": "movement_type", "type": {"type": "enum", "name": "MovementType", "symbols": ["IN","OUT","TRANSFER","ADJUST"]}},
    {"name": "metadata", "type": {"type": "record", "name": "EventMetadata", "fields": [
      {"name": "user_id", "type": ["null", "string"], "default": null},
      {"name": "trace_id", "type": "string"},
      {"name": "correlation_id", "type": "string"}
    ]}}
  ]
}
```

---

## 8. API Design

### 8.1 REST API Conventions

- Base URL: `https://api.omnicore.io/v1`
- Authentication: Bearer JWT (OAuth2 access token)
- Content-Type: `application/json`
- Pagination: cursor-based (`?cursor=<token>&limit=100`)
- Errors: RFC 7807 Problem Details

```http
GET /v1/finance/journal-entries?cursor=eyJpZCI6MTIzfQ&limit=50
Authorization: Bearer eyJhbGciOiJSUzI1NiIs...

HTTP/1.1 200 OK
Content-Type: application/json
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 847
X-Request-ID: 550e8400-e29b-41d4-a716-446655440000

{
  "data": [...],
  "pagination": {
    "next_cursor": "eyJpZCI6MTczfQ",
    "has_more": true,
    "total_count": 1243
  }
}
```

### 8.2 gRPC Services (Internal)

```protobuf
syntax = "proto3";
package omnicore.wms.v1;

service WarehouseService {
  rpc GetStockLevel(GetStockLevelRequest) returns (StockLevelResponse);
  rpc CreateMovement(CreateMovementRequest) returns (CreateMovementResponse);
  rpc StreamMovements(StreamMovementsRequest) returns (stream StockMovement);
  rpc BatchUpdateLocations(stream LocationUpdate) returns (BatchUpdateResponse);
}

message GetStockLevelRequest {
  string warehouse_id = 1;
  string sku_id = 2;
  string as_of_datetime = 3;  // ISO8601, optional (current if empty)
}

message StockLevelResponse {
  string sku_id = 1;
  string warehouse_id = 2;
  double quantity_available = 3;
  double quantity_reserved = 4;
  double quantity_in_transit = 5;
  string unit_of_measure = 6;
  string updated_at = 7;
}
```

### 8.3 API Rate Limits

| Tier | Req/min (REST) | gRPC calls/min | Webhook events/min |
|------|---------------|-----------------|-------------------|
| Starter | 1,000 | 500 | 100 |
| Business | 10,000 | 5,000 | 1,000 |
| Enterprise | Unlimited | Unlimited | Unlimited |

---

## 9. Security Architecture

### 9.1 Identity & Access Management

```
User → OIDC Provider (Keycloak 24)
     → JWT Access Token (15 min TTL)
     → Refresh Token (30 days)
     → Kong validates JWT signature (JWKS)
     → Auth Service: RBAC check (role + resource + action)
     → Request forwarded to microservice
```

**RBAC Model:**  
- 5 built-in roles: `super_admin`, `tenant_admin`, `module_admin`, `operator`, `viewer`
- Custom roles via permission matrix (action × resource)
- Row-level security: users see only their tenant's data (tenant_id in all queries)

### 9.2 Secrets Management

All secrets are managed by HashiCorp Vault 1.16:
- Database credentials: rotated every 24 hours (dynamic secrets)
- API keys: stored as KV v2 secrets
- TLS certificates: generated by Vault PKI engine
- Kubernetes: secrets injected via Vault Agent sidecar

### 9.3 Network Security

- **mTLS everywhere**: Istio enforces mutual TLS for all pod-to-pod traffic
- **Network Policies**: Kubernetes NetworkPolicy restricts which pods can talk to which
- **Egress control**: all outbound traffic goes through a proxy (inspection + allowlist)
- **VPC isolation**: each environment (dev/staging/prod) in separate VPC

### 9.4 Data Security

- **Encryption at rest**: AES-256 for all databases (AWS KMS)
- **Encryption in transit**: TLS 1.3 minimum everywhere
- **PII masking**: sensitive fields (SSN, bank account) encrypted at field level using AES-GCM
- **Data classification**: automated tagging via doc-intelligence service

---

## 10. Infrastructure & Deployment

### 10.1 Kubernetes Cluster Layout

```
PRODUCTION CLUSTER (AWS us-east-1):
├── Node Pools:
│   ├── system-pool: 3× m6i.xlarge (4 vCPU, 16 GB) — system workloads
│   ├── app-pool: 24× m6i.2xlarge (8 vCPU, 32 GB) — business services
│   ├── data-pool: 12× r6i.4xlarge (16 vCPU, 128 GB) — DB, Kafka
│   ├── ml-pool: 6× g4dn.xlarge (4 vCPU, 16 GB, T4 GPU) — ML inference
│   └── spot-pool: 6× m6i.2xlarge (Spot) — batch jobs, workers
│
├── Namespaces:
│   ├── omnicore-system (Kong, Istio, cert-manager, ArgoCD)
│   ├── omnicore-finance (finance-core, budget, invoice, payroll)
│   ├── omnicore-operations (wms, manufacturing, supply-chain)
│   ├── omnicore-crm (crm, recruitment, performance)
│   ├── omnicore-ai (ai-engine, ml workers, Triton)
│   ├── omnicore-data (Kafka, ClickHouse, Elasticsearch, Redis)
│   └── omnicore-monitoring (Prometheus, Grafana, Jaeger, Loki)
```

### 10.2 CI/CD Pipeline

```
Developer pushes code to feature branch
  ↓
GitHub Actions CI:
  1. go vet + golangci-lint (< 2 min)
  2. Unit tests (go test -race, coverage report)
  3. Integration tests (docker-compose, real DB)
  4. Contract tests (Pact provider verification)
  5. Security scan (Trivy, Snyk, SonarQube)
  6. Docker build (multi-stage, distroless base)
  7. Image push to ECR
  8. Helm chart lint + dry-run
  (Total CI time target: < 8 minutes)
  ↓
Pull Request → 2 approvals required → Merge to main
  ↓
ArgoCD detects new image tag in Helm values (GitOps)
  ↓
Deploy to staging (automatic)
  ↓
Smoke tests + performance tests (k6)
  ↓
Manual approval → Deploy to production (blue/green)
  ↓
Canary: 5% → 25% → 100% traffic over 30 minutes
  ↓
Automatic rollback if error rate > 0.1% or P99 > 500ms
```

### 10.3 Resource Requests (Production)

| Service Type | CPU Request | CPU Limit | Mem Request | Mem Limit | Replicas |
|-------------|-------------|-----------|-------------|-----------|----------|
| Go service (typical) | 200m | 1000m | 128Mi | 512Mi | 2–4 |
| Python ML worker | 500m | 2000m | 512Mi | 2Gi | 2–3 |
| Java adapter | 500m | 2000m | 512Mi | 2Gi | 2–3 |
| Triton GPU server | 2000m | 4000m | 4Gi | 8Gi | 2 |
| ClickHouse node | 4000m | 8000m | 16Gi | 32Gi | 6 |
| Kafka broker | 2000m | 4000m | 8Gi | 16Gi | 5 |

---

## 11. ML Platform Architecture

### 11.1 ML Pipeline Overview

```
Data Sources (Kafka + PostgreSQL + ClickHouse)
  ↓
Feature Engineering (Feast feature store)
  ↓
Model Training (PyTorch + scikit-learn + XGBoost)
  → MLflow: experiment tracking, model registry, artifact store
  ↓
Model Validation (offline metrics: precision/recall/RMSE)
  ↓
A/B Testing Framework (gradual rollout, holdout groups)
  ↓
Model Serving:
  ├── Triton Inference Server (GPU, batch inference, ONNX)
  └── Python FastAPI (CPU, low-latency, real-time)
  ↓
Monitoring (data drift, model drift, latency, accuracy)
```

### 11.2 Production ML Models

| Model | Algorithm | Framework | Latency Target | Batch Size | Retrain Frequency |
|-------|-----------|-----------|----------------|------------|-------------------|
| Demand Forecasting | LSTM + Prophet | PyTorch | < 500ms | 1000 SKUs | Weekly |
| Churn Prediction | XGBoost | scikit-learn | < 50ms | Real-time | Monthly |
| Anomaly Detection | Isolation Forest | scikit-learn | < 20ms | Streaming | Weekly |
| Route Optimization | RL (PPO) | PyTorch | < 2s | Per request | Monthly |
| Document Classification | BERT-base | HuggingFace | < 200ms | 32 docs | Quarterly |
| Fraud Detection | GNN | PyTorch Geometric | < 100ms | Real-time | Weekly |
| AI Assistant | GPT-4o (API) | OpenAI SDK | < 3s | N/A | N/A |

### 11.3 LLM Integration

OmniCore AI Engine uses GPT-4o for natural language queries ("Show me all overdue invoices from last month"), document summarization, and anomaly explanations.

Local fallback: Llama 3 8B via Ollama (for air-gapped RU/KZ deployments where OpenAI API is unavailable).

---

## 12. Observability Stack

### 12.1 Three Pillars

**Metrics (Prometheus + Grafana)**  
Every service exposes `/metrics` endpoint. Key SLOs tracked:
- Request rate (RPS)
- Error rate (4xx, 5xx)
- Latency percentiles (P50, P95, P99)
- Saturation (CPU, memory, queue depth)

**Logging (Loki + Promtail)**  
- Structured JSON logs (zerolog for Go, structlog for Python)
- Log levels: ERROR, WARN, INFO (DEBUG disabled in prod)
- Correlation: every log line includes `trace_id`, `tenant_id`, `user_id`
- Retention: 30 days in Loki, 1 year in S3

**Tracing (Jaeger + OpenTelemetry)**  
- 100% sampling for errors, 5% for successful requests
- Trace propagation: W3C Trace Context headers
- Service dependency map auto-generated from trace data

### 12.2 Alerting Rules

| Alert | Condition | Severity | Action |
|-------|-----------|----------|--------|
| High error rate | error_rate > 1% for 5 min | Critical | PagerDuty (immediate) |
| API latency P99 | > 500ms for 5 min | Warning | Slack #oncall |
| Database connection pool saturation | > 90% for 2 min | Critical | PagerDuty |
| Kafka consumer lag | > 100,000 messages for 10 min | Warning | Slack |
| Disk usage | > 85% | Warning | Slack |
| Pod crash loop | > 3 restarts in 5 min | Critical | PagerDuty |

---

## 13. Performance & Scalability

### 13.1 Load Targets

| Scenario | Target |
|----------|--------|
| Concurrent users (Starter tier total) | 5,000 |
| Concurrent users (Business tier total) | 50,000 |
| Concurrent users (Enterprise single tenant) | 10,000 |
| Total platform concurrent users | 100,000 |
| API requests per second (steady state) | 50,000 RPS |
| API requests per second (peak, 3× load) | 150,000 RPS |
| Kafka events per second | 500,000 events/sec |
| ClickHouse analytical queries per second | 500 concurrent |
| Search queries per second (Elasticsearch) | 5,000 QPS |

### 13.2 Caching Strategy

| Layer | Technology | TTL | What's cached |
|-------|-----------|-----|---------------|
| CDN | CloudFront | 1 hour | Static assets, public API responses |
| API Gateway | Kong (Redis) | 60 seconds | Frequently-accessed read endpoints |
| Application | Redis | 5 minutes | User sessions, RBAC decisions, config |
| Database | PgBouncer | N/A | Connection pooling |
| Read models | Redis | 30 seconds | Dashboard KPI values |

### 13.3 Database Connection Limits

| Database | Max Connections | Per-Service Pool | PgBouncer Pool Mode |
|----------|----------------|------------------|---------------------|
| PostgreSQL (finance) | 300 | 20 | Transaction |
| PostgreSQL (wms) | 500 | 30 | Transaction |
| Redis (cache) | 10,000 | 50 | N/A |
| ClickHouse | 200 | 10 | N/A |

---

## 14. Disaster Recovery

### 14.1 Recovery Objectives

| Tier | RTO | RPO | Strategy |
|------|-----|-----|----------|
| Enterprise | 15 minutes | 5 minutes | Hot standby (multi-AZ) + async replication |
| Business | 1 hour | 30 minutes | Warm standby + point-in-time restore |
| Starter | 4 hours | 1 hour | Cold standby + daily backup restore |

### 14.2 Backup Strategy

- PostgreSQL: continuous WAL shipping to S3 + PITR up to 7 days; full dump weekly
- ClickHouse: incremental backup daily, full backup weekly (S3)
- Kafka: MirrorMaker 2 replication to standby cluster in separate AZ
- Redis: RDB snapshot every 1 hour, AOF for <= 1 min RPO
- Elasticsearch: snapshot to S3 every 6 hours
- S3 (object store): cross-region replication enabled

### 14.3 Runbook: Database Failover

1. Patroni auto-promotes standby (< 30 seconds, automated)
2. Kong updates upstream pool via Admin API
3. On-call notified via PagerDuty
4. Root cause analysis within 24 hours
5. Post-mortem published within 72 hours (blameless)

---

## 15. Migration Strategy

### 15.1 Customer Onboarding (from legacy ERP)

OmniCore provides a **Migration Toolkit** (open-source, MIT license):

```
Step 1: Discovery Phase (1 week)
  - Run omnicore-discover agent on customer's network
  - Auto-detect: SAP R/3, SAP S/4HANA, 1C:8.x, Oracle ERP, Dynamics 365
  - Generate compatibility report and migration complexity score

Step 2: Data Extraction (2–4 weeks)
  - ETL connectors for each source system
  - Incremental extraction (CDC for live systems)
  - Data quality report: duplicates, nulls, referential integrity

Step 3: Transformation & Validation (2–4 weeks)
  - Mapping source schema → OmniCore canonical data model
  - Automated validation rules + business rule checks
  - Reconciliation: source totals vs destination totals

Step 4: Parallel Run (4 weeks minimum)
  - Both old ERP and OmniCore running simultaneously
  - Daily comparison reports
  - Sign-off required from customer Finance Director

Step 5: Cutover (1 weekend)
  - Final delta sync
  - DNS switch
  - Legacy system kept in read-only mode for 90 days
```

### 15.2 Estimated Migration Timelines

| Source System | Data Volume | Migration Duration |
|--------------|-------------|-------------------|
| 1C:8.3 (small) | < 10 GB | 3 weeks |
| 1C:8.3 (large, 10+ years history) | 100+ GB | 8–12 weeks |
| SAP R/3 | 50–500 GB | 12–20 weeks |
| SAP S/4HANA | 100–1TB | 16–24 weeks |
| Custom legacy DB | Varies | Assessment required |

---

## 16. Open Questions & Conflicts

### 16.1 Architecture Decisions Pending

**ADR-001: Timeline Conflict**  
- Denis Krasnov (Architect): Full platform GA in November 2026 (22 months)
- Artур Жandarov (CEO): GA in July 2026 (18 months)  
- CTO Kirill Osipov: GA in August 2026 (20 months) — intermediate position
- **Status**: Escalated to board. Decision needed by 2025-03-01.

**ADR-002: Service Count**  
- Current design: 47 microservices  
- CTO wants to consolidate to 32 services (reduce operational overhead)  
- Chief Architect argues 47 is correct for domain boundaries  
- **Status**: Review scheduled for 2025-04-01.

**ADR-003: Frontend Architecture**  
- Option A: Single Next.js monorepo (recommended by Natalia Borisova)  
- Option B: Micro-frontend with Module Federation (proposed by external consultant)  
- **Status**: POC underway. Decision by 2025-03-15.

**ADR-004: AI Provider**  
- Production: GPT-4o (OpenAI API) — cost per query estimated $0.02–$0.05  
- Alternative: Self-hosted Llama 3 70B (one-time GPU cost $80,000/year in cloud)  
- **Status**: Cost/benefit analysis in progress.

### 16.2 Known Technical Debt (Planned)

1. **PayrollService (Java)**: Written in Java for legacy tax rule compatibility. Target: rewrite in Go within 18 months.
2. **integration-hub**: Uses RabbitMQ for legacy adapter queues. Target: migrate all to Kafka by Phase 2.
3. **SCADA adapter**: Currently Python-only, no failover. Target: add hot standby.
4. **Elasticsearch vs OpenSearch**: Running both increases operational cost. Consolidate to one by Q4 2025.
