# VIKMO DealerDesk — AI/ML Technical Decisions

This document answers all eight questions for the AI/ML Intern Track. Each answer describes the implementation, the reasoning behind the design, its limitations, and the relevant source files.

---

## 1. Explain your schema: each model, its relationships, and the `on_delete` choice for every foreign key.

**Code citation:** `core/models.py:15-179`

The application uses Django ORM models backed by PostgreSQL.

### Product — `core/models.py:15-38`

Stores catalogue information, including SKU, name, category, brand, vehicle fitment, price and description. The SKU is the primary key, allowing catalogue items to be identified consistently.

### Inventory — `core/models.py:40-61`

Has a one-to-one relationship with Product:

`product = OneToOneField(Product, on_delete=CASCADE, primary_key=True)`

`CASCADE` is appropriate because the inventory record belongs to its catalogue product. A database constraint prevents negative inventory quantities.

### Dealer — `core/models.py:63-88`

Stores dealer identity and business information, including dealer code, name, city, contact details and credit limit. Its relationship with Django's User model uses `OneToOneField` with `on_delete=SET_NULL`, preserving the dealer record if its linked user account is deleted.

### Order — `core/models.py:90-127`

Stores the order number, dealer, status and financial totals. Its dealer foreign key uses `on_delete=PROTECT`, preventing deletion of a dealer while related orders exist. This protects transaction history.

### OrderItem — `core/models.py:129-150`

Stores each order line, including quantity, product reference and price/tax snapshots. Its foreign keys use:

- `order`: `CASCADE`, because an order item belongs to its parent order.
- `product`: `PROTECT`, because products referenced by historical orders should not be deleted.

A unique constraint on the order and product prevents duplicate product lines within the same order.

### IdempotencyRecord — `core/models.py:152-163`

Stores a unique idempotency key, request-body hash and related order. Its order foreign key uses `CASCADE`, removing the idempotency record when its order is deleted.

### AssistantMessage — `core/models.py:165-179`

Stores assistant conversation messages, session identifiers, roles, content, tool-call metadata and timestamps. The session identifier is indexed to support conversation-history lookup. It is not a foreign key to Dealer.

These relationships help maintain data integrity, prevent accidental deletion of transaction history and support consistent catalogue, inventory and order operations.

---

## 2. How does retrieval work? Why these embedding, indexing and ranking choices, and where does retrieval fail?

**Code citation:** `core/assistant/retrieval.py:1-612`; `core/assistant/tools.py:8-14`

The current retrieval implementation uses a domain-specific hybrid lexical and database-search approach. It does **not** use semantic embedding vectors.

### Retrieval pipeline

1. **Query normalization:** Normalizes text, removes conversational filler, handles plural forms and expands common automotive spelling variations.
2. **Entity extraction:** Identifies part types, brands, categories and vehicle fitment from the user's request.
3. **Candidate retrieval:** Searches the catalogue using SKU matching, lexical signals and PostgreSQL trigram similarity where available.
4. **Ranking:** Combines SKU, part type, category, brand, vehicle fitment and text similarity signals.
5. **Fitment filtering:** Reduces the chance of recommending an incompatible part when the user specifies a vehicle.
6. **Result grounding:** Returns catalogue records and associated metadata to the assistant for response generation.

PostgreSQL's `pg_trgm` extension supports approximate text matching. A Python `difflib.SequenceMatcher` fallback is described in the existing implementation.

### Why this approach?

Exact SKUs and vehicle compatibility are especially important in automotive parts search. Semantic similarity alone could confuse similar product names or nearby SKU values, so deterministic matching and fitment constraints are useful.

The implementation avoids the additional model dependency and vector-index maintenance required by embedding-based retrieval.

### Limitations

Retrieval can fail when supplier metadata is incomplete, vehicle fitment is ambiguous, spelling variations are not covered, or an aftermarket compatibility relationship is missing from the catalogue. Similar text does not prove that a part fits a vehicle.

The system therefore reduces retrieval errors but cannot guarantee perfect recall or eliminate incorrect assistant responses.

A future improvement would be to evaluate semantic embeddings with PostgreSQL `pgvector`, while retaining exact SKU matching and vehicle compatibility checks.

---

## 3. Walk through your tool-calling loop, from the user's message to the final reply.

**Code citation:** `core/assistant/agent.py:235-324`; `core/assistant/sessions.py:15-30`; `core/assistant/tools.py:8-76`

The assistant uses an LLM to interpret requests and backend tools to retrieve information or initiate supported actions.

1. **Request received:** The API receives the user's message, session ID and dealer ID.
2. **Conversation history:** Previous messages are loaded from the assistant-message persistence layer.
3. **Model request:** The configured language model receives the conversation and available tool definitions.
4. **Tool selection:** The model may request a function such as `search_parts`, `check_stock` or `create_draft_order`.
5. **Backend execution:** The application validates and executes the requested tool against the database or order-service logic.
6. **Tool result:** The tool result is returned to the model as part of the tool-calling loop.
7. **Final response:** The model generates a natural-language answer based on the returned information.
8. **Persistence:** Conversation messages and relevant tool-call metadata are stored, and the API returns the response.

The language model decides which available tool may be useful, but the application executes the tool. Database operations therefore remain under backend control.

The exact provider and fallback behaviour depend on the configured environment. The implementation has been developed to support a configured LLM provider and an offline fallback.

---

## 4. How does your assistant get prices and stock, and how do you make sure it never states a figure that isn't in the database right now?

**Code citation:** `core/assistant/tools.py:8-33`; `core/assistant/agent.py:14-37`

The assistant obtains catalogue prices and inventory quantities through backend tools that read Product and Inventory records from PostgreSQL.

For example:

- `search_parts` retrieves relevant catalogue products.
- `check_stock` checks the inventory for a specific SKU.
- The assistant uses returned tool results to construct its response.

The system prompt instructs the model not to invent or estimate commercial values and to use the tool outputs for prices and stock quantities.

This approach grounds commercial answers in database records instead of relying on the model's learned knowledge.

However, a prompt instruction alone cannot guarantee that a model will never generate an incorrect number. Also, inventory may change after a query because another transaction could consume or replenish stock.

For stronger guarantees, the backend should validate every price and stock figure before returning it, and order-confirmation operations should recheck inventory inside an appropriate database transaction with locking. The response should distinguish a stock lookup from a completed reservation or order.

Therefore, the implementation provides database grounding, but absolute guarantees require enforcement at the application and transaction levels.

---

## 5. Supplier descriptions are untrusted. How does your assistant avoid following instructions hidden inside them, and where does your defence stop working?

**Code citation:** `core/assistant/agent.py:14-37`; `core/assistant/tools.py:36-76`

Supplier descriptions are external data and must not be treated as trusted instructions.

### Current defensive approach

1. **Prompt-level separation:** The system prompt tells the model to treat catalogue descriptions as untrusted data, not as instructions that override its system rules.
2. **Context boundaries:** The existing implementation describes wrapping catalogue text in `<untrusted_catalogue_data>` boundaries to distinguish product content from operational instructions.
3. **Restricted tools:** The assistant can only use the operations exposed by the application. It should not be able to perform actions for which no tool or backend permission exists.
4. **Backend validation:** Order and inventory operations must be validated by the backend rather than relying on the model's interpretation of supplier text.

### Where the defence stops working

Prompt-based injection defence is not a complete security boundary. A malicious description may still influence the model's recommendations, cause incorrect compatibility claims or attempt to manipulate tool selection.

Text boundaries are helpful but do not guarantee that the model will ignore every malicious instruction.

Further improvements would include sanitizing and validating supplier fields, checking vehicle fitment independently of free-text descriptions, applying authorization checks to every tool, and testing adversarial supplier descriptions automatically.

---

## 6. Describe your forecasting approach and how you validated it. Cite the line that stops future data leaking into training.

**Code citation:** `ml/train_forecast.py:131-208`; `ml/train_forecast.py:234`; `core/tests/test_forecasting.py`

The forecasting pipeline uses adaptive statistical methods to predict weekly demand for catalogue SKUs.

The existing implementation describes:

- **Exponential smoothing with a damped trend** for regular demand patterns.
- **Croston's method with the Syntetos–Boylan Approximation (SBA)** for intermittent demand.
- **Historical promotion response** to estimate the demand lift associated with scheduled promotions.
- **Diwali proximity adjustments** to account for the festival's changing calendar date.
- **A recency-weighted moving average** for SKUs with limited historical observations.

### Preventing future-data leakage

The existing document identifies the following line in `ml/train_forecast.py`:

```python
train = [r for r in full if r["week_start"] < test_weeks[0]]
```

This filter restricts training records to weeks before the first test week. The exact line number must be checked against the current source file before submission.

The forecasting pipeline uses chronological rolling-origin evaluation rather than randomly splitting time-series observations. This helps simulate the real situation where a forecast is produced using only historical data.

### Validation

The existing report records WAPE results for two four-week evaluation folds:

- Fold 1: proposed adaptive model WAPE of 26.66%.
- Fold 2: proposed adaptive model WAPE of 23.51%.

These numbers should be retained only if they match the current training and evaluation output. The same applies to any claimed percentage improvement over baselines.

The automated forecasting tests should be run again before submission to verify chronological separation, expected output rows and the current evaluation results.

---

## 7. Which SKUs does your forecast handle worst, and why? How did you handle promotions, Diwali, rarely sold SKUs and new SKUs?

**Code citation:** `ml/train_forecast.py:63-129`; `ml/train_forecast.py:158-170`

The most difficult SKUs are those with irregular demand, long periods without sales, or isolated promotional spikes. These patterns make recent averages and trend extrapolation less reliable.

The existing project report identifies `FIL-1031` as an example of a SKU affected by large promotional spikes. It should be described as the worst-handled SKU only if the latest per-SKU evaluation confirms that result.

### Promotions

The pipeline estimates per-SKU promotional lift from historical promotional and non-promotional periods. Planned promotion dates are read from the promotion calendar. Historical lift estimates can still be unreliable when only a few promotional observations exist.

### Diwali

The pipeline uses proximity to Diwali rather than assuming that the festival falls in the same Gregorian week every year. This is intended to align seasonal effects with the actual festival date.

### Rarely sold SKUs

SKUs with a high proportion of zero-sales weeks are routed to Croston's SBA method. It separates the estimated size of non-zero demand from the interval between demand events.

### New or low-history SKUs

The implementation describes using a recency-weighted moving average without trend extrapolation when history is limited. Such forecasts remain uncertain because there is insufficient evidence to learn a stable SKU-specific pattern.

### Main limitation

These statistical methods are interpretable and suitable for relatively small datasets, but they do not fully capture substitution between products or complex interactions between vehicle demand, promotions and seasonal events.

The strongest next step would be to evaluate errors by SKU and demand pattern, rather than relying on overall WAPE alone.

---

## 8. What is the weakest part of your submission, and what would you do with two more days?

The main weakness is the limited ability of the forecasting pipeline to learn cross-SKU relationships and complex demand interactions. The current statistical approach is interpretable, but products with irregular promotional demand or limited history remain difficult to forecast.

With two additional days, I would prioritize:

1. **Per-SKU error analysis:** Identify the SKUs and demand patterns contributing most to forecast error, and add targeted tests for those cases.
2. **Model comparison:** Evaluate a global gradient-boosted model such as LightGBM using historical lags, SKU attributes, promotion indicators and festival-proximity features. Keep the same chronological backtesting protocol and adopt it only if it improves held-out results.
3. **Forecast uncertainty:** Add prediction intervals or another calibrated uncertainty method so inventory decisions can account for forecast risk rather than relying only on point estimates.
4. **Retrieval evaluation:** Build a test set of realistic automotive queries, including typos, similar SKUs, ambiguous fitment and adversarial supplier descriptions. Measure retrieval quality and compatibility errors before adding embeddings.

These improvements would focus on measurable accuracy, safer assistant behaviour and more reliable inventory decisions rather than adding complexity without evidence of benefit.
