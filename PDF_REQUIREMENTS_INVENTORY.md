# VIKMO DealerDesk — PDF Requirements Inventory

**Document Reference:** `VIKMO_DealerDesk_Assignment.pdf` (Pages 1–8) & `API_CONTRACT.md` (Sections 1–10)  
**Project:** VIKMO DealerDesk  
**Tracks:** Python / Django Intern Track & AI / ML Intern Track  

---

## 1. Overview & Track Matrix

The assignment defines five major functional parts and one frontend portal, with distinct requirements based on the candidate's track:

| Part | Component | Django Track | AI / ML Track | Scoring Weight (Django) | Scoring Weight (AI/ML) |
|---|---|:---:|:---:|:---:|:---:|
| **A1** | **Backend Core** (Products, Inventory, Dealers, Draft Orders) | **Required** | **Required** | Part of 40 pts | 10 pts (Core only) |
| **A2** | **Order Engine** (Status flow, Concurrency, GST, Order numbers, Idempotency) | **Required** | **Optional** (Bonus) | Part of 40 pts | Bonus (up to 5 pts) |
| **B** | **Supplier Synchronization** (Cursor pagination, Rate-limiting, Retries, Deduplication) | **Required** | **Optional** (Bonus) | 15 pts | Bonus (up to 5 pts) |
| **C** | **Dealer Assistant (GenAI)** (LLM tool-calling, PostgreSQL grounding, Anti-injection) | **Optional** (Bonus) | **Required** | Bonus (up to 5 pts) | 35 pts |
| **D** | **Forecasting and Reordering (ML)** (160-row forecast, Rolling-origin backtest, Dynamic ROP) | **Optional** (Bonus) | **Required** | Bonus (up to 5 pts) | 25 pts |
| **E** | **Frontend** (Dealer portal with catalogue, live stock, ordering, chat, reorder) | **Optional** (Bonus) | **Optional** (Bonus) | Bonus (up to 5 pts) | Bonus (up to 5 pts) |

*Additional Score Breakdown:*
- **Code quality and tests:** 20 pts (Django) / 10 pts (AI/ML)
- **DECISIONS.md (8 track questions answered with file:line citations):** 15 pts (Django) / 15 pts (AI/ML)
- **5-Minute Video Walkthrough:** 10 pts (Django) / 5 pts (AI/ML)
- **Total Base Score:** 100 pts. Bonus capped at 10 pts total. Bonus only counts if required parts score $\ge 60\%$. Minimum bar: scoring $< 30\%$ on any required part flags submission.

---

## 2. Comprehensive Requirements Inventory

### Category 1: Backend Core (Part A1) — Required for Both Tracks
* **REQ-A1-01 (Data Models):** Implement at minimum `Product`, `Inventory`, `Dealer`, `Order`, and `OrderItem` models. Fields, types, relationships, constraints, indexes, and `on_delete` behaviors must be chosen and justified in `DECISIONS.md`. [PDF p.2 §4; Contract §4–§7]
* **REQ-A1-02 (PostgreSQL Exclusivity):** PostgreSQL is mandatory (`DATABASE_URL`). SQLite is strictly rejected because concurrency rules cannot be tested on it. [PDF p.4 §9; Contract §1]
* **REQ-A1-03 (Product Catalogue API):** `GET /api/products/` with pagination (`page`, `page_size` 1–100, default 20), case-insensitive search (`sku`, `name`, `brand`), exact `category`, and substring `vehicle` (vehicle_fitment) filters. [PDF p.2 §4; Contract §4]
* **REQ-A1-04 (Product Creation & Lookup):** `POST /api/products/` creates product with stock 0 (`201`), duplicate SKU yields `409 DUPLICATE`, price must be $>0$ with $\le 2$ decimals else `400 VALIDATION_ERROR`. `GET /api/products/{sku}/` returns product or `404 NOT_FOUND`. `PATCH /api/products/{sku}/` updates fields without changing SKU. [Contract §4]
* **REQ-A1-05 (Inventory Management API):** `PUT /api/inventory/{sku}/` with `{"quantity": int >= 0, "reason": str}` updates warehouse stock. Unknown SKU yields `404 NOT_FOUND`. Manual updates do not alter existing orders. [PDF p.2 §4; Contract §5]
* **REQ-A1-06 (Dealer APIs):** `GET /api/dealers/` (paginated list), `POST /api/dealers/` (requires `dealer_code` and `name`, returns `201`, duplicate yields `409 DUPLICATE`), `GET /api/dealers/{id}/` returns dealer or `404 NOT_FOUND`. [Contract §6]
* **REQ-A1-07 (Draft Order Creation & Validation):** `POST /api/orders/` creates a `DRAFT` order (`201`). Requires at least one item, `quantity` integer $\ge 1$, valid SKUs, no duplicate SKUs within request, valid dealer. Otherwise returns `400 VALIDATION_ERROR`. Line items capture current catalogue `unit_price`. [PDF p.2 §4; Contract §7.1]
* **REQ-A1-08 (Order Listing & Retrieval):** `GET /api/orders/` (paginated list with `dealer_id` and `status` filters), `GET /api/orders/{order_number}/` returns order or `404 NOT_FOUND`. [Contract §7.1]
* **REQ-A1-09 (Standard Error Envelope):** All errors return JSON shape `{"error": {"code": "...", "message": "...", "details": [...]}}` with exact HTTP status codes and contract error codes. [PDF p.2 §4; Contract §3]
* **REQ-A1-10 (Health Endpoint):** `GET /api/health/` returns `200 {"status": "ok"}` without authentication. [PDF p.5 §9.1; Contract §1]

---

### Category 2: Order Engine (Part A2) — Required for Django, Optional for AI/ML
* **REQ-A2-01 (Order State Machine):** Enforce strict lifecycle: `DRAFT` $\rightarrow$ `CONFIRMED` $\rightarrow$ `DISPATCHED` $\rightarrow$ `DELIVERED`. Only `DRAFT` or `CONFIRMED` can transition to `CANCELLED`. Editing (`PUT /api/orders/{order_number}/`) is allowed only in `DRAFT`. All other transitions return `409 INVALID_TRANSITION` or `409 ORDER_LOCKED`. [PDF p.2 §4; Contract §7.2]
* **REQ-A2-02 (Stock Reservation & All-or-Nothing Confirmation):** DRAFT orders have zero effect on inventory stock. `POST /api/orders/{order_number}/confirm/` validates stock for every line item. If any line exceeds stock, zero stock changes occur, returning `409 INSUFFICIENT_STOCK` with `details` containing every short line and `message` stating available vs requested. [PDF p.3 §4; Contract §7.3]
* **REQ-A2-03 (Stock Restoration on Cancellation):** Cancelling a `CONFIRMED` order restores its line item quantities to inventory stock exactly once. Cancelling a `DRAFT` order modifies no stock. `DISPATCHED` and `DELIVERED` orders cannot be cancelled. [PDF p.3 §4; Contract §7.3]
* **REQ-A2-04 (Concurrency & Zero Overselling):** Concurrent order confirmations for remaining units must never oversell stock below 0, protected via PostgreSQL row-level locks (`select_for_update`) and atomic transactions. [PDF p.3 §4; Contract §7.3]
* **REQ-A2-05 (18% Statutory GST & Decimal Precision):** `line_subtotal = unit_price * quantity`. `line_tax = line_subtotal * 0.18`, rounded per line using `ROUND_HALF_UP` to the paisa. `line_total = line_subtotal + line_tax`. `subtotal = sum(line_subtotal)`, `tax_total = sum(line_tax)`, `grand_total = subtotal + tax_total`. All monetary values formatted as 2-decimal strings (`DecimalField(12, 2)`), never binary floats. [PDF p.3 §4; Contract §7.4]
* **REQ-A2-06 (Price Locking):** While DRAFT, order lines reflect current catalogue price. Upon confirmation, `unit_price` is permanently locked and never altered by subsequent catalogue changes. [PDF p.3 §4; Contract §7.4]
* **REQ-A2-07 (Sequential Collision-Free Order Numbers):** Format `ORD-YYYYMMDD-NNNN` where date is in Asia/Kolkata (IST) timezone and `NNNN` is a zero-padded daily sequence starting at `0001`. Guaranteed unique under concurrent creation. [PDF p.3 §4; Contract §7.5]
* **REQ-A2-08 (Idempotency Key):** Optional `Idempotency-Key` header on `POST /api/orders/`. Duplicate key with identical body returns the existing order (`200` or `201`) without creating a new order, even under concurrent requests. Reusing the same key with a different body returns `409 IDEMPOTENCY_CONFLICT`. [PDF p.3 §4; Contract §7.5]

---

### Category 3: Supplier Synchronization (Part B) — Required for Django, Optional for AI/ML
* **REQ-B-01 (Supplier Sync Endpoint):** `POST /api/sync/supplier/` (no body) executes one full synchronization and returns within 120 seconds. [PDF p.3 §5; Contract §8.2]
* **REQ-B-02 (Cursor-Based Pagination Traversal):** Traverses supplier API (`GET {SUPPLIER_API_URL}/v1/products?cursor=<cursor>&limit=<n>`, `X-Api-Key`), following `next_cursor` until it is `null`. Never skips a page. [PDF p.3 §5; Contract §8.1, §8.3]
* **REQ-B-03 (Retry Logic & Rate Limit Resilience):** On HTTP 429, waits for duration specified in `Retry-After` header before retrying. On 5xx or connection error, retries with exponential backoff. Each request is attempted at most 5 times. [PDF p.3 §5; Contract §8.3]
* **REQ-B-04 (Atomic All-or-Nothing Transaction on Failure):** If any request fails after 5 attempts or API key is rejected (401), zero changes are committed to the database, returning `502 SUPPLIER_UNAVAILABLE`. [PDF p.3 §5; Contract §8.3]
* **REQ-B-05 (Invalid Item Handling):** Items with missing/empty `sku` or invalid price (not a positive decimal with $\le 2$ decimal places) are skipped and reported in the `rejected` response array, without failing the overall sync. [PDF p.3 §5; Contract §8.3]
* **REQ-B-06 (Duplicate SKU Deduplication):** Cross-page duplicate SKUs are resolved by retaining the entry with the latest `updated_at`. [PDF p.3 §5; Contract §8.3]
* **REQ-B-07 (Database Application Rules):** New SKUs are created with stock 0 (`created`). Existing SKUs with differing fields are updated (`updated`). Unmodified SKUs count as `unchanged`. Local warehouse stock is never modified (`supplier_stock` is supplier's stock). [PDF p.3 §5; Contract §8.3]
* **REQ-B-08 (Sync Idempotency):** Running sync a second time on an unchanged feed returns `created: 0, updated: 0` and changes nothing in the database. [PDF p.3 §5; Contract §8.3]
* **REQ-B-09 (Management Command):** Supplier sync must also be runnable from CLI: `python manage.py sync_supplier`. [PDF p.3 §5; Contract §8]

---

### Category 4: Dealer Assistant / GenAI (Part C) — Required for AI/ML, Optional for Django
* **REQ-C-01 (Chat Endpoint):** `POST /api/assistant/chat/` accepts `session_id`, `dealer_id`, and `message`. [PDF p.3 §6; Contract §9]
* **REQ-C-02 (LLM Provider & Tool Calling):** Integrates an approved LLM provider (Google Gemini, OpenAI, Anthropic, or Groq) with authentic tool calling. Provider key read strictly from environment variable (`GEMINI_API_KEY`, etc.). Provider and model documented in `README.md`. [PDF p.3 §6; Contract §9]
* **REQ-C-03 (Exact Tools Dispatched):** The LLM itself decides and dispatches tools: `search_parts`, `check_stock`, and `create_draft_order`. All dispatched tools reported in `tool_calls`. [PDF p.3 §6; Contract §9]
* **REQ-C-04 (PostgreSQL Grounding & Zero Hallucination):** Every price and stock figure cited in `reply` must originate from the PostgreSQL database at request time. [PDF p.3 §6; Contract §9]
* **REQ-C-05 (Draft-Only Orders):** Assistant may only create `DRAFT` orders adhering to identical business rules as `POST /api/orders/`. It must never confirm orders. Creating an order emits an action `{"type": "draft_order_created", "order_number": "ORD-..."}` in `actions`. [PDF p.3 §6; Contract §9]
* **REQ-C-06 (Multi-Turn Session Memory & Isolation):** Conversation context maintained across turns using `session_id`. Different sessions and dealers must remain isolated. [PDF p.4 §6; Contract §9]
* **REQ-C-07 (Clarification on Ambiguity):** Clarifies ambiguous queries (e.g. asking for brake pads without vehicle fitment). [PDF p.4 §6]
* **REQ-C-08 (Anti-Prompt Injection Defense):** Supplier catalogue descriptions are untrusted data. The assistant must never follow adversarial instructions embedded inside catalogue text. Off-topic queries are politely declined. [PDF p.4 §6; Contract §9]
* **REQ-C-09 (Deterministic Offline Fallback):** When external API keys or connectivity are unavailable, the assistant falls back to a deterministic PostgreSQL-grounded handler without crashing. [Contract §9]
* **REQ-C-10 (Response SLA):** Each chat turn must respond within 60 seconds. [Contract §9]

---

### Category 5: Demand Forecasting & Dynamic Reorder (Part D) — Required for AI/ML, Optional for Django
* **REQ-D-01 (Forecast Scope & Artifact):** Forecast weekly `units_sold` for the 40 SKUs in `data/lead_times.csv` across four future weeks starting `2026-09-28` (`2026-09-28`, `2026-10-05`, `2026-10-12`, `2026-10-19`). Committed as `ml/forecast.csv` with exactly 160 rows and columns `sku,week_start,forecast_units`. [PDF p.4 §7; Contract §10.1]
* **REQ-D-02 (Historical Rolling-Origin Backtesting):** Evaluated strictly on historical data without future data leakage (`week_start < test_weeks[0]`). [PDF p.4 §7]
* **REQ-D-03 (Baseline Comparisons):** Evaluated against three baselines: Last Value (Naive), 4-Week Moving Average, and Same Week Last Year (Seasonal Naive). Scoring depends on outperforming the best baseline. [PDF p.4 §7]
* **REQ-D-04 (Special Demand Patterns):** Handles promotions (from `promo_calendar.csv`), festival lift (shifting Diwali dates from `festival_calendar.csv`), intermittent demand / rarely sold SKUs, and new SKUs. Strategy documented in `DECISIONS.md`. [PDF p.4 §7]
* **REQ-D-05 (Forecast Detail API):** `GET /api/forecast/{sku}/` returns 4 forecast weeks identical to `ml/forecast.csv` (`200`). Unknown or non-forecast SKU returns `404 NOT_FOUND`. [Contract §10.2]
* **REQ-D-06 (Reorder Suggestions API & Exact Formula):** `GET /api/reorder-suggestions/` returns 40 unpaginated forecast SKU recommendations. Uses exact contract formula:
  - $L$ = `lead_time_weeks` from `lead_times.csv`
  - $\text{lead\_time\_demand}$ = sum of forecast units for first $L$ forecast weeks
  - $\sigma$ = sample standard deviation ($n-1$) of `units_sold` over most recent 12 weeks of `sales_history.csv`
  - $\text{safety\_stock} = \lceil 1.65 \times \sigma \times \sqrt{L} \rceil$
  - $\text{reorder\_point} = \text{lead\_time\_demand} + \text{safety\_stock}$
  - $\text{reorder\_qty} = \max(0, \lceil \text{reorder\_point} - \text{current\_stock} \rceil)$
  - Uses live warehouse stock at request time. [PDF p.4 §7; Contract §10.2]

---

### Category 6: Operations Frontend Dashboard (Part E) — Optional for Both Tracks
* **REQ-E-01 (Single-Page Dashboard on Django):** Served directly by Django at `GET /` (`http://localhost:8000/`) connecting directly to backend APIs. [PDF p.4 §8]
* **REQ-E-02 (Catalogue Browsing & Complete 600-Product Access):** Working pagination and/or load-more control allowing dealers to browse all 600 catalogue products. Accurate counter summary distinguishing total catalogue products (600) from currently displayed count. [PDF p.4 §8; Assignment Priority]
* **REQ-E-03 (Full-Catalogue Search & Filtering):** Search works across all 600 products (not just page 1). Category and vehicle fitment filters work across pages. Filters are preserved during pagination. [PDF p.4 §8]
* **REQ-E-04 (Order Lifecycle & Cart Flow):** Interactive UI for selecting products, entering quantity, creating DRAFT orders, confirming orders, and cancelling orders with clear error messages on short stock. [PDF p.4 §8]
* **REQ-E-05 (Assistant Chat UI):** Conversational chat interface displaying user/assistant messages, cited SKU pills, and order action alerts. [PDF p.4 §8]
* **REQ-E-06 (Forecast & Dynamic Reorder View):** Live table displaying lead time, safety stock, reorder point, live stock, and calculated reorder quantities. [PDF p.4 §8]
* **REQ-E-07 (Supplier Sync Trigger & Live Stats):** UI control to initiate full supplier synchronization and display sync statistics (created, updated, unchanged, rejected). [PDF p.4 §8]
* **REQ-E-08 (Responsive Usability):** Clean layout supporting desktop and mobile devices without console/network errors. [PDF p.4 §8]

---

### Category 7: Mandatory Clean-Install Run Contract & Repository Structure
* **REQ-RC-01 (Run Contract Execution):** Grader clones repository and executes:
  ```bash
  pip install -r requirements.txt
  python manage.py migrate --noinput
  python manage.py seed_data
  python manage.py seed_data
  python manage.py runserver 0.0.0.0:8000 --noreload
  ```
  App must start cleanly with this sequence; otherwise score is 0. [PDF p.5 §9.1; Contract §1]
* **REQ-RC-02 (Idempotent Seeding):** `python manage.py seed_data` loads `catalogue.csv` (600 products) and `dealers.csv` (25 dealers). Running it twice creates no duplicate records and preserves manual inventory adjustments. [PDF p.5 §9.1; Contract §1]
* **REQ-RC-03 (Environment Variable Configuration):** Reads `DATABASE_URL`, `SUPPLIER_API_URL`, `SUPPLIER_API_KEY`, and LLM keys strictly from environment. `.env.example` is committed; real `.env` is never committed. [PDF p.5 §9.1; Contract §1]
* **REQ-RC-04 (Data Directory Integrity):** Files in `data/` remain identical to provided datasets (`catalogue.csv`, `dealers.csv`, `sales_history.csv`, `promo_calendar.csv`, `lead_times.csv`, `festival_calendar.csv`). [PDF p.5 §10]
* **REQ-RC-05 (Repository Root Layout):** `manage.py`, `requirements.txt`, `API_CONTRACT.md`, `README.md`, `DECISIONS.md`, and `smoke_test.py` reside at the repository root. [PDF p.5 §9.1, p.6 §12]
* **REQ-RC-06 (Submission Archive Hygiene):** Archive excludes `.venv`, `.env`, compiled bytecode (`*.pyc`, `__pycache__`), IDE settings, and database log dumps. [PDF p.6 §12]

---

### Category 8: Documentation, DECISIONS.md & Video Walkthrough
* **REQ-DOC-01 (README.md Declaration):** Declares target track at top (`django` or `aiml`), setup steps, test execution commands, LLM provider & model, optional parts attempted, video link, and assumptions. [PDF p.6 §12]
* **REQ-DOC-02 (DECISIONS.md 8 Track Questions):** Thorough, concise, technically rigorous answers citing exact file paths and line numbers (`file:line`) for all 8 track questions. [PDF p.6–7 §12]
* **REQ-DOC-03 (5-Minute Video Walkthrough Link):** Up to 5 minutes, developer's own voice, no slides, code walkthrough of order-confirm flow (Django) or assistant tool-calling loop (AI/ML). Documented in README as link or marked PENDING. [PDF p.7 §12]
* **REQ-DOC-04 (Automated Smoke Test Verification):** `python smoke_test.py --base-url http://localhost:8000 --track django` and `--track aiml` pass with 0 failures on a clean seeded database. [PDF p.6 §11, §12]

