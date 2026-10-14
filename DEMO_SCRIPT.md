# VIKMO DealerDesk — 5-Minute Comprehensive Demo Script

This script is structured for a concise, compelling 5-minute walkthrough demonstrating the complete platform: PostgreSQL core, Order Lifecycle, Supplier Synchronization, AI/ML Demand Forecasting, Grounded GenAI Assistant, and the Operations Frontend Dashboard.

---

## 0:00 - 0:45 | Architecture & Database Foundation

**Objective:** Demonstrate PostgreSQL configuration, migration stability, idempotent data seeding, and test suite verification.

```bash
# 1. Verify Django configuration and migrations
python manage.py check

# 2. Run automated test suite (85 tests covering all modules)
python manage.py test core.tests --keepdb
```
- **Speaking Points:**
  - *"VIKMO DealerDesk is an enterprise B2B spare parts platform built with Django 5 and PostgreSQL."*
  - *"Our seed command is strictly idempotent: repeatedly running it maintains 600 catalogue products and 25 dealers without overriding warehouse inventory modifications."*
  - *"Our test suite has 85 automated tests covering concurrency row locks, financial precision, order lifecycles, RBAC security, supplier sync, assistant tools, forecasting, and frontend rendering."*

---

## 0:45 - 1:45 | Interactive Frontend Dashboard & Order Engine

**Objective:** Showcase the modern Operations Dashboard (`http://localhost:8000/`) and the full order lifecycle.

```bash
# Open http://localhost:8000/ in browser
```
- **Speaking Points:**
  - *"We provide an interactive Operations & AI Intelligence Dashboard serving live operational tools in a unified UI."*
  - *"Let's explore the Catalogue tab: live search across 600 parts, filtering by vehicle fitment and category."*
  - *"In the Orders tab: we create a draft order for Dealer 1 with SKU `BRK-1044`."*
  - *"Notice the exact financial calculations: 18% statutory GST rounded via `ROUND_HALF_UP`."*
  - *"When we confirm the order, the system locks the inventory row with `select_for_update`, ensuring zero overselling even under concurrent dealer requests. On cancellation, inventory is automatically restored."*

---

## 1:45 - 2:45 | Supplier Synchronization Service

**Objective:** Demonstrate paginated sync with retry resilience and zero inventory disruption.

```bash
# In Dashboard: Navigate to 'Supplier Sync' tab and click 'Trigger Full Supplier Sync'
# Or from CLI:
python manage.py sync_supplier
```
- **Speaking Points:**
  - *"Our supplier sync service connects to external supplier feeds via cursor pagination."*
  - *"It handles rate limits (HTTP 429) using `Retry-After` headers and transient `5xx` errors with exponential backoff, up to 5 retries per request."*
  - *"It rejects invalid prices or missing SKUs, deduplicates items across pages by latest `updated_at`, and updates product pricing atomically in PostgreSQL while keeping our local warehouse quantities untouched."*

---

## 2:45 - 3:45 | AI/ML Demand Forecasting & Dynamic Reordering

**Objective:** Demonstrate machine learning forecasting backtesting and real-time inventory-driven reorder suggestions.

```bash
# Run ML backtest pipeline
python ml/train_forecast.py

# Query live reorder suggestions API
curl -s http://127.0.0.1:8000/api/reorder-suggestions/ | jq '.results[0]'
```
- **Speaking Points:**
  - *"Our forecasting pipeline uses chronological rolling-origin backtesting without future data leakage."*
  - *"We evaluated 3 baselines against our adaptive model. The adaptive model achieved an 8.54% error reduction in WAPE by accounting for promotion lifts, lunar calendar shifts (Diwali), and intermittent demand via Croston's SBA method."*
  - *"The live reorder engine dynamically combines 12-week lead-time demand, standard deviation safety stock, and live warehouse inventory to advise dealers on exact replenishment quantities."*

---

## 3:45 - 4:30 | Grounded GenAI Dealer Assistant

**Objective:** Demonstrate multi-turn conversation, real-time tool calling, anti-injection safety, and draft order creation.

```bash
# In Dashboard: Navigate to 'AI Assistant' tab, or test via CLI:
curl -s -X POST http://127.0.0.1:8000/api/assistant/chat/ \
  -H "Content-Type: application/json" \
  -d '{"session_id": "demo-sess-1", "dealer_id": 1, "message": "Do you have brake pads for a Pulsar 150?"}' | jq
```
- **Speaking Points:**
  - *"Our dealer assistant uses tool calling (`search_parts`, `check_stock`, `create_draft_order`) directly connected to PostgreSQL."*
  - *"It cannot hallucinate prices or stock levels because all numbers come from database tool outputs."*
  - *"Supplier catalogue text is strictly fenced to neutralize prompt injection attacks."*
  - *"Dealers can order parts via conversational natural language, and the assistant creates a validated DRAFT order directly into the database."*

---

## 4:30 - 5:00 | Official Smoke Test Verification & Wrap-up

**Objective:** Conclude with the official smoke test covering all components.

```bash
python smoke_test.py --base-url http://127.0.0.1:8000 --all
```
- **Output:**
  - **12/12 checks passed (100%)**
- **Conclusion:**
  - *"All components across both the Django Full Stack Track and the AI/ML Intern Track are fully implemented, verified, hardened, and ready for deployment."*
