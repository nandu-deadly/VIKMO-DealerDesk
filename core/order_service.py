import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
import zoneinfo
from django.db import transaction, IntegrityError
from django.utils import timezone

from core.models import Product, Inventory, Dealer, Order, OrderItem, OrderStatus, IdempotencyRecord
from core.exceptions import (
    AppAPIException,
    NotFoundException,
    InvalidTransitionException,
    OrderLockedException,
    InsufficientStockException,
    IdempotencyConflictException,
)


class OrderService:
    @staticmethod
    def _compute_hash(raw_body: bytes | str | dict) -> str:
        if isinstance(raw_body, dict):
            content = json.dumps(raw_body, sort_keys=True)
        elif isinstance(raw_body, bytes):
            content = raw_body.decode("utf-8")
        else:
            content = str(raw_body)
        return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()

    @classmethod
    def create_order(
        cls,
        dealer_id: int,
        items_data: list[dict],
        idempotency_key: str = None,
        raw_body: Any = None,
    ) -> tuple[Order, bool]:
        if idempotency_key:
            current_hash = cls._compute_hash(
                raw_body if raw_body is not None else {"dealer_id": dealer_id, "items": items_data}
            )
            existing_rec = IdempotencyRecord.objects.select_related("order").filter(key=idempotency_key).first()
            if existing_rec:
                if existing_rec.body_hash == current_hash:
                    return existing_rec.order, False
                else:
                    raise IdempotencyConflictException("Idempotency key reused with different request body.")

        if not dealer_id:
            raise AppAPIException(code="VALIDATION_ERROR", message="Field 'dealer_id' is required.")

        try:
            dealer = Dealer.objects.get(id=dealer_id)
        except (Dealer.DoesNotExist, ValueError):
            raise AppAPIException(code="VALIDATION_ERROR", message=f"Dealer with id {dealer_id} does not exist.")

        if hasattr(dealer, "is_active") and not dealer.is_active:
            raise AppAPIException(code="VALIDATION_ERROR", message=f"Dealer '{dealer.dealer_code}' is inactive or unauthorized to place orders.")

        if not isinstance(items_data, list) or len(items_data) == 0:
            raise AppAPIException(code="VALIDATION_ERROR", message="Order must contain at least one item.")

        seen_skus = set()
        validated_items = []
        for idx, item in enumerate(items_data):
            if not isinstance(item, dict):
                raise AppAPIException(code="VALIDATION_ERROR", message=f"Item at index {idx} must be an object.")

            sku = item.get("sku")
            quantity = item.get("quantity")

            if not sku or not isinstance(sku, str):
                raise AppAPIException(code="VALIDATION_ERROR", message=f"Item at index {idx} missing 'sku'.")

            sku = sku.strip()
            if sku in seen_skus:
                raise AppAPIException(code="VALIDATION_ERROR", message=f"Duplicate SKU '{sku}' in order items.")
            seen_skus.add(sku)

            if quantity is None or not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
                raise AppAPIException(code="VALIDATION_ERROR", message=f"Item '{sku}' quantity must be an integer >= 1.")

            try:
                product = Product.objects.get(sku=sku)
            except Product.DoesNotExist:
                raise AppAPIException(code="VALIDATION_ERROR", message=f"Product with SKU '{sku}' not found.")

            validated_items.append({"product": product, "quantity": quantity})

        kolkata_tz = zoneinfo.ZoneInfo("Asia/Kolkata")
        now_kolkata = timezone.now().astimezone(kolkata_tz)
        date_str = now_kolkata.strftime("%Y%m%d")
        today_prefix = f"ORD-{date_str}-"

        # Retry loop for concurrency safety
        max_attempts = 10
        for attempt in range(max_attempts):
            try:
                with transaction.atomic():
                    # If idempotency_key is provided, re-check and lock inside the transaction
                    if idempotency_key:
                        existing_rec = (
                            IdempotencyRecord.objects.select_related("order")
                            .filter(key=idempotency_key)
                            .first()
                        )
                        if existing_rec:
                            current_hash = cls._compute_hash(
                                raw_body if raw_body is not None else {"dealer_id": dealer_id, "items": items_data}
                            )
                            if existing_rec.body_hash == current_hash:
                                return existing_rec.order, False
                            else:
                                raise IdempotencyConflictException("Idempotency key reused with different request body.")

                    last_order = (
                        Order.objects.filter(order_number__startswith=today_prefix)
                        .select_for_update()
                        .order_by("-order_number")
                        .first()
                    )
                    if last_order:
                        try:
                            last_seq = int(last_order.order_number.split("-")[-1])
                            seq = last_seq + 1
                        except (ValueError, IndexError):
                            seq = Order.objects.filter(order_number__startswith=today_prefix).count() + 1
                    else:
                        seq = 1

                    order_number = f"ORD-{date_str}-{seq:04d}"

                    subtotal = Decimal("0.00")
                    tax_total = Decimal("0.00")
                    order_items_to_create = []

                    for item_info in validated_items:
                        product = item_info["product"]
                        qty = item_info["quantity"]
                        unit_price = product.price

                        line_subtotal = unit_price * qty
                        line_tax = (line_subtotal * Decimal("0.18")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                        line_total = line_subtotal + line_tax

                        subtotal += line_subtotal
                        tax_total += line_tax

                        order_items_to_create.append({
                            "product": product,
                            "sku": product.sku,
                            "name": product.name,
                            "quantity": qty,
                            "unit_price": unit_price,
                            "line_subtotal": line_subtotal,
                            "line_tax": line_tax,
                            "line_total": line_total,
                        })

                    grand_total = subtotal + tax_total

                    order = Order.objects.create(
                        order_number=order_number,
                        dealer=dealer,
                        status=OrderStatus.DRAFT,
                        subtotal=subtotal,
                        tax_total=tax_total,
                        grand_total=grand_total,
                    )

                    for oi_data in order_items_to_create:
                        OrderItem.objects.create(order=order, **oi_data)

                    if idempotency_key:
                        current_hash = cls._compute_hash(
                            raw_body if raw_body is not None else {"dealer_id": dealer_id, "items": items_data}
                        )
                        IdempotencyRecord.objects.create(
                            key=idempotency_key,
                            body_hash=current_hash,
                            order=order,
                        )

                    return order, True

            except IntegrityError as ie:
                # If another concurrent request created the idempotency record first:
                if idempotency_key:
                    existing_rec = (
                        IdempotencyRecord.objects.select_related("order")
                        .filter(key=idempotency_key)
                        .first()
                    )
                    if existing_rec:
                        current_hash = cls._compute_hash(
                            raw_body if raw_body is not None else {"dealer_id": dealer_id, "items": items_data}
                        )
                        if existing_rec.body_hash == current_hash:
                            return existing_rec.order, False
                        else:
                            raise IdempotencyConflictException("Idempotency key reused with different request body.")

                if attempt == max_attempts - 1:
                    raise

        raise AppAPIException("Failed to allocate unique order number after multiple attempts.")

    @classmethod
    def edit_order(cls, order_number: str, items_data: list[dict]) -> Order:
        with transaction.atomic():
            try:
                order = Order.objects.select_for_update().get(order_number=order_number)
            except Order.DoesNotExist:
                raise NotFoundException(f"Order '{order_number}' not found.")

            if order.status != OrderStatus.DRAFT:
                raise OrderLockedException("Editing an order that is not DRAFT.")

            if not isinstance(items_data, list) or len(items_data) == 0:
                raise AppAPIException(code="VALIDATION_ERROR", message="Order must contain at least one item.")

            seen_skus = set()
            validated_items = []
            for idx, item in enumerate(items_data):
                sku = item.get("sku")
                quantity = item.get("quantity")
                if not sku or not isinstance(sku, str):
                    raise AppAPIException(code="VALIDATION_ERROR", message=f"Item at index {idx} missing 'sku'.")

                sku = sku.strip()
                if sku in seen_skus:
                    raise AppAPIException(code="VALIDATION_ERROR", message=f"Duplicate SKU '{sku}' in order items.")
                seen_skus.add(sku)

                if quantity is None or not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
                    raise AppAPIException(code="VALIDATION_ERROR", message=f"Item '{sku}' quantity must be an integer >= 1.")

                try:
                    product = Product.objects.get(sku=sku)
                except Product.DoesNotExist:
                    raise AppAPIException(code="VALIDATION_ERROR", message=f"Product with SKU '{sku}' not found.")

                validated_items.append({"product": product, "quantity": quantity})

            order.items.all().delete()

            subtotal = Decimal("0.00")
            tax_total = Decimal("0.00")

            for item_info in validated_items:
                product = item_info["product"]
                qty = item_info["quantity"]
                unit_price = product.price

                line_subtotal = unit_price * qty
                line_tax = (line_subtotal * Decimal("0.18")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                line_total = line_subtotal + line_tax

                subtotal += line_subtotal
                tax_total += line_tax

                OrderItem.objects.create(
                    order=order,
                    product=product,
                    sku=product.sku,
                    name=product.name,
                    quantity=qty,
                    unit_price=unit_price,
                    line_subtotal=line_subtotal,
                    line_tax=line_tax,
                    line_total=line_total,
                )

            order.subtotal = subtotal
            order.tax_total = tax_total
            order.grand_total = subtotal + tax_total
            order.save()

        return order

    @classmethod
    def confirm_order(cls, order_number: str, confirmed_by_user=None) -> Order:
        with transaction.atomic():
            try:
                order = Order.objects.select_for_update().prefetch_related("items").get(order_number=order_number)
            except Order.DoesNotExist:
                raise NotFoundException(f"Order '{order_number}' not found.")

            if order.status != OrderStatus.DRAFT:
                raise InvalidTransitionException(f"Cannot confirm order in status '{order.status}'.")

            order_items = list(order.items.all())
            product_skus = [oi.sku for oi in order_items]

            inventories = {
                inv.product_id: inv
                for inv in Inventory.objects.select_for_update().filter(product_id__in=product_skus)
            }

            short_lines = []
            messages = []
            for oi in order_items:
                inv = inventories.get(oi.sku)
                available = inv.quantity if inv else 0
                if available < oi.quantity:
                    short_lines.append({"sku": oi.sku, "requested": oi.quantity, "available": available})
                    messages.append(f"Insufficient stock for {oi.name}. Available: {available}, Requested: {oi.quantity}")

            if short_lines:
                raise InsufficientStockException(message=" ".join(messages), details=short_lines)

            for oi in order_items:
                inv = inventories[oi.sku]
                inv.quantity -= oi.quantity
                inv.save(update_fields=["quantity"])

            order.status = OrderStatus.CONFIRMED
            if confirmed_by_user and getattr(confirmed_by_user, "is_authenticated", False):
                order.confirmed_by = confirmed_by_user
                order.confirmed_at = timezone.now()
                order.save(update_fields=["status", "updated_at", "confirmed_by", "confirmed_at"])
            else:
                order.save(update_fields=["status", "updated_at"])

        return order

    @classmethod
    def dispatch_order(cls, order_number: str) -> Order:
        with transaction.atomic():
            try:
                order = Order.objects.select_for_update().get(order_number=order_number)
            except Order.DoesNotExist:
                raise NotFoundException(f"Order '{order_number}' not found.")

            if order.status != OrderStatus.CONFIRMED:
                raise InvalidTransitionException(f"Cannot dispatch order in status '{order.status}'.")

            order.status = OrderStatus.DISPATCHED
            order.save(update_fields=["status", "updated_at"])

        return order

    @classmethod
    def deliver_order(cls, order_number: str) -> Order:
        with transaction.atomic():
            try:
                order = Order.objects.select_for_update().get(order_number=order_number)
            except Order.DoesNotExist:
                raise NotFoundException(f"Order '{order_number}' not found.")

            if order.status != OrderStatus.DISPATCHED:
                raise InvalidTransitionException(f"Cannot deliver order in status '{order.status}'.")

            order.status = OrderStatus.DELIVERED
            order.save(update_fields=["status", "updated_at"])

        return order

    @classmethod
    def cancel_order(cls, order_number: str) -> Order:
        with transaction.atomic():
            try:
                order = Order.objects.select_for_update().prefetch_related("items").get(order_number=order_number)
            except Order.DoesNotExist:
                raise NotFoundException(f"Order '{order_number}' not found.")

            if order.status == OrderStatus.DRAFT:
                order.status = OrderStatus.CANCELLED
                order.save(update_fields=["status", "updated_at"])
                return order

            elif order.status == OrderStatus.CONFIRMED:
                order_items = list(order.items.all())
                product_skus = [oi.sku for oi in order_items]

                inventories = {
                    inv.product_id: inv
                    for inv in Inventory.objects.select_for_update().filter(product_id__in=product_skus)
                }

                for oi in order_items:
                    inv = inventories.get(oi.sku)
                    if inv:
                        inv.quantity += oi.quantity
                        inv.save(update_fields=["quantity"])

                order.status = OrderStatus.CANCELLED
                order.save(update_fields=["status", "updated_at"])
                return order

            else:
                raise InvalidTransitionException(f"Cannot cancel order in status '{order.status}'.")

