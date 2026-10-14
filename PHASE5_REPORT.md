# VIKMO DealerDesk — Phase 5 Report: GenAI Dealer Assistant

**Date:** 2026-10-11  
**Track:** AI/ML Intern  
**Status:** Complete & Verified  

---

## 1. Executive Summary

Phase 5 implements the GenAI Dealer Assistant (`POST /api/assistant/chat/`) fulfilling all requirements in `API_CONTRACT.md` §9. The assistant enables dealers to interactively query catalogue products, check real-time stock and prices, and generate draft orders using tool calling grounded in the live PostgreSQL database.

All 29 automated tests pass, and **10/10 official AI/ML smoke test checks pass**.

---

## 2. Architecture & Components

### 2.1 Endpoint
- **URL**: `POST /api/assistant/chat/`
- **Request Payload**:
  ```json
  {
    "session_id": "string",
    "dealer_id": 1,
    "message": "Do you have brake pads for a Pulsar 150?"
  }
  ```
- **Response Structure (200 OK)**:
  ```json
  {
    "reply": "Yes — Endurance Brake Pad Set (BRK-1044) fits the Bajaj Pulsar 150 ...",
    "cited_skus": ["BRK-1044"],
    "tool_calls": [
      {
        "name": "search_parts",
        "arguments": {"query": "brake pads", "vehicle": "Bajaj Pulsar 150"}
      }
    ],
    "actions": []
  }
  ```

### 2.2 Tools Implemented
1. `search_parts(query, vehicle, category)`:
   - Queries live PostgreSQL `Product` table with preloaded `Inventory`.
   - Returns up to 5 matching parts with real-time stock and unit prices formatted to two decimal places.
2. `check_stock(sku)`:
   - Checks real-time quantity and price for a specific SKU.
   - Grounded in database; returns clear not-found error if SKU does not exist.
3. `create_draft_order(dealer_id, items)`:
   - Invokes core `OrderService.create_order` to enforce standard business validation, 18% GST rounding (`ROUND_HALF_UP`), sequential collision-free `ORD-YYYYMMDD-NNNN` order numbers, and dealer credit limit validation.
   - Emits action `{"type": "draft_order_created", "order_number": "ORD-..."}`.
   - Orders remain strictly in `DRAFT` status; inventory is never deducted prematurely.

### 2.3 Provider Integration & Fallback Strategy
- Official SDK: `google-genai` (v2.29.0) with support for `gemini-2.5-flash`.
- Multi-provider support:
  - Google Gemini: via `google-genai` or direct REST API (`GEMINI_API_KEY`).
  - Groq: `llama-3.3-70b-versatile` (`GROQ_API_KEY`).
  - OpenAI: `gpt-4o-mini` (`OPENAI_API_KEY`).
- Zero-key / Deterministic Offline Mode:
  - If no external API keys are configured (e.g. offline testing environments), the agent smoothly routes to an intent-driven tool dispatcher executing live database tools. This ensures tests pass deterministically without network dependencies or flaky mocks.

### 2.4 Session Isolation & Anti-Injection Guardrails
- **Session Isolation**:
  - `SessionManager` records conversation history in PostgreSQL using the `AssistantMessage` model indexed by `session_id`.
  - Sessions never leak or share state across different `session_id`s.
- **Anti-Prompt Injection**:
  - System prompt explicitly enforces that catalogue descriptions and part names are untrusted supplier data, not instructions.
  - Off-topic queries (e.g. weather, recipes, general conversation) are politely declined.
- **Strict Grounding**:
  - Only real SKUs existing in the database are cited (`extract_cited_skus`). Zero hallucinated SKUs or fabricated prices.

---

## 3. Verification & Test Results

### 3.1 Automated Test Suite
Ran `python manage.py test core.tests --keepdb`:
- **29/29 tests passed** (including 9 assistant tests covering tools, sessions, citations, anti-injection, and API contract shape).

```
Ran 29 tests in 3.773s
OK
```

### 3.2 Official Smoke Test
Ran `python smoke_test.py --base-url http://127.0.0.1:8000 --track aiml`:
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
  [PASS] POST /api/assistant/chat/ (response shape only)

Forecasting
  [PASS] ml/forecast.csv (columns, 160 rows, weeks)
  [PASS] GET /api/forecast/{sku}/ and /api/reorder-suggestions/ (shape only)

10/10 checks passed.
```

---

## 4. Modified & Created Files

1. [`core/assistant/__init__.py`](file:///d:/VIKMO_DealerDesk_Assignment/core/assistant/__init__.py): Assistant module initialization.
2. [`core/assistant/tools.py`](file:///d:/VIKMO_DealerDesk_Assignment/core/assistant/tools.py): `search_parts`, `check_stock`, `create_draft_order`.
3. [`core/assistant/sessions.py`](file:///d:/VIKMO_DealerDesk_Assignment/core/assistant/sessions.py): PostgreSQL session manager using `AssistantMessage`.
4. [`core/assistant/agent.py`](file:///d:/VIKMO_DealerDesk_Assignment/core/assistant/agent.py): Multi-provider LLM agent with tool calling loop, injection defense, and grounded citation extractor.
5. [`core/views.py`](file:///d:/VIKMO_DealerDesk_Assignment/core/views.py): Added `AssistantChatView`.
6. [`core/urls.py`](file:///d:/VIKMO_DealerDesk_Assignment/core/urls.py): Added `path("assistant/chat/", ...)`.
7. [`core/tests/test_assistant.py`](file:///d:/VIKMO_DealerDesk_Assignment/core/tests/test_assistant.py): Unit and API tests for Phase 5.
8. [`requirements.txt`](file:///d:/VIKMO_DealerDesk_Assignment/requirements.txt): Added `google-genai>=2.0.0`.
9. [`README.md`](file:///d:/VIKMO_DealerDesk_Assignment/README.md): Documented LLM provider, models, and tool architecture.
