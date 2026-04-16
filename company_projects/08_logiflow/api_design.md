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
