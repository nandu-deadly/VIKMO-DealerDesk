# VIKMO DealerDesk — Automotive Parts B2B Platform & AI Assistant

**Selected Track:** AI/ML Intern Track (All Mandatory & Optional Components Fully Completed)  
**Environment:** Python 3.11+ / 3.14, Django 5.2, PostgreSQL 18+  
**Status:** 100% Complete, Verified, Submission Ready & Hardened  

---

## 1. Project Overview

VIKMO DealerDesk is an enterprise B2B automotive spare parts procurement, inventory management, and AI intelligence platform designed for two-wheeler dealerships across India.

### Comprehensive Implemented Components

1. **Relational Data Layer & Core DRF APIs (Part A1)**:
   - **600 catalogue products**, **25 authorized dealers**, **600 live warehouse inventory records**.
   - **Idempotent data seeding** (`python manage.py seed_data`) preserving live warehouse stock across runs.
   - Exact error envelope compliance: `{"error": {"code": "...", "message": "...", "details": []}}`.
   - Comprehensive model validation, foreign key constraints, and clean migrations.

2. **Order Lifecycle & Concurrency Engine (Part A2)**:
   - Sequential, collision-free order numbering: `ORD-YYYYMMDD-NNNN`.
   - Statutory 18% GST calculation with strict `ROUND_HALF_UP` Decimal precision.
   - Full state machine: `DRAFT` -> `CONFIRMED` -> `DISPATCHED` -> `DELIVERED` / `CANCELLED`.
   - PostgreSQL row-level locking (`select_for_update`) to completely eliminate overselling under concurrent requests.
   - Stock is decremented on confirmation and safely restored upon cancellation.

3. **External Supplier Synchronization Service (Part B)**:
   - Resilient cursor-based pagination traversal following `next_cursor` until `null`.
   - Automatic retry mechanism with up to 5 attempts per page, respecting HTTP `429` `Retry-After` headers and exponential backoff on `5xx`.
   - Strict validation: rejects missing/empty `sku` or invalid `price` format, recording them in `rejected`.
   - Cross-page deduplication retaining the item version with the latest `updated_at`.
   - **All-or-nothing atomic transaction**: on outage or 401 error, changes nothing and raises `502 SUPPLIER_UNAVAILABLE`.
   - **Zero inventory mutation**: internal warehouse quantities remain untouched.
   - Exposed via endpoint `POST /api/sync/supplier/` and management command `python manage.py sync_supplier`.

4. **GenAI Dealer Assistant & Conversational Ordering (Part C)**:
   - **Multi-turn Conversational Order Workflow**: Complete 6-step ordering flow (Product Search -> Contextual Selection -> Order Agreement -> Stock-Validated Quantity Collection with 18% GST Financial Breakdown -> Confirmation -> DRAFT Order Placement & Reporting with duplicate prevention).
   - **Genuine Tool Execution**: Native LLM tool calling for search_parts, check_stock, and create_draft_order.
   - **Dynamic Catalogue Sizing**: Dynamic count calculation at runtime (Product.objects.count()) and count-independent catalogue responses (supporting supplier synchronization expansions).
   - **Cross-Dealer Session Isolation**: Multi-turn conversation persistence with strict dealer isolation preventing cross-dealer access (HTTP 403 FORBIDDEN).
   - **Draft-Order Safety**: Server-enforced dealer_id derivation, preventing dealer ID spoofing; orders are created as DRAFT with zero unconfirmed stock reservation.
   - **PostgreSQL Database Grounding**: Live catalogue pricing and inventory stock queries with zero price or stock hallucination.
   - **Anti-Prompt Injection Defense**: Untrusted supplier catalogue descriptions are treated strictly as data.
   - **Multi-Provider Support**: Google Gemini (gemini-2.5-flash), Groq (llama-3.3-70b-versatile), OpenAI (gpt-4o-mini), and a deterministic offline fallback. Live manual verification script provided in 	est_gemini_live.py.

5. **AI/ML Demand Forecasting & Dynamic Reordering (Part D)**:
   - Chronological rolling-origin backtesting (Weeks 97–100 and Weeks 101–104) with zero future data leakage.
   - Intermittent demand handling using Croston's Method with Syntetos-Boylan Approximation (SBA).
   - Lunar festival (Diwali) proximity adjustment and empirical per-SKU promotion response elasticity.
   - Generates [`ml/forecast.csv`](ml/forecast.csv) with exactly 160 rows (40 SKUs × 4 future weeks).
   - Dynamic live-stock reorder suggestions via `GET /api/reorder-suggestions/` and `GET /api/forecast/{sku}/`.

6. **Interactive Dashboards & VIKMO PartnerDesk Portals**:
   - **VIKMO PartnerDesk Login**: Modern centered login card with deep blue canvas, cyan accents, segmented Dealer | Distributor toggle buttons, and show/hide password control.
   - **Role-Based Portals**: Dedicated Dealer Dashboard (`/dealer/dashboard/`) and Distributor Operations Portal (`/distributor/dashboard/`).
   - Two-stage order approval: Dealer drafts orders; Distributor reviews pending queue, approves/confirms (which decrements inventory), dispatches, and delivers.
   - Single-page operational console served at `GET /` (`http://localhost:8000/`).

---

## 2. Prerequisites & Setup

### Prerequisites

- Python 3.11+ (tested on Python 3.14.3)
- PostgreSQL 14+ (tested on PostgreSQL 18.6)

### Environment Configuration

1. Copy `.env.example` to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Configure local PostgreSQL credentials and optional LLM keys in `.env`:
   ```dotenv
   DJANGO_DEBUG=1
   DJANGO_SECRET_KEY=replace-with-a-secure-random-secret-key-at-least-32-chars
   DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0,testserver
   DATABASE_URL=postgresql://user:password@127.0.0.1:5432/dealerdesk

   # Supplier Mock API (optional / local dev)
   SUPPLIER_API_URL=http://127.0.0.1:8099
   SUPPLIER_API_KEY=dev-supplier-key

   # LLM Provider Configuration (Gemini 2.5 Flash recommended; offline fallback active if unset)
   LLM_PROVIDER=gemini
   GEMINI_API_KEY=your_gemini_api_key_here
   GEMINI_MODEL=gemini-2.5-flash

   # Alternative Providers (optional):
   # GROQ_API_KEY=your_groq_api_key_here
   # GROQ_MODEL=llama-3.3-70b-versatile
   # OPENAI_API_KEY=your_openai_api_key_here
   # OPENAI_MODEL=gpt-4o-mini

   # Distributor Credentials for create_distributor command
   DISTRIBUTOR_USERNAME=distributor
   DISTRIBUTOR_PASSWORD=your_secure_distributor_password_here
   DISTRIBUTOR_EMAIL=distributor@vikmo.internal
   ```

### Installation & Database Initialization

```bash
# 1. Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate       # On Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. System checks & migrations
python manage.py check
python manage.py migrate --noinput

# 4. Seed database (idempotent; run twice to verify 600 catalogue products, 25 dealers, 600 inventory)
python manage.py seed_data
python manage.py seed_data

# 5. Create Distributor account (secure prompt or via DISTRIBUTOR_PASSWORD env var)
python manage.py create_distributor --username distributor
# Or via environment variable:
# DISTRIBUTOR_PASSWORD="YourSecurePassword123!" python manage.py create_distributor --username distributor
```

### Separate Authentication Portals & Credentials

The platform enforces Role-Based Access Control (RBAC) with independent login portals:

1. **Dealer Portal**:
   - **Login URL**: `http://127.0.0.1:8000/dealer/login/`
   - **Dashboard**: `http://127.0.0.1:8000/dealer/dashboard/`
   - **Default Accounts**: Seeded dealers `DLR-001` through `DLR-025` with password `Dealer@<dealer_code>` (e.g., `Dealer@DLR-001`).
   - **Capabilities**: View dealer catalogue, live stock, submit draft orders, track order history.

2. **Distributor Portal**:
   - **Login URL**: `http://127.0.0.1:8000/distributor/login/`
   - **Dashboard**: `http://127.0.0.1:8000/distributor/dashboard/`
   - **Account**: Created via `python manage.py create_distributor`.
   - **Capabilities**: Review pending dealer draft orders, approve/confirm orders, dispatch, and mark delivered.

3. **Strict Order Security & Authorization (RBAC)**:
   - Order confirmation endpoints (`/api/orders/<order_number>/confirm/`, `/api/distributor/orders/<order_number>/confirm/`) require authentication.
   - **Unauthenticated requests** receive `HTTP 401 UNAUTHORIZED`.
   - **Authenticated dealers** receive `HTTP 403 FORBIDDEN`.
   - **Only authenticated Distributors** can confirm orders (`HTTP 200 OK`).


---

## 3. Running the Platform

### Start Development Server & UI Dashboard

```bash
python manage.py runserver 127.0.0.1:8000
```
- Open **http://127.0.0.1:8000/** in your browser to access the full interactive Operations & AI Intelligence Dashboard.

### Start Supplier Mock Service (Optional / Dev)

In a separate terminal, launch the mock supplier service:
```bash
python supplier_mock/mock_supplier.py --port 8099 --key dev-supplier-key
```

### Core API Routes & Examples

- **Operations Dashboard**:
  `GET http://127.0.0.1:8000/`
- **Health Check**:
  `GET http://127.0.0.1:8000/api/health/`
- **Product Catalogue**:
  `GET http://127.0.0.1:8000/api/products/?category=Brakes&page_size=10`
- **Warehouse Inventory Update**:
  `PUT http://127.0.0.1:8000/api/inventory/BRK-1044/` with `{"quantity": 50, "reason": "Restocked"}`
- **Create Draft Order**:
  `POST http://127.0.0.1:8000/api/orders/` with `{"dealer_id": 1, "items": [{"sku": "BRK-1044", "quantity": 2}]}`
- **Confirm Order**:
  `POST http://127.0.0.1:8000/api/orders/ORD-YYYYMMDD-NNNN/confirm/`
- **Cancel Order**:
  `POST http://127.0.0.1:8000/api/orders/ORD-YYYYMMDD-NNNN/cancel/`
- **Supplier Sync Endpoint**:
  `POST http://127.0.0.1:8000/api/sync/supplier/`
- **Supplier Sync Management Command**:
  `python manage.py sync_supplier`
- **AI/ML Forecast Detail**:
  `GET http://127.0.0.1:8000/api/forecast/BRK-1044/`
- **Live Reorder Suggestions**:
  `GET http://127.0.0.1:8000/api/reorder-suggestions/`
- **GenAI Dealer Assistant Chat**:
  `POST http://127.0.0.1:8000/api/assistant/chat/` with `{"session_id": "sess-1", "dealer_id": 1, "message": "Do you have brake pads for a Pulsar 150?"}`

---

## 4. AI/ML Forecasting Pipeline

Run the machine learning backtesting and forecast generation:

```bash
python ml/train_forecast.py
```

- Evaluates 3 baselines (Naive, 4-Week Moving Average, Same-Week-Last-Year) across 2 backtesting folds.
- Adaptive Model achieves up to **8.54% error reduction** over the best baseline.
- Generates authoritative [`ml/forecast.csv`](ml/forecast.csv) with exactly 160 rows (40 SKUs × 4 forecast weeks).

---

## 5. Verification & Testing

### Automated Unit Test Suite

```bash
python manage.py test core.tests --keepdb
```
- **113 tests executed, 113 passed (100% pass rate)**.
- Covers:
  - Database schema constraints, inventory relations, and idempotent seeding.
  - Financial Decimal precision and 18% GST calculation.
  - Concurrency safety and row-level locking (`select_for_update`).
  - Order state machine transitions (Draft -> Confirm -> Dispatch -> Deliver / Cancel).
  - RBAC security: Dealer vs Distributor authentication, anonymous 401 rejection, dealer 403 rejection.
  - Idempotent distributor account management and credential preservation.
  - Supplier sync pagination, 5-retry limit, 429 `Retry-After`, deduplication, and atomic rollback.
  - **Hybrid RAG Assistant Retrieval Engine**: Multi-signal scoring, spelling variations & typos (`tubless tyre`, `break pads`), singular/plural normalization, automotive synonyms, vehicle fitment precision (`confirmed` vs `universal` vs `incompatible`), non-catalogue vehicle rejection (e.g. Activa), ambiguous order clarification, and zero-hallucination guarantees.
  - Assistant agent tool dispatch, memory persistence, and anti-injection defenses.
  - Frontend dashboard and portal template rendering.


### Comprehensive Smoke Test Suite

```bash
# In Terminal 1 (Mock Supplier):
python supplier_mock/mock_supplier.py --port 8099 --key dev-supplier-key

# In Terminal 2 (Django Server):
python manage.py runserver 127.0.0.1:8000

# In Terminal 3 (Run all smoke tests):
python smoke_test.py --base-url http://127.0.0.1:8000 --all
```
- **12 / 12 checks passed (100%)**:
  - `GET /api/health/` [PASS]
  - `GET /api/products/` [PASS]
  - `GET /api/products/{sku}/` and 404 shape [PASS]
  - `Dealers: list and create` [PASS]
  - `PUT /api/inventory/{sku}/` [PASS]
  - `POST /api/orders/` creates DRAFT [PASS]
  - `Validation error shape` [PASS]
  - `Order engine confirm/cancel/invalid transition` [PASS]
  - `POST /api/sync/supplier/` [PASS]
  - `POST /api/assistant/chat/` [PASS]
  - `ml/forecast.csv validation` [PASS]
  - `GET /api/forecast/{sku}/` and `/api/reorder-suggestions/` [PASS]

---

## 6. Security Hardening

- **Secrets Handling**: Zero credentials, API keys, or database passwords hardcoded in repository files.
- **Error Sanitization**: Custom exception handler redacts credentials and tokens.
- **Database Safety**: Strictly restricted to PostgreSQL; SQLite fallback disabled.
- **Prompt Fencing**: Untrusted catalogue descriptions and user inputs are fenced with boundary markers.
- **Distribution Hygiene**: Caches (`__pycache__`), `.venv`, `.env`, and temporary files are strictly ignored and excluded from releases.

---

## 7. Assumptions & Technical Considerations

1. **Database & Persistence**:
   - The production datastore is strictly PostgreSQL 14+; connection parameters are read exclusively from the `DATABASE_URL` environment variable.
   - Initial catalogue and dealer counts are 600 and 25 respectively. Running `seed_data` multiple times idempotently preserves live stock changes while pruning synthetic mock items.
2. **AI Assistant Grounding & Providers**:
   - Primary LLM provider is Google Gemini (`gemini-2.5-flash`), with transparent fallback to OpenAI/Groq or an offline deterministic PostgreSQL-grounded engine if API keys are omitted or rate-limited.
   - The assistant only creates `DRAFT` orders and has no permission to confirm orders or bypass approval hierarchies.
3. **Forecasting & Demand**:
   - Weekly demand follows four-week operational horizons. Sales data in `sales_history.csv` reflects weekly aggregated demand.
   - Intermittent SKUs (demand with >40% zero sales weeks) are modeled using Croston's SBA method to avoid positive bias.
   - Lead time demand uses the sum of forecasts over the lead time weeks `L` specified in `data/lead_times.csv`.
4. **GST & Currency**:
   - Statutory 18% GST is computed per line using Python's `Decimal` with `ROUND_HALF_UP` rounding to the nearest paisa.

---

## 8. Repository & Demonstration Links

- **Public GitHub Repository:** https://github.com/nandu-deadly/VIKMO-DealerDesk
- **5-Minute Video Walkthrough:** https://youtu.be/gvwejo2sw00?si=22ygByQSYBrONH1y
