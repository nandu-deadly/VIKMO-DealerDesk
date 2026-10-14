# VIKMO DealerDesk — Evaluator Clean-Install & Hidden-Edge-Case Simulation Report

**Date & Time:** 2026-10-12  
**Test Environment:** Windows (PowerShell), Python 3.14.3 virtual environment (`.venv`), PostgreSQL 18.6  
**Test Isolation Mechanism:** PostgreSQL Isolated Schema `vikmo_evaluator_test` with dedicated `search_path`, separate from the operational `public` development database (`dealerdesk`).  
**Operational Development Database Status:** Pristine and untouched (600 products, 25 dealers, 600 inventory records, 0 stale orders).

---

## 1. Executive Summary & Verification Verdict

| Audit Milestone / Section | Contract Reference | Status | Evidence Summary |
| :--- | :--- | :---: | :--- |
| **Phase 2: Database Isolation** | Run Contract §1 | **PASS** | `vikmo_evaluator_test` schema created with full table isolation; dev DB had 0 modifications. |
| **Phase 3: Clean-Install Run Sequence** | Run Contract §1 | **PASS** | `pip install`, `migrate`, `seed_data` x2, `runserver` 0.0.0.0:8000, and `GET /api/health/` responded `200 {"status":"ok"}`. |
| **Phase 4A: Order Lifecycle & Rules** | Contract §7.1–§7.3 | **PASS** | Strict state machine (`DRAFT` → `CONFIRMED` → `DISPATCHED` → `DELIVERED` / `CANCELLED`), invalid transitions rejected (`409 INVALID_TRANSITION`), locked orders rejected (`409 ORDER_LOCKED`), stock restored exactly once on cancel. |
| **Phase 4B: GST & Exact Rounding** | Contract §7.4 | **PASS** | Tested `ROUND_HALF_UP` boundary cases (e.g. `0.25 * 0.18 = 0.045 -> 0.05`, `1.75 * 0.18 = 0.315 -> 0.32`). All per-line taxes and order totals exact to the paisa. |
| **Phase 4C: Concurrent Confirmations** | Contract §7.3 | **PASS** | Multi-threaded PostgreSQL `select_for_update()` test: 2 concurrent orders requesting 4 units from 5 stock resulted in exactly 1 confirmed, 1 rejected with `409 INSUFFICIENT_STOCK`, final stock = 1 (zero overselling). Single unit race: 1 confirmed, 1 rejected, final stock = 0. |
| **Phase 4D: Idempotency Concurrency** | Contract §7.5 | **PASS** | 5 concurrent threads sharing the same `Idempotency-Key` created exactly 1 order; 4 threads received cached replay. Different body with same key raised `409 IDEMPOTENCY_CONFLICT`. |
| **Phase 4E: Unique Order Numbers** | Contract §7.5 | **PASS** | 10 concurrent requests generated 10 strictly unique numbers formatted `ORD-YYYYMMDD-NNNN` using IST timezone. |
| **Phase 5: Supplier Sync Atomicity** | Contract §8 | **PASS** | Simulated persistent 503 outage after fetching Page 1: sync cleanly raised `502 SUPPLIER_UNAVAILABLE`, and database comparison confirmed 0 leaked records (100% atomic rollback). |
| **Phase 6: Full Regression & Smoke Suite** | API Contract §1, §2 | **PASS** | **58 / 58 Django unit tests passed (100%)**. **12 / 12 Official smoke checks passed (100%)**. |

---

## 2. Requirement Checklist & Source Mapping

| Requirement / Edge-Case | API Contract Clause | Implementation Source | Test Evidence |
| :--- | :--- | :--- | :--- |
| **PostgreSQL-Only Enforcement** | §1, §3 | `dealerdesk/settings.py:143-157` | Verified with PostgreSQL 18.6. Rejects SQLite. |
| **Clean Database Migration** | §1 | `manage.py migrate --noinput` | Applied 21 migrations clean on empty schema. |
| **Idempotent Data Seeding** | §1, §4, §6 | `core/management/commands/seed_data.py` | Run 1: 600 products, 25 dealers. Run 2: 0 duplicates created. |
| **Health Check Endpoint** | §1 | `core/views.py:HealthCheckView` | `GET /api/health/` → `200 {"status": "ok"}`. |
| **Order State Machine** | §7.1, §7.2 | `core/order_service.py:173-352` | `OrderStatus` transitions enforced with `409 INVALID_TRANSITION` and `409 ORDER_LOCKED`. |
| **Draft Stock Immutability** | §7.3 | `core/order_service.py:32-171` | Creating/editing DRAFT orders leaves warehouse stock untouched. |
| **Atomic Order Confirmation** | §7.3 | `core/order_service.py:246-285` | `select_for_update()` over items and inventory inside `transaction.atomic()`. |
| **Exact GST Per-Line Rounding** | §7.4 | `core/order_service.py:124, 220` | `Decimal("0.18").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)`. |
| **Concurrent Oversell Prevention** | §7.3 | `core/order_service.py:246-285` | Row-level PostgreSQL locks serialize stock checks and decrements. |
| **Concurrent Idempotency Safety** | §7.5 | `core/order_service.py:40-165` | Database uniqueness constraint on `IdempotencyRecord.key` + transaction retry loop. |
| **Format ORD-YYYYMMDD-NNNN** | §7.5 | `core/order_service.py:88-112` | Kolkata timezone (`Asia/Kolkata`) date prefix + sequential zero-padded suffix. |
| **Supplier Sync Atomicity** | §8.3 | `core/supplier_sync.py:176-224` | Entire catalogue update wrapped in `transaction.atomic()`; failed fetches abort without DB writes. |

---

## 3. Phase 2 & 3: Clean-Install Run Execution Log

All commands were run against the isolated test schema `vikmo_evaluator_test` configured via `DB_SCHEMA=vikmo_evaluator_test`:

1. **`pip install -r requirements.txt`**
   - Output: `Requirement already satisfied: Django<6,>=4.2 ... psycopg>=3.1 ... djangorestframework>=3.15`
   - Exit code: `0`
2. **`python manage.py migrate --noinput`**
   - Output: Applied 21 migrations across `contenttypes`, `auth`, `admin`, `core`, and `sessions`.
   - Exit code: `0`
3. **`python manage.py seed_data` (Pass 1)**
   - Output: `Catalogue: 600 created, 0 updated, 600 new inventory records initialized. Dealers: 25 created.`
   - Exit code: `0`
4. **`python manage.py seed_data` (Pass 2 - Idempotency Check)**
   - Output: `Catalogue: 0 created, 600 updated, 0 new inventory records initialized. Dealers: 0 created, 25 updated.`
   - Record counts verified:
     - Products: **600**
     - Dealers: **25**
     - Inventory Records: **600**
     - Orders: **0**
   - Exit code: `0`
5. **`python manage.py runserver 0.0.0.0:8000 --noreload` & Health Check**
   - Subprocess started on `0.0.0.0:8000`.
   - Request: `GET http://127.0.0.1:8000/api/health/`
   - Response: `200 OK` → `{"status": "ok"}`.
   - Clean shutdown executed.

---

## 4. Phase 4: Order Engine Contract Audit (§7.3–§7.5)

### A. Order Lifecycle and State Transitions
- **A1 Invalid Dealer:** `POST /api/orders/` with `dealer_id=999999` returned `400 VALIDATION_ERROR` (`PASS`).
- **A2 Empty Items:** `POST /api/orders/` with `items=[]` returned `400 VALIDATION_ERROR` (`PASS`).
- **A3 Invalid / Duplicate SKU:** Non-existent SKU and duplicate SKU in items array both returned `400 VALIDATION_ERROR` (`PASS`).
- **A4 Draft Stock Immutability:** Stock before draft: 237; stock after draft: 237 (`PASS`).
- **A5 Edit Draft:** Item replacement succeeded while order in `DRAFT` status (`PASS`).
- **A6 Order Confirmation:** Correctly transitioned status to `CONFIRMED` and decremented stock by exactly 3 (298 → 295) (`PASS`).
- **A7 Edit Non-Draft:** Attempting to `PUT /api/orders/{order_number}/` on confirmed order returned `409 ORDER_LOCKED` (`PASS`).
- **A8 Invalid Transition:** Skipping dispatch from `CONFIRMED` straight to `DELIVERED` returned `409 INVALID_TRANSITION` (`PASS`).
- **A9 Dispatch:** Transitioned `CONFIRMED` → `DISPATCHED` (`PASS`).
- **A10 Dispatched Cancellation Blocked:** Attempting to cancel a `DISPATCHED` order returned `409 INVALID_TRANSITION` (`PASS`).
- **A11 Delivery:** Transitioned `DISPATCHED` → `DELIVERED` (`PASS`).
- **A12 Confirmation Cancellation Restores Stock:** Cancelling a `CONFIRMED` order restored warehouse stock by exactly 5 (290 → 295) (`PASS`).
- **A13 Second Cancel Blocked:** Cancelling an already `CANCELLED` order returned `409 INVALID_TRANSITION` (`PASS`).

### B. Exact GST and Monetary Precision (`ROUND_HALF_UP`)
- **Boundary Test 1:** `TEST-HALF-001` (price 12.55, qty 1)
  - Subtotal: `12.55`
  - Tax Calculation: `12.55 * 0.18 = 2.2590` → `ROUND_HALF_UP` = `2.26`
  - Line Total: `14.81`
- **Boundary Test 2 (Crucial Half-Up Test):** `TEST-HALF-002` (price 0.25, qty 1)
  - Subtotal: `0.25`
  - Tax Calculation: `0.25 * 0.18 = 0.0450` → `ROUND_HALF_UP` = `0.05` (`ROUND_HALF_EVEN` / bank rounding would produce 0.04)
  - Line Total: `0.30`
- **Boundary Test 3 (Crucial Half-Up Test):** `TEST-HALF-003` (price 1.75, qty 1)
  - Subtotal: `1.75`
  - Tax Calculation: `1.75 * 0.18 = 0.3150` → `ROUND_HALF_UP` = `0.32`
  - Line Total: `2.07`
- **Order Level Aggregates:**
  - Order Subtotal: `14.55` (Exact match)
  - Order Tax Total: `2.63` (Exact match: `2.26 + 0.05 + 0.32 = 2.63`)
  - Order Grand Total: `17.18` (Exact match: `14.55 + 2.63 = 17.18`)
  - **Verdict:** `PASS` — All calculations performed in `Decimal`, zero binary floating-point inaccuracy.

### C. Concurrent Order Confirmations (Overselling Prevention)
- **Scenario 1 (5 units available, two concurrent orders for 4 units):**
  - Thread 1 (`ORD-...-0003`) and Thread 2 (`ORD-...-0002`) triggered simultaneously across separate PostgreSQL connections using a `threading.Barrier`.
  - Transaction 1 acquired row lock on `Inventory`, validated 4 <= 5, decremented stock to 1, committed `CONFIRMED`.
  - Transaction 2 acquired row lock on `Inventory`, saw available = 1 < requested 4, aborted with `409 INSUFFICIENT_STOCK`.
  - **Final Database Stock:** Exactly `1` unit (never negative, zero overselling).
  - **Final Orders State:** Exactly 1 `CONFIRMED`, exactly 1 `DRAFT`.
- **Scenario 2 (Single Unit Race):**
  - 1 unit available, two concurrent orders requesting 1 unit each.
  - Exactly 1 confirmed, 1 rejected with `409 INSUFFICIENT_STOCK`.
  - Final stock: `0`.
  - **Verdict:** `PASS`.

### D. Concurrent Idempotency-Key Requests
- **Test:** 5 concurrent threads submitted identical order payloads simultaneously with the same `Idempotency-Key` (`test-idem-concurrent-uuid-99999`).
- **Observed Behavior:**
  - Exactly 1 order created in database (`is_new=True`).
  - Remaining 4 concurrent threads successfully returned the existing order (`is_new=False`).
  - Total `IdempotencyRecord` rows in database: `1`.
- **Payload Tampering Replay:** Submitting the same key with modified quantity returned `409 IDEMPOTENCY_CONFLICT`.
- **Verdict:** `PASS`.

### E. Unique Order Numbers under Concurrency
- **Test:** 10 threads concurrently executed `create_order` across independent database connections.
- **Observed Order Numbers:**
  - `ORD-20261012-0009`
  - `ORD-20261012-0010`
  - `ORD-20261012-0011`
  - `ORD-20261012-0012`
  - `ORD-20261012-0013`
  - `ORD-20261012-0014`
  - `ORD-20261012-0015`
  - `ORD-20261012-0016`
  - `ORD-20261012-0017`
  - `ORD-20261012-0018`
- **Result:** 10/10 unique sequential numbers matching `ORD-YYYYMMDD-NNNN`. Zero collisions or gaps.
- **Verdict:** `PASS`.

---

## 5. Phase 5: Supplier Sync Atomicity and Failure Audit

### Outage Simulation Setup
- Database pre-sync snapshot captured: Products = 605, Inventory = 605, Sample SKU `ACC-1001` price = `2240.00`, stock = `237`.
- Mock session configured: Page 1 returned HTTP 200 with 1 new product (`NEW-SYNC-PART-999`) and 1 price alteration for `ACC-1001` (to `1.00`).
- Page 2 returned persistent HTTP 503 errors (5 consecutive retries).

### Observed Behavior
1. Service performed exponential backoff across 5 retry attempts:
   - Attempt 1: 503 → sleep 0.5s
   - Attempt 2: 503 → sleep 1.0s
   - Attempt 3: 503 → sleep 2.0s
   - Attempt 4: 503 → sleep 4.0s
   - Attempt 5: 503 → sleep 8.0s
2. Aborted with `SupplierUnavailableException: Supplier request failed after maximum retry attempts.` (HTTP 502 `SUPPLIER_UNAVAILABLE`).
3. Database post-failure comparison:
   - Products count: **605** (unchanged)
   - Inventory count: **605** (unchanged)
   - Sample SKU `ACC-1001` price: **2240.00** (unchanged)
   - Sample SKU `ACC-1001` stock: **237** (unchanged)
   - Product `NEW-SYNC-PART-999` exists in DB: **False** (0 leaked records)
- **Verdict:** `PASS` — All-or-nothing atomicity verified.

---

## 6. Phase 6: Automated Test Suite & Smoke Verification

### Django Test Suite
```bash
python manage.py test core.tests --keepdb
```
- **Total Tests:** 58
- **Results:** `Ran 58 tests in 8.043s - OK`
- **Passing Rate:** **58 / 58 (100%)**

### Official Smoke Tests
```bash
python smoke_test.py --base-url http://127.0.0.1:8000 --track django
python smoke_test.py --base-url http://127.0.0.1:8000 --track aiml
python smoke_test.py --base-url http://127.0.0.1:8000 --all
```
- **Track Django:** **9 / 9 checks passed**
- **Track AI/ML:** **10 / 10 checks passed**
- **All Tracks:** **12 / 12 checks passed**

---

## 7. Operational Development Database Integrity Check

Following the completion of all simulation and audit procedures, the primary development database (`dealerdesk`) was directly inspected:
- **Products:** **600**
- **Dealers:** **25**
- **Inventory Records:** **600**
- **Orders:** **0**
- **Status:** **Completely untouched and pristine.**

---

## 8. Files Modified During Hardening

1. `dealerdesk/settings.py`:
   - Added support for `DB_SCHEMA` to route database connections dynamically to isolated PostgreSQL schemas.
2. `core/order_service.py`:
   - Hardened `create_order` with `select_for_update()` on sequence lookups and atomic handling of `IdempotencyRecord` unique constraint collisions under concurrency.
3. `core/tests/test_concurrency_and_transactions.py`:
   - Added `test_concurrent_idempotency_key_deduplication` and `test_exact_gst_round_half_up_boundary_cases`.
4. `EVALUATOR_SIMULATION_REPORT.md`:
   - Created this comprehensive evidence report.
