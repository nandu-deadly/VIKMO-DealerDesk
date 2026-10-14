#!/usr/bin/env python3
"""DealerDesk smoke test: checks the basics of the contract before you submit.

    pip install requests
    python smoke_test.py --base-url http://localhost:8000 --track django
    python smoke_test.py --base-url http://localhost:8000 --track aiml
    python smoke_test.py --base-url http://localhost:8000 --all      # also check optional parts

Run it against a FRESHLY SEEDED database (it creates a test dealer and orders).
Passing this does NOT mean you'll score well. The hidden grader tests the business rules,
concurrency, the supplier sync's behaviour, the assistant and the forecast in depth.
"""
import argparse, csv, os, re, sys, uuid

try:
    import requests
except ImportError:
    sys.exit("Please `pip install requests` first.")

MONEY = re.compile(r"^-?\d+\.\d{2}$")
ORDER_NO = re.compile(r"^ORD-\d{8}-\d{4}$")
results = []


def check(name, fn):
    try:
        problem = fn()
    except requests.RequestException as e:
        problem = f"request failed: {e}"
    except Exception as e:  # a crashing check is reported, never stops the run
        problem = f"{type(e).__name__}: {e}"
    ok = not problem
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + ("" if ok else f"\n         -> {problem}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000")
    ap.add_argument("--track", choices=["django", "aiml"])
    ap.add_argument("--all", action="store_true", help="check every part, required or not")
    ap.add_argument("--data", default="data", help="path to the data/ folder")
    ap.add_argument("--forecast", default=os.path.join("ml", "forecast.csv"))
    ap.add_argument("--distributor-user", default=os.environ.get("DISTRIBUTOR_USERNAME", "distributor"))
    ap.add_argument("--distributor-password", default=os.environ.get("DISTRIBUTOR_PASSWORD", ""))
    a = ap.parse_args()
    if not a.track and not a.all:
        ap.error("give --track django, --track aiml or --all")
    B = a.base_url.rstrip("/")
    S = requests.Session()
    get = lambda p, **kw: S.get(B + p, timeout=kw.pop("timeout", 20), **kw)

    def post(p, body=None, **kw):
        headers = dict(kw.pop("headers", {}))
        csrf = S.cookies.get("csrftoken")
        if csrf and "X-CSRFToken" not in headers:
            headers["X-CSRFToken"] = csrf
        return S.post(B + p, json=body, headers=headers, timeout=kw.pop("timeout", 20), **kw)
    parts = {"core"}
    if a.all or a.track == "django":
        parts |= {"engine", "sync"}
    if a.all or a.track == "aiml":
        parts |= {"assistant", "forecast"}
    ctx = {}
    teardown_actions = {
        "orders": [],
        "dealers": [],
        "inventory": {},
    }

    def err_shape(r, status, code):
        if r.status_code != status:
            return f"expected HTTP {status}, got {r.status_code}: {r.text[:200]}"
        try:
            e = r.json()["error"]
        except Exception:
            return f'body must be {{"error": {{"code", "message", "details"}}}}, got: {r.text[:200]}'
        if e.get("code") != code or "message" not in e or not isinstance(e.get("details"), list):
            return f"expected error.code={code} with message and details list, got {e}"
        return None

    print(f"\nDealerDesk smoke test against {B}  (parts: {', '.join(sorted(parts))})\n")

    try:
        print("Core")

        def health():
            r = get("/api/health/")
            if r.status_code != 200 or r.json() != {"status": "ok"}:
                return f'expected 200 {{"status": "ok"}}, got {r.status_code} {r.text[:100]}'
        if not check("GET /api/health/", health):
            print("\nThe app isn't reachable or healthy; fix that first.")
            sys.exit(1)

        def products():
            r = get("/api/products/?page_size=5")
            b = r.json()
            for k in ("count", "next", "previous", "results"):
                if k not in b:
                    return f"paginated list must include '{k}'"
            if b["count"] != 600:
                return f"count is {b['count']}, expected 600 on a freshly seeded database (seed twice must not duplicate)"
            p = b["results"][0]
            for k in ("sku", "name", "category", "brand", "vehicle_fitment", "price", "stock", "description"):
                if k not in p:
                    return f"product is missing '{k}'"
            if not (isinstance(p["price"], str) and MONEY.match(p["price"])):
                return f"price must be a string with 2 decimals, got {p['price']!r}"
            if not isinstance(p["stock"], int):
                return f"stock must be an integer, got {p['stock']!r}"
            ctx["products"] = b["results"]
        check("GET /api/products/ (pagination, fields, 600 seeded)", products)

        def product_detail():
            sku = ctx["products"][0]["sku"]
            r = get(f"/api/products/{sku}/")
            if r.status_code != 200 or r.json().get("sku") != sku:
                return f"GET /api/products/{sku}/ returned {r.status_code}"
            return err_shape(get("/api/products/NOPE-0000/"), 404, "NOT_FOUND")
        check("GET /api/products/{sku}/ and 404 error shape", product_detail)

        def dealers():
            # 1. Fetch first page with page_size=5 to verify pagination response shape
            r5 = get("/api/dealers/?page_size=5")
            if r5.status_code != 200:
                return f"GET /api/dealers/?page_size=5 returned HTTP {r5.status_code}: {r5.text[:150]}"
            b = r5.json()
            for k in ("count", "next", "previous", "results"):
                if k not in b:
                    return f"paginated list must include '{k}'"
            if not b.get("results"):
                return "GET /api/dealers/?page_size=5 returned empty results"

            # Immediate fallback: set ctx["dealer"] to a valid integer right away
            ctx["dealer"] = b["results"][0]["id"]

            # 2. Paginate through all dealers using page_size=100
            all_dealers = []
            next_url = "/api/dealers/?page_size=100"
            while next_url:
                path = next_url if next_url.startswith("/") else next_url.replace(B, "")
                resp = get(path)
                if resp.status_code != 200:
                    return f"GET {path} returned HTTP {resp.status_code}: {resp.text[:150]}"
                page_data = resp.json()
                for k in ("count", "next", "previous", "results"):
                    if k not in page_data:
                        return f"paginated list at {path} must include '{k}'"
                all_dealers.extend(page_data.get("results", []))
                next_url = page_data.get("next")

            # 3. Verify all 25 seeded dealers against data/dealers.csv
            dealers_csv = os.path.join(a.data, "dealers.csv")
            if os.path.exists(dealers_csv):
                with open(dealers_csv, "r", encoding="utf-8") as f:
                    expected_seeded_codes = {row["dealer_code"] for row in csv.DictReader(f) if row.get("dealer_code")}
            else:
                expected_seeded_codes = {f"DLR-{i:03d}" for i in range(1, 26)}

            seeded_dealers = [x for x in all_dealers if x.get("dealer_code") in expected_seeded_codes]

            if len(seeded_dealers) != 25:
                return f"expected 25 seeded dealers, found {len(seeded_dealers)}"

            missing_codes = expected_seeded_codes - {x["dealer_code"] for x in seeded_dealers}
            if missing_codes:
                return f"missing seeded dealers: {sorted(missing_codes)}"

            # 4. Select an authorized seeded dealer (DLR-001 through DLR-025) and verify eligibility
            selected_dealer = seeded_dealers[0]
            ctx["dealer"] = selected_dealer["id"]
            for k in ("id", "dealer_code", "name", "credit_limit"):
                if k not in selected_dealer:
                    return f"dealer is missing '{k}'"

            # 5. Verify dealer creation endpoint using temporary test dealer, tracked for teardown
            temp_code = f"TEMP-{uuid.uuid4().hex[:6]}"
            r = post("/api/dealers/", {"dealer_code": temp_code, "name": "Temporary Test Dealer"})
            if r.status_code != 201:
                return f"POST /api/dealers/ returned {r.status_code}: {r.text[:150]}"
            temp_id = r.json().get("id")
            if temp_id:
                teardown_actions["dealers"].append(temp_id)
        check("Dealers: list (25 seeded) and create", dealers)

        def inventory():
            sku = ctx["products"][0]["sku"]
            # Save pre-test inventory quantity before making changes
            curr_res = get(f"/api/products/{sku}/")
            if curr_res.status_code == 200:
                teardown_actions["inventory"][sku] = curr_res.json().get("stock", 50)

            r = S.put(f"{B}/api/inventory/{sku}/", json={"quantity": 50, "reason": "smoke test"}, timeout=20)
            if r.status_code != 200 or r.json().get("quantity") != 50:
                return f"PUT /api/inventory/{sku}/ returned {r.status_code}: {r.text[:150]}"
            if get(f"/api/products/{sku}/").json().get("stock") != 50:
                return "product stock doesn't reflect the inventory update"
            ctx["sku"] = sku
        check("PUT /api/inventory/{sku}/", inventory)

        def create_order():
            dealer_id = ctx.get("dealer")
            if not dealer_id:
                return "dealer ID not set in ctx"
            r = post("/api/orders/", {"dealer_id": dealer_id, "items": [{"sku": ctx["sku"], "quantity": 2}]})
            if r.status_code != 201:
                return f"expected 201, got {r.status_code}: {r.text[:200]}"
            o = r.json()
            ord_no = o.get("order_number")
            if ord_no:
                teardown_actions["orders"].append(ord_no)
            ctx["order"] = ord_no
            for k in ("order_number", "dealer_id", "status", "items", "subtotal", "tax_total", "grand_total", "created_at", "updated_at"):
                if k not in o:
                    return f"order is missing '{k}'"
            if o["status"] != "DRAFT":
                return f"new orders must be DRAFT, got {o['status']}"
            it = o["items"][0] if o["items"] else {}
            for k in ("sku", "name", "quantity", "unit_price", "line_subtotal", "line_tax", "line_total"):
                if k not in it:
                    return f"order item is missing '{k}'"
            for k in ("subtotal", "tax_total", "grand_total"):
                if not (isinstance(o[k], str) and MONEY.match(o[k])):
                    return f"{k} must be a string with 2 decimals, got {o[k]!r}"
            if "engine" in parts and not ORDER_NO.match(o["order_number"]):
                return f"order_number must look like ORD-YYYYMMDD-NNNN, got {o['order_number']!r}"
            if get(f"/api/orders/{o['order_number']}/").status_code != 200:
                return "GET /api/orders/{order_number}/ failed"
        check("POST /api/orders/ creates a DRAFT (shape, money format)", create_order)

        check("Validation error shape (empty items)",
              lambda: err_shape(post("/api/orders/", {"dealer_id": ctx.get("dealer"), "items": []}), 400, "VALIDATION_ERROR"))

        if "engine" in parts:
            print("\nOrder engine")

            def lifecycle():
                n = ctx["order"]

                # 1. Reject unauthenticated/anonymous confirmation (HTTP 401)
                anon_s = requests.Session()
                r_anon = anon_s.post(f"{B}/api/orders/{n}/confirm/", timeout=10)
                if r_anon.status_code != 401:
                    return f"expected HTTP 401 for anonymous confirm, got {r_anon.status_code}: {r_anon.text[:150]}"

                # 2. Authenticate distributor session
                dist_pwd = a.distributor_password or os.environ.get("DISTRIBUTOR_PASSWORD", "")
                if not dist_pwd:
                    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
                    if os.path.exists(env_path):
                        with open(env_path, "r", encoding="utf-8") as ef:
                            for line in ef:
                                line = line.strip()
                                if line.startswith("DISTRIBUTOR_PASSWORD="):
                                    dist_pwd = line.split("=", 1)[1].strip().strip('"').strip("'")
                if not dist_pwd:
                    dist_pwd = "Distributor@123"

                login_url = f"{B}/distributor/login/"
                S.get(login_url, timeout=10)
                csrf = S.cookies.get("csrftoken") or ""
                login_res = S.post(
                    login_url,
                    data={
                        "username": a.distributor_user,
                        "password": dist_pwd,
                        "csrfmiddlewaretoken": csrf,
                    },
                    headers={"Referer": login_url},
                    allow_redirects=False,
                    timeout=10,
                )
                if login_res.status_code not in (200, 302):
                    return f"Distributor login failed ({login_res.status_code}): {login_res.text[:150]}"

                # 3. Authenticated distributor confirms the order
                r = post(f"/api/orders/{n}/confirm/")
                if r.status_code != 200 or r.json().get("status") != "CONFIRMED":
                    return f"confirm returned {r.status_code}: {r.text[:150]}"
                if get(f"/api/products/{ctx['sku']}/").json()["stock"] != 48:
                    return "confirming 2 units should reduce stock from 50 to 48"
                r = post(f"/api/orders/{n}/cancel/")
                if r.status_code != 200 or r.json().get("status") != "CANCELLED":
                    return f"cancel returned {r.status_code}: {r.text[:150]}"
                if get(f"/api/products/{ctx['sku']}/").json()["stock"] != 50:
                    return "cancelling a confirmed order should restore stock to 50"
                return err_shape(post(f"/api/orders/{n}/confirm/"), 409, "INVALID_TRANSITION")
            check("Confirm, cancel and an invalid transition", lifecycle)

        if "sync" in parts:
            print("\nSupplier sync  (start supplier_mock/mock_supplier.py and point SUPPLIER_API_URL at it)")

            def sync():
                r = post("/api/sync/supplier/", timeout=150)
                if r.status_code == 502:
                    return "got 502: is the supplier mock running, and are SUPPLIER_API_URL / SUPPLIER_API_KEY set for your app?"
                if r.status_code != 200:
                    return f"expected 200, got {r.status_code}: {r.text[:200]}"
                b = r.json()
                for k in ("created", "updated", "unchanged", "rejected", "pages_fetched", "requests_made"):
                    if k not in b:
                        return f"response is missing '{k}'"
                if not isinstance(b["rejected"], list):
                    return "'rejected' must be a list"
                print(f"         summary: created={b['created']} updated={b['updated']} unchanged={b['unchanged']} "
                      f"rejected={len(b['rejected'])} pages={b['pages_fetched']} requests={b['requests_made']}")
            check("POST /api/sync/supplier/ (response shape only)", sync)

        if "assistant" in parts:
            print("\nDealer Assistant")

            def chat():
                dealer_id = ctx.get("dealer")
                if not dealer_id:
                    return "dealer ID not set in ctx"
                r = post("/api/assistant/chat/", {"session_id": f"smoke-{uuid.uuid4().hex[:6]}", "dealer_id": dealer_id,
                                                   "message": "Hello, what can you help me with?"}, timeout=90)
                if r.status_code != 200:
                    return f"expected 200, got {r.status_code}: {r.text[:200]}"
                b = r.json()
                if not isinstance(b.get("reply"), str):
                    return "'reply' must be a string"
                for k in ("cited_skus", "tool_calls", "actions"):
                    if not isinstance(b.get(k), list):
                        return f"'{k}' must be a list"
            check("POST /api/assistant/chat/ (response shape only)", chat)

        if "forecast" in parts:
            print("\nForecasting")
            weeks = ["2026-09-28", "2026-10-05", "2026-10-12", "2026-10-19"]

            def forecast_file():
                lead = os.path.join(a.data, "lead_times.csv")
                if not os.path.exists(a.forecast):
                    return f"{a.forecast} not found (run this from your repo root, or pass --forecast)"
                rows = list(csv.DictReader(open(a.forecast, encoding="utf-8")))
                if not rows or list(rows[0].keys())[:3] != ["sku", "week_start", "forecast_units"]:
                    return "columns must be: sku,week_start,forecast_units"
                skus = {r["sku"] for r in csv.DictReader(open(lead))} if os.path.exists(lead) else None
                have = {(r["sku"], r["week_start"]) for r in rows}
                if skus and have != {(s, w) for s in skus for w in weeks}:
                    return f"need exactly one row per forecast SKU per week ({len(skus) * 4} rows), got {len(rows)} rows"
                if any(float(r["forecast_units"]) < 0 for r in rows):
                    return "forecast_units must be non-negative"
                ctx["fsku"] = rows[0]["sku"]
            check("ml/forecast.csv (columns, 160 rows, weeks)", forecast_file)

            def forecast_api():
                sku = ctx.get("fsku")
                if not sku:
                    return "skipped: forecast.csv check failed"
                b = get(f"/api/forecast/{sku}/").json()
                if [x.get("week_start") for x in b.get("forecast", [])] != weeks:
                    return f"expected 4 weeks {weeks}, got {b}"
                r = get("/api/reorder-suggestions/", timeout=60)
                res = r.json().get("results")
                if not isinstance(res, list) or len(res) != 40:
                    return f"expected 40 results, got {len(res) if isinstance(res, list) else res!r}"
                for k in ("sku", "current_stock", "lead_time_weeks", "lead_time_demand", "safety_stock", "reorder_point", "reorder_qty"):
                    if k not in res[0]:
                        return f"reorder entry is missing '{k}'"
            check("GET /api/forecast/{sku}/ and /api/reorder-suggestions/ (shape only)", forecast_api)

    finally:
        print("\nTeardown: cleaning up test artifacts...")
        # 1. Clean up created test orders
        for ord_no in teardown_actions.get("orders", []):
            try:
                ord_res = get(f"/api/orders/{ord_no}/")
                if ord_res.status_code == 200:
                    status_val = ord_res.json().get("status")
                    if status_val == "CONFIRMED":
                        # Attempt cancel to restore stock before deletion
                        post(f"/api/orders/{ord_no}/cancel/")
                del_res = S.delete(f"{B}/api/orders/{ord_no}/", timeout=10)
                if del_res.status_code not in (200, 204, 404):
                    print(f"         teardown warning: delete order {ord_no} returned {del_res.status_code}")
            except Exception as ex:
                print(f"         teardown error deleting order {ord_no}: {ex}")

        # 2. Clean up temporary test dealers
        for d_id in teardown_actions.get("dealers", []):
            try:
                del_res = S.delete(f"{B}/api/dealers/{d_id}/", timeout=10)
                if del_res.status_code not in (200, 204, 404):
                    print(f"         teardown warning: delete dealer {d_id} returned {del_res.status_code}")
            except Exception as ex:
                print(f"         teardown error deleting dealer {d_id}: {ex}")

        # 3. Restore inventory modified during testing
        for sku, original_qty in teardown_actions.get("inventory", {}).items():
            try:
                inv_res = S.put(
                    f"{B}/api/inventory/{sku}/",
                    json={"quantity": original_qty, "reason": "smoke test teardown restoration"},
                    timeout=20,
                )
                if inv_res.status_code != 200:
                    print(f"         teardown warning: restore inventory for {sku} returned {inv_res.status_code}")
            except Exception as ex:
                print(f"         teardown error restoring inventory for {sku}: {ex}")

    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed.")
    print("Reminder: this checks the contract basics only. It is not your score.\n")
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()
