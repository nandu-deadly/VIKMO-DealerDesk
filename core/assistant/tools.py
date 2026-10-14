from typing import Any
from django.db.models import Q
from core.models import Product, Dealer
from core.order_service import OrderService
from core.exceptions import AppAPIException


def search_parts(query: str = "", vehicle: str = None, category: str = None) -> list[dict]:
    """Search catalogue products by text, vehicle fitment, or category using Hybrid RAG.
    Returns up to 5 matching products with live catalogue price, stock, and fitment metadata.
    """
    from core.assistant.retrieval import hybrid_search_parts
    return hybrid_search_parts(query=query, vehicle=vehicle, category=category, limit=5)



def check_stock(sku: str) -> dict:
    """Check current real-time inventory quantity and catalogue price for a specific SKU."""
    if not sku:
        return {"error": "SKU parameter is required."}

    clean_sku = sku.strip()
    try:
        p = Product.objects.select_related("inventory").get(sku=clean_sku)
        return {
            "sku": p.sku,
            "name": p.name,
            "price": f"{p.price:.2f}",
            "stock": p.stock,
            "vehicle_fitment": p.vehicle_fitment,
        }
    except Product.DoesNotExist:
        return {"error": f"Product with SKU '{clean_sku}' not found in catalogue."}


def create_draft_order(dealer_id: int, items: list[dict]) -> dict:
    """Create a DRAFT order for the dealer using live database catalogue prices.
    Items format: [{'sku': '...', 'quantity': int}]
    """
    if not dealer_id:
        return {"error": "dealer_id is required."}

    if not items or not isinstance(items, list):
        return {"error": "items must be a non-empty list."}

    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            return {"error": f"Item at index {idx} must be an object with 'sku' and 'quantity'."}
        sku = item.get("sku")
        qty = item.get("quantity")
        if not sku or not isinstance(sku, str):
            return {"error": f"Item at index {idx} missing or invalid 'sku'."}
        clean_sku = sku.strip()
        if qty is None or not isinstance(qty, int) or isinstance(qty, bool) or qty < 1:
            return {"error": f"Item '{clean_sku}' quantity must be an integer >= 1."}
        try:
            prod = Product.objects.get(sku=clean_sku)
        except Product.DoesNotExist:
            return {"error": f"Product with SKU '{clean_sku}' not found in catalogue."}

    try:
        order, _ = OrderService.create_order(dealer_id=dealer_id, items_data=items)
        return {
            "type": "draft_order_created",
            "order_number": order.order_number,
            "dealer_id": order.dealer_id,
            "status": order.status,
            "subtotal": f"{order.subtotal:.2f}",
            "tax_total": f"{order.tax_total:.2f}",
            "grand_total": f"{order.grand_total:.2f}",
            "items_count": order.items.count(),
        }
    except AppAPIException as e:
        return {"error": e.message}
    except Exception as e:
        return {"error": str(e)}
