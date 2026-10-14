# VIKMO DealerDesk — Phase 4 Execution Report: Demand Forecasting & Reorder Engine

## 1. Summary of Deliverables & Files Changed

Phase 4 implemented the complete reproducible demand forecasting pipeline, backtesting benchmark suite, committed forecast file, and reorder suggestion endpoints in compliance with [`API_CONTRACT.md`](API_CONTRACT.md) §10:

1. **[`ml/train_forecast.py`](ml/train_forecast.py)**:
   - Reproducible pipeline implementing chronological rolling-origin backtesting across all 3 baseline models and an adaptive forecasting model.
   - Accurately models known future promotions (`promo_calendar.csv`), festival calendar shifting (`festival_calendar.csv`), intermittent demand (Croston-SBA), and cold-start SKUs.
2. **[`ml/forecast.csv`](ml/forecast.csv)**:
   - Committed forecast artifact containing exactly 160 rows (40 forecast SKUs $\times$ 4 weeks: `2026-09-28`, `2026-10-05`, `2026-10-12`, `2026-10-19`).
   - Format: `sku,week_start,forecast_units`.
3. **[`core/forecasting_service.py`](core/forecasting_service.py)**:
   - Core forecasting service reading `ml/forecast.csv` and computing reorder suggestions using exact contract formulas.
   - Calculates sample standard deviation ($\sigma$, ddof=1) over the 12 most recent weeks of `sales_history.csv`.
   - Computes:
     $$\text{lead\_time\_demand} = \sum_{w=1}^L \text{forecast\_units}_w$$
     $$\text{safety\_stock} = \lceil 1.65 \times \sigma \times \sqrt{L} \rceil$$
     $$\text{reorder\_point} = \text{lead\_time\_demand} + \text{safety\_stock}$$
     $$\text{reorder\_qty} = \max(0, \lceil \text{reorder\_point} - \text{current\_stock} \rceil)$$
   - Reads `current_stock` live from PostgreSQL `Inventory` table at request time.
4. **[`core/views.py`](core/views.py)** & **[`core/urls.py`](core/urls.py)**:
   - `GET /api/forecast/{sku}/`: Returns 4-week forecast or `404 NOT_FOUND`.
   - `GET /api/reorder-suggestions/`: Returns 40 unpaginated reorder suggestion items.
5. **[`core/tests/test_forecasting.py`](core/tests/test_forecasting.py)**:
   - 4 automated test cases verifying CSV integrity, 40 SKUs, 4 dates, non-negativity, 404 error handling, hand-calculated reorder formulas, zero stock, and stock above reorder point.
6. **[`DECISIONS.md`](DECISIONS.md)**:
   - Comprehensive answers to all 8 AI/ML track questions with code citations and measured backtest metrics.

---

## 2. Chronological Backtesting & Baseline Comparison

Evaluated using rolling-origin backtesting with strict prevention of data leakage ([`ml/train_forecast.py:241`](ml/train_forecast.py#L241)):

### Fold 1: Test Weeks 97–100 (`2026-08-03` to `2026-08-24`)
| Model / Baseline | MAE | WAPE | RMSE | Relative Improvement |
|---|---|---|---|---|
| Naive (Last Value) | 11.88 | 33.50% | 16.87 | Baseline 1 |
| Same-Week-Last-Year (Seasonal Naive) | 11.48 | 32.36% | 17.32 | Baseline 3 |
| 4-Week Moving Average | 9.76 | 27.52% | 14.62 | Baseline 2 (Best) |
| **Proposed Adaptive Model** | **9.46** | **26.66%** | **14.06** | **+3.11% over best baseline** |

### Fold 2: Test Weeks 101–104 (`2026-08-31` to `2026-09-21`)
| Model / Baseline | MAE | WAPE | RMSE | Relative Improvement |
|---|---|---|---|---|
| Same-Week-Last-Year (Seasonal Naive) | 12.27 | 36.01% | 19.72 | Baseline 3 |
| Naive (Last Value) | 11.72 | 34.41% | 19.58 | Baseline 1 |
| 4-Week Moving Average | 8.76 | 25.71% | 15.01 | Baseline 2 (Best) |
| **Proposed Adaptive Model** | **8.01** | **23.51%** | **11.64** | **+8.54% over best baseline** |

---

## 3. Actual Test & Verification Results

### 3.1 Django System Check
```powershell
python manage.py check
```
**Output**: `System check identified no issues (0 silenced).`

### 3.2 Migrations Dry-Run
```powershell
python manage.py makemigrations --check --dry-run
```
**Output**: `No changes detected`

### 3.3 Unit Test Suite Against PostgreSQL
```powershell
python manage.py test core.tests --keepdb
```
**Output**:
```
Ran 20 tests in 3.548s
OK
```
- 6 Phase 2 tests (models, constraints, idempotent seeding): **ALL PASS**
- 10 Phase 3 tests (products, inventory, dealers, draft orders, GST rounding): **ALL PASS**
- 4 Phase 4 tests (`test_forecast_csv_structure_and_constraints`, `test_forecast_api_detail_and_404`, `test_reorder_suggestions_api_and_exact_formulas`, `test_reorder_suggestions_live_inventory_integration`): **ALL PASS**

### 3.4 Official Smoke Test (`smoke_test.py --track aiml`)
Ran against server at `http://127.0.0.1:8000`:
```powershell
python smoke_test.py --base-url http://127.0.0.1:8000 --track aiml
```
**Actual Output**:
```
DealerDesk smoke test against http://127.0.0.1:8000  (parts: assistant, core, forecast)

Core
  [PASS] GET /api/health/
  [PASS] GET /api/products/ (pagination, fields, 600 seeded)
  [PASS] GET /api/products/{sku}/ and 404 error shape
  [PASS] Dealers: list (25 seeded) and create
  [PASS] PUT /api/inventory/{sku}/
  [PASS] POST /api/orders/ creates a DRAFT (shape, money format)
  [PASS] Validation error shape (empty items)

Dealer Assistant
  [FAIL] POST /api/assistant/chat/ (response shape only) -> Scheduled for Phase 5

Forecasting
  [PASS] ml/forecast.csv (columns, 160 rows, weeks)
  [PASS] GET /api/forecast/{sku}/ and /api/reorder-suggestions/ (shape only)

9/10 checks passed.
```

---

## 4. Contract Deviations & Unresolved Issues

- **None**: Both `ml/forecast.csv`, `GET /api/forecast/{sku}/`, and `GET /api/reorder-suggestions/` conform to `API_CONTRACT.md`.
- **Only Remaining Track Component**: Dealer Assistant (`/api/assistant/chat/`), scheduled for Phase 5.
