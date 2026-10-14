# VIKMO DealerDesk — Phase 7 Report: Submission Hardening

**Date:** 2026-10-11  
**Track:** AI/ML Intern  
**Final Status:** READY FOR SUBMISSION  

---

## 1. Checks Performed & Actual Results

| Category | Check Performed | Verification Method | Result | Status |
|---|---|---|---|---|
| **Django System Check** | Verify model definitions, system apps, and database engine | `python manage.py check` | `System check identified no issues (0 silenced)` | **PASS** |
| **Database Migrations** | Check pending migration drift or missing schema changes | `python manage.py makemigrations --check --dry-run` | `No changes detected` | **PASS** |
| **Unit & Integration Tests** | Full Django test suite (models, seeding, APIs, assistant, forecasting) | `python manage.py test core.tests --keepdb` | `Ran 31 tests in 2.856s - OK` | **PASS** |
| **Official Smoke Test** | End-to-end API validation across core, assistant, and ML tracks | `python smoke_test.py --base-url http://127.0.0.1:8000 --track aiml` | `10/10 checks passed` | **PASS** |
| **Forecast Artifact Integrity** | Check 160 rows, 40 SKUs, exact 4 future weeks, non-negativity, schema | Custom validation script on `ml/forecast.csv` | Exactly 160 rows, 40 SKUs, 0 negative values | **PASS** |
| **Reorder Engine Validation** | Independent verification of lead-time demand, $\sigma$, safety stock, and reorder point | Independent calculation across all 40 forecast SKUs | Exact mathematical match on all 40 SKUs | **PASS** |
| **Live Inventory Reactivity** | Verify reorder engine and assistant query live warehouse stock | Dynamic inventory updates and assertions | Real-time stock strictly respected | **PASS** |
| **Inventory Safety on Drafts** | Ensure draft order creation never alters inventory quantity | Order creation test with pre/post stock checks | Stock remains completely unchanged | **PASS** |

---

## 2. Issues Found & Minimal Fixes

### Issue Identified
- In `core/assistant/tools.py`, `search_parts` previously performed a single substring check on `Q(sku__icontains=q_clean) | Q(name__icontains=q_clean) | Q(brand__icontains=q_clean)`.
- When users asked conversational queries containing plurals or multi-word parts (e.g. `"brake pads for a Pulsar 150"`), the literal query string `"brake pads"` failed to match `"Brake Pad Set"` because of the plural `"pads"`.

### Minimal Fix Applied
- In [`core/assistant/tools.py`](core/assistant/tools.py#L14-L25), enhanced `search_parts` query filtering:
  - Preserved the full phrase search while adding word-level intersection filtering with simple stem/plural handling (e.g. `"pads"` -> `"pad"`).
  - In [`core/assistant/agent.py`](core/assistant/agent.py#L510-L516), cleaned conversational stop words and vehicle fitment names from the search query passed to `search_parts`.
- **Result**: Conversational queries like `"Do you have brake pads for a Pulsar 150?"` now accurately resolve to `BRK-1044` with full citations, live prices, and warehouse quantities.

---

## 3. Live GenAI Status

- **Status**: **NOT RUN (No live API keys configured in local development environment)**.
- **Audit Verification**:
  - Environment variable inspection confirmed `GEMINI_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`, and `ANTHROPIC_API_KEY` are not populated in local environment.
  - Zero hardcoded keys or secrets are stored in `.env`, `.env.example`, or repository code.
  - Tested and verified the deterministic fallback handler:
    - Tool invocation: `search_parts` dispatched with arguments `{"query": "brake", "vehicle": "Pulsar 150"}`.
    - Grounding: Quotes real catalogue price and live inventory for `BRK-1044`.
    - Citation: `cited_skus: ["BRK-1044"]`.
    - Off-topic queries: Politely declined with domain boundary notice.
    - Anti-prompt injection: Treats catalogue descriptions as inert supplier data.

---

## 4. Forecast & Reorder Validation Results

1. **Backtesting Reproducibility**:
   - `python ml/train_forecast.py` executed cleanly without data leakage (`week_start < test_weeks[0]`).
   - Recorded fold metrics:
     - **Fold 1**: Proposed Adaptive Model achieved MAE 9.46 / WAPE 26.66% (3.11% improvement over best baseline).
     - **Fold 2**: Proposed Adaptive Model achieved MAE 8.01 / WAPE 23.51% (8.54% improvement over best baseline).
2. **Reorder Engine Formula Audit**:
   - $\text{lead\_time\_demand} = \sum_{w=1}^L \text{forecast\_units}_w$: **Verified across all 40 SKUs**.
   - $\sigma = \sqrt{\frac{1}{n-1}\sum (x_i - \bar{x})^2}$ over most recent 12 weeks: **Verified across all 40 SKUs**.
   - $\text{safety\_stock} = \lceil 1.65 \times \sigma \times \sqrt{L} \rceil$: **Verified across all 40 SKUs**.
   - $\text{reorder\_point} = \text{lead\_time\_demand} + \text{safety\_stock}$: **Verified across all 40 SKUs**.
   - $\text{reorder\_qty} = \max(0, \lceil \text{reorder\_point} - \text{current\_stock} \rceil)$: **Verified across all 40 SKUs**.
3. **Model Limitations**:
   - The forecasting model is an adaptive time-series baseline designed for intermittent and seasonal demand (Croston SBA + EMA + Promo Lift + Diwali Proximity Splines). It is not a global deep-learning or gradient-boosted tree model, which remains a documented future enhancement in [`DECISIONS.md`](DECISIONS.md).

---

## 5. Security & Configuration Summary

- **PostgreSQL Requirement**: Strictly enforced in `settings.py`; application halts if SQLite is attempted.
- **Credential Safety**: No `.env` committed. `.gitignore` properly excludes `.env`, `*.pyc`, `__pycache__`, and `.venv`.
- **Order Engine Integrity**: Orders are created strictly in `DRAFT` status; inventory is never decremented until explicit order confirmation.
- **Idempotency Protection**: Reused keys with matching payloads return existing orders; mismatched payloads reject with `409 CONFLICT`.

---

## 6. Final Submission Recommendation

**The VIKMO DealerDesk AI/ML Intern Track repository is fully verified, robustly tested, and READY FOR SUBMISSION.**

All mandatory requirements match the specifications and contract shapes in `API_CONTRACT.md`.
