# VIKMO DealerDesk — Final Submission Audit (AI/ML Track)

**Audit Date:** 2026-10-13  
**Selected Track:** AI/ML Intern Track  
**Environment:** Python 3.14.3, Django 5.2.18, PostgreSQL 18.6, Psycopg 3.3.6  
**Final Status:** **100% PASS — SUBMISSION READY**

---

## 1. Requirement Compliance Matrix (AI/ML Track)

| Requirement | Contract Section | Implementation Location | Verification Method | Actual Result | Status |
|---|---|---|---|---|---|
| **PostgreSQL Database & Engine** | §1, §2 | [`dealerdesk/settings.py`](dealerdesk/settings.py#L65-L75) | `python manage.py check` & DB inspection | Strictly requires `django.db.backends.postgresql`, rejects SQLite | **PASS** |
| **Product, Inventory & Dealer Models** | §4, §5, §6 | [`core/models.py`](core/models.py#L15-L88) | Unit tests in `test_models_and_seeding.py` | Validated field types, `DecimalField(12, 2)`, constraints, `CASCADE`/`PROTECT` | **PASS** |
| **Idempotent Data Seeding** | §1, §4, §6 | [`core/management/commands/seed_data.py`](core/management/commands/seed_data.py) | Run seed twice on clean & dev DB | Exactly 600 catalogue products, 25 dealers loaded idempotently; live warehouse stock preserved | **PASS** |
| **Product Catalog REST APIs** | §4 | [`core/views.py`](core/views.py#L140-L195), [`core/serializers.py`](core/serializers.py) | `GET /api/products/`, `POST`, `GET /api/products/{sku}/`, `PATCH` | Proper pagination, filters (`search`, `category`, `vehicle`), 404 error shape, zero initial stock on POST | **PASS** |
| **Inventory Management API** | §5 | [`core/views.py`](core/views.py#L197-L216) | `PUT /api/inventory/{sku}/` | Non-negative integer validation, exact `{sku, quantity}` response format | **PASS** |
| **Dealer Management APIs** | §6 | [`core/views.py`](core/views.py#L218-L247) | `GET /api/dealers/`, `POST`, `GET /api/dealers/{id}/` | Unique `dealer_code`, GSTIN validation, pagination, 409 on duplicate | **PASS** |
| **Draft Order Engine** | §7.1 | [`core/order_service.py`](core/order_service.py), [`core/views.py`](core/views.py#L249-L290) | `POST /api/orders/`, `GET /api/orders/` | Orders created in `DRAFT` status; `ORD-YYYYMMDD-NNNN` sequential numbering; current catalogue prices used; warehouse stock untouched | **PASS** |
| **Order Idempotency** | §7.5 | [`core/order_service.py`](core/order_service.py#L39-L49), [`core/models.py`](core/models.py#L152-L163) | Unit test `test_order_idempotency_key` | Same key + body returns existing order; same key + different body raises 409 conflict | **PASS** |
| **GenAI Dealer Assistant** | §9 | [`core/assistant/agent.py`](core/assistant/agent.py), [`core/assistant/tools.py`](core/assistant/tools.py) | `POST /api/assistant/chat/` | Strict schema (`reply`, `cited_skus`, `tool_calls`, `actions`); multi-turn session memory; anti-injection prompt fencing | **PASS** |
| **Assistant Tool Calling** | §9 | [`core/assistant/tools.py`](core/assistant/tools.py) | Unit tests in `test_assistant.py` | Dispatches `search_parts`, `check_stock`, `create_draft_order`; orders stay `DRAFT`; zero stock decrement; live DB pricing | **PASS** |
| **Demand Forecasting Pipeline** | §10.1 | [`ml/train_forecast.py`](ml/train_forecast.py) | `python ml/train_forecast.py` | Rolling-origin backtest against 3 baselines; out-of-fold MAE and WAPE evaluated without data leakage | **PASS** |
| **Committed Forecast Artifact** | §10.1 | [`ml/forecast.csv`](ml/forecast.csv) | `smoke_test.py` & row validator | Exactly 160 rows, 40 SKUs × 4 required weeks (`2026-09-28`, `2026-10-05`, `2026-10-12`, `2026-10-19`) | **PASS** |
| **Forecast Retrieval Endpoint** | §10.2 | [`core/views.py`](core/views.py), [`core/forecasting_service.py`](core/forecasting_service.py) | `GET /api/forecast/{sku}/` | Returns 4 forecast weeks matching `ml/forecast.csv`; 404 on unknown SKU | **PASS** |
| **Reorder Engine Endpoint** | §10.2 | [`core/views.py`](core/views.py), [`core/forecasting_service.py`](core/forecasting_service.py) | `GET /api/reorder-suggestions/` | Exactly 40 forecast SKUs; dynamic recalculation using live inventory; exact formulas for $\sigma$, safety stock, and reorder point | **PASS** |
| **Official Smoke Test (AI/ML)** | All | [`smoke_test.py`](smoke_test.py) | `python smoke_test.py --track aiml` | **10/10 checks PASS (100%)** | **PASS** |
| **Official Smoke Test (All)** | All | [`smoke_test.py`](smoke_test.py) | `python smoke_test.py --all` | **12/12 checks PASS (100%)** | **PASS** |

---

## 2. Regression & Security Audit Findings

1. **Cross-Dealer & Cross-Session Isolation**:
   - `SessionManager` stores session turns strictly keyed by `session_id` in `AssistantMessage`. Sessions never share history.
   - Orders created by assistant strictly use the request body `dealer_id`.
2. **Hallucination Prevention**:
   - Stock and pricing are retrieved via direct PostgreSQL queries in real time.
   - `extract_cited_skus` filters reply text against existing SKUs in PostgreSQL, eliminating fabricated SKU citations.
3. **Anti-Prompt Injection**:
   - System prompt instructs model that catalogue descriptions and part names are inert third-party data, never operational instructions.
   - Off-topic queries (e.g. poetry, weather, generic chats) are politely declined.
4. **Order Idempotency**:
   - Reusing idempotency keys with matching payload safely returns the existing order; mismatched payloads raise `409 IDEMPOTENCY_CONFLICT`.
5. **Inventory Safety**:
   - Draft orders never decrement inventory in either REST API or assistant tool calling. Stock decreases only upon order confirmation.
6. **Authentication & RBAC**:
   - Order confirmation endpoints strictly require authentication. Anonymous requests receive `HTTP 401 UNAUTHORIZED`. Dealers receive `HTTP 403 FORBIDDEN`. Only authenticated Distributors can confirm orders.

---

## 3. Environment & Compatibility Audit

- **Python Version**: Python 3.11+ (tested on Python 3.14.3).
- **Operating Systems**: Tested on Windows, verified clean path and package separation for Linux deployments.
- **Dependencies**: Listed in `requirements.txt` with standard bounds.
- **Secrets Management**: Zero API keys or credentials committed; all configurations sourced from environment variables; `.env.example` committed with safe placeholders.
