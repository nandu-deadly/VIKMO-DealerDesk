import csv
from pathlib import Path
from decimal import Decimal
from core.models import Product, Inventory

catalogue_path = Path("data/catalogue.csv")
assert catalogue_path.exists(), f"Catalogue not found: {catalogue_path}"

with catalogue_path.open(encoding="utf-8-sig", newline="") as f:
    rows = list(csv.DictReader(f))

expected = {r["sku"]: int(r["stock"]) for r in rows}

live_rows = list(
    Inventory.objects.select_related("product").values_list(
        "product__sku", "quantity"
    )
)
live = dict(live_rows)

missing = sorted(set(expected) - set(live))
extra = sorted(set(live) - set(expected))
mismatches = [
    (sku, expected[sku], live[sku])
    for sku in sorted(set(expected) & set(live))
    if expected[sku] != live[sku]
]

print("=== LIVE STOCK AUDIT ===")
print("Catalogue SKUs:", len(expected))
print("Live inventory records:", len(live_rows))
print("Unique live SKUs:", len(live))
print("Expected starting stock total:", sum(expected.values()))
print("Current live stock total:", sum(live.values()))
print("Missing inventory SKUs:", len(missing))
print("Unexpected inventory SKUs:", len(extra))
print("Stock quantity differences:", len(mismatches))

if missing:
    print("\nMISSING:", missing[:50])
if extra:
    print("\nUNEXPECTED:", extra[:50])
if mismatches:
    print("\nSKU | EXPECTED STARTING STOCK | LIVE STOCK")
    for sku, expected_qty, live_qty in mismatches[:100]:
        print(f"{sku} | {expected_qty} | {live_qty}")

if not missing and not extra and not mismatches:
    print("\nRESULT: PASS - live quantities match the starting catalogue.")
else:
    print("\nRESULT: DIFFERENCES FOUND - review before changing stock.")
