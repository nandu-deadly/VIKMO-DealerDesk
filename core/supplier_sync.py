import time
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
import requests
from django.conf import settings
from django.db import transaction
from django.utils.dateparse import parse_datetime

from core.models import Product, Inventory
from core.exceptions import SupplierUnavailableException

logger = logging.getLogger(__name__)


class SupplierSyncService:
    """Implements supplier catalogue synchronization according to API_CONTRACT.md section 8.
    
    Rules:
    1. Fetch every page, following next_cursor until null.
    2. Retries: on 429 wait Retry-After then retry. On 5xx/connection error retry after short backoff.
       Each request attempted at most 5 times.
    3. All or nothing: if any request fails after 5 attempts or key rejected (401), change nothing
       and raise SupplierUnavailableException (502).
    4. Invalid items (missing/empty sku, or price not a positive amount with <= 2 decimals) skipped
       and recorded in rejected.
    5. Duplicates across pages: keep version with latest updated_at.
    6. Apply to DB:
       - not in catalogue -> create with stock 0 (created)
       - exists, and any of name, category, brand, vehicle_fitment, description, price differs -> update (updated)
       - otherwise -> unchanged
    7. Never change stock (supplier_stock is supplier's quantity, not ours).
    8. Idempotent.
    """

    MAX_RETRIES = 5
    BACKOFF_BASE = 0.5

    @classmethod
    def _validate_price(cls, price_val: any) -> tuple[bool, Decimal | None]:
        if price_val is None:
            return False, None
        try:
            p_str = str(price_val).strip()
            # check at most 2 decimals
            if "." in p_str:
                decimals = len(p_str.split(".")[1])
                if decimals > 2:
                    return False, None
            dec = Decimal(p_str)
            if dec <= Decimal("0.00"):
                return False, None
            return True, dec
        except (InvalidOperation, ValueError, TypeError):
            return False, None

    @classmethod
    def sync_catalogue(cls, base_url: str = None, api_key: str = None) -> dict:
        url = (base_url or getattr(settings, "SUPPLIER_API_URL", "http://127.0.0.1:8099")).rstrip("/")
        key = api_key if api_key is not None else getattr(settings, "SUPPLIER_API_KEY", "")

        cursor = None
        pages_fetched = 0
        requests_made = 0

        raw_items_list = []
        session = requests.Session()

        # Step 1 & 2: Fetch every page with retry logic
        while True:
            endpoint = f"{url}/v1/products"
            params = {"limit": 20}
            if cursor:
                params["cursor"] = cursor
            headers = {"X-Api-Key": key}

            page_data = None
            attempt = 0

            while attempt < cls.MAX_RETRIES:
                attempt += 1
                requests_made += 1
                try:
                    resp = session.get(endpoint, params=params, headers=headers, timeout=20)
                    if resp.status_code == 200:
                        page_data = resp.json()
                        break
                    elif resp.status_code == 401:
                        logger.error("Supplier rejected API key (401).")
                        raise SupplierUnavailableException("Supplier API key invalid or rejected.")
                    elif resp.status_code == 429:
                        retry_after = resp.headers.get("Retry-After")
                        wait_seconds = float(retry_after) if retry_after else 1.0
                        logger.warning(f"Supplier 429 received. Waiting {wait_seconds}s before attempt {attempt + 1}")
                        time.sleep(wait_seconds)
                    elif resp.status_code in (500, 502, 503, 504):
                        wait_seconds = cls.BACKOFF_BASE * (2 ** (attempt - 1))
                        logger.warning(f"Supplier {resp.status_code} received. Waiting {wait_seconds}s before attempt {attempt + 1}")
                        time.sleep(wait_seconds)
                    else:
                        logger.error(f"Supplier unexpected status {resp.status_code}.")
                        raise SupplierUnavailableException(f"Supplier API returned unexpected status {resp.status_code}.")
                except requests.RequestException as e:
                    if attempt >= cls.MAX_RETRIES:
                        logger.error(f"Supplier connection failed after {cls.MAX_RETRIES} attempts: {e}")
                        raise SupplierUnavailableException(f"Supplier connection failed: {e}")
                    wait_seconds = cls.BACKOFF_BASE * (2 ** (attempt - 1))
                    logger.warning(f"Supplier request exception {e}. Waiting {wait_seconds}s before attempt {attempt + 1}")
                    time.sleep(wait_seconds)

            if page_data is None:
                raise SupplierUnavailableException("Supplier request failed after maximum retry attempts.")

            pages_fetched += 1
            items = page_data.get("items", [])
            raw_items_list.extend(items)

            cursor = page_data.get("next_cursor")
            if not cursor:
                break

        # Step 4: Validate items and record rejected
        rejected = []
        valid_items_raw = []

        for item in raw_items_list:
            supplier_sku = item.get("supplier_sku") or ""
            sku = (item.get("sku") or "").strip()
            price_val = item.get("price")

            if not sku:
                rejected.append({"supplier_sku": supplier_sku, "reason": "missing sku"})
                continue

            is_valid_price, price_dec = cls._validate_price(price_val)
            if not is_valid_price:
                rejected.append({"supplier_sku": supplier_sku, "reason": "invalid price"})
                continue

            valid_items_raw.append({
                "sku": sku,
                "name": (item.get("name") or "").strip(),
                "category": (item.get("category") or "").strip(),
                "brand": (item.get("brand") or "").strip(),
                "vehicle_fitment": (item.get("vehicle_fitment") or "").strip(),
                "description": (item.get("description") or "").strip(),
                "price": price_dec,
                "updated_at": item.get("updated_at") or "",
                "supplier_sku": supplier_sku,
            })

        # Step 5: Deduplicate items across pages by keeping latest updated_at
        sku_map = {}
        for item in valid_items_raw:
            sku = item["sku"]
            if sku not in sku_map:
                sku_map[sku] = item
            else:
                existing_updated = sku_map[sku]["updated_at"]
                current_updated = item["updated_at"]
                # Compare timestamps
                t_exist = parse_datetime(existing_updated) if existing_updated else None
                t_curr = parse_datetime(current_updated) if current_updated else None

                if t_exist and t_curr:
                    if t_curr > t_exist:
                        sku_map[sku] = item
                elif current_updated > existing_updated:
                    sku_map[sku] = item

        # Step 6 & 7: Apply to database inside an atomic transaction
        created_count = 0
        updated_count = 0
        unchanged_count = 0

        with transaction.atomic():
            existing_products = {
                p.sku: p
                for p in Product.objects.filter(sku__in=sku_map.keys())
            }

            products_to_create = []
            inventories_to_create = []

            for sku, data in sku_map.items():
                if sku not in existing_products:
                    prod = Product(
                        sku=sku,
                        name=data["name"],
                        category=data["category"],
                        brand=data["brand"],
                        vehicle_fitment=data["vehicle_fitment"],
                        description=data["description"],
                        price=data["price"],
                    )
                    products_to_create.append(prod)
                    inventories_to_create.append(Inventory(product=prod, quantity=0))
                    created_count += 1
                else:
                    existing = existing_products[sku]
                    differs = (
                        existing.name != data["name"]
                        or existing.category != data["category"]
                        or existing.brand != data["brand"]
                        or existing.vehicle_fitment != data["vehicle_fitment"]
                        or existing.description != data["description"]
                        or existing.price != data["price"]
                    )
                    if differs:
                        existing.name = data["name"]
                        existing.category = data["category"]
                        existing.brand = data["brand"]
                        existing.vehicle_fitment = data["vehicle_fitment"]
                        existing.description = data["description"]
                        existing.price = data["price"]
                        existing.save()
                        updated_count += 1
                    else:
                        unchanged_count += 1

            if products_to_create:
                Product.objects.bulk_create(products_to_create)
                Inventory.objects.bulk_create(inventories_to_create)

        return {
            "created": created_count,
            "updated": updated_count,
            "unchanged": unchanged_count,
            "rejected": rejected,
            "pages_fetched": pages_fetched,
            "requests_made": requests_made,
        }

