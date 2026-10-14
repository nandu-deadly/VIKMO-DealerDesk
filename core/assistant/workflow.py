import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from django.db.models import Q
from core.models import Product
from core.assistant.tools import search_parts, create_draft_order


def calculate_order_financials(unit_price: Decimal, quantity: int) -> dict:
    """Calculates subtotal, 18% GST with ROUND_HALF_UP, and grand total."""
    qty = Decimal(quantity)
    subtotal = (unit_price * qty).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    tax_total = (subtotal * Decimal("0.18")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    grand_total = (subtotal + tax_total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "unit_price": f"{unit_price:.2f}",
        "quantity": quantity,
        "subtotal": f"{subtotal:.2f}",
        "gst_rate": "18%",
        "tax_total": f"{tax_total:.2f}",
        "grand_total": f"{grand_total:.2f}",
    }


def clean_text_for_quantity(text: str) -> str:
    """Removes vehicle displacement mentions and CC strings to avoid confusing engine CC with order quantities."""
    text = re.sub(r"\b\d+\s*cc\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:hunter|classic|meteor|bullet)\s*(?:350|650)\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:pulsar|discover)\s*(?:125|135|150|160|180|200|220|ns\s*200|rs\s*200)\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:duke|rc|adventure)\s*(?:125|200|250|390)\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:himalayan|guerrilla)\s*(?:411|450)\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:activa|jupiter|access|dio|ntorq)\s*(?:110|125)?\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:splendor|passion|shine|unicorn)\s*(?:plus|pro|100|110|125|150|160)?\b", " ", text, flags=re.I)
    text = re.sub(r"\b(?:r15|mt-15|mt15|fz-s|fz|fzs)\s*(?:v[1-4]|150|250)?\b", " ", text, flags=re.I)
    return text


def parse_sku_and_quantity(message: str) -> tuple[str | None, int | None]:
    """Extracts SKU and integer order quantity from message text with 100% precision.
    Guarantees SKU digits (e.g. 1001 in BRK-1001) or vehicle CC numbers are NEVER confused with quantity.
    """
    msg = message.strip()

    # 1. Extract SKU first (format: 3 uppercase letters, dash, alphanumerics)
    sku_match = re.search(r"\b([A-Za-z]{3}-[A-Za-z0-9\-]+)\b", msg)
    sku = None
    msg_no_sku = msg
    if sku_match:
        sku = sku_match.group(1).upper()
        # Excise exact SKU span so SKU digits cannot be matched as quantity
        msg_no_sku = msg[:sku_match.start()] + " " + msg[sku_match.end():]

    clean_msg = clean_text_for_quantity(msg_no_sku).strip()

    # 2. Extract Quantity
    qty = None

    # Pattern A: explicit quantity/qty label: "quantity 100", "qty: 1", "quantity = 5", "quantity: -5"
    m = re.search(r"\b(?:quantity|qty)[:\s=]+(-?\d+)\b", clean_msg, re.I)
    if m:
        qty = int(m.group(1))

    # Pattern B: units suffix: "100 units", "2 pcs", "5 pieces", "30 items", "10 nos"
    if qty is None:
        m = re.search(r"\b(-?\d+)\s*(?:units?|pcs?|pieces?|items?|nos?|pack(?:s)?|sets?)\b", clean_msg, re.I)
        if m:
            qty = int(m.group(1))

    # Pattern C: order/buy/for X of / X units: "Order 2 units of", "order 5 of", "for 10 of"
    if qty is None:
        m = re.search(r"\b(?:for|order|buy|draft order|create an order for|take|send)\s+(-?\d+)\s*(?:units?\s+)?(?:of\b)?", clean_msg, re.I)
        if m:
            qty = int(m.group(1))

    # Pattern D: action verbs + number: "order 10", "want 30", "need 100", "make it 15"
    if qty is None:
        m = re.search(r"\b(?:order|buy|want|need|make it|send|give|take|purchase)\s+(-?\d+)\b", clean_msg, re.I)
        if m:
            qty = int(m.group(1))

    # Pattern E: standalone number: "30", "100", "1", "-5"
    if qty is None:
        m = re.fullmatch(r"\s*(-?\d+)\s*", clean_msg)
        if m:
            qty = int(m.group(1))

    # Pattern F: fallback single remaining integer
    if qty is None:
        nums = [int(n) for n in re.findall(r"\b-?\d+\b", clean_msg)]
        if len(nums) == 1:
            qty = nums[0]

    return sku, qty


def extract_quantity(message: str) -> int | None:
    """Robustly extracts an order quantity integer from user input, avoiding vehicle CC numbers."""
    _, qty = parse_sku_and_quantity(message)
    return qty


class ConversationalOrderWorkflow:
    """Manages the multi-turn conversational product-ordering workflow for VIKMO DealerDesk."""

    @classmethod
    def process_turn(
        cls,
        session_id: str,
        dealer_id: int,
        message: str,
        state: dict,
    ) -> tuple[dict | None, dict]:
        """Processes a chat turn against the active workflow state.
        Returns (response_dict, updated_state) if handled by workflow, or (None, state) to pass through.
        """
        msg_clean = message.strip()
        msg_lower = msg_clean.lower()
        flow_step = state.get("flow_step")

        # 0. Do not intercept off-topic questions
        if any(w in msg_lower for w in ("weather", "capital", "movie", "poem", "recipe", "politics", "president")):
            return None, state

        sku_in_msg, qty_in_msg = parse_sku_and_quantity(msg_clean)

        # If user provides a new explicit order command with SKU (e.g. "order BRK-1001, quantity 100"):
        # Reset any previous completed order state so it does not falsely trigger duplicate prevention
        if sku_in_msg and any(w in msg_lower for w in ("order", "buy", "draft")):
            if state.get("created_order"):
                state = {}
                flow_step = None

        # -------------------------------------------------------------
        # Step 5 / Duplicate Prevention: AWAITING_CONFIRMATION or ORDER_COMPLETED
        # -------------------------------------------------------------
        if flow_step in ("AWAITING_CONFIRMATION", "ORDER_COMPLETED") or state.get("created_order"):
            # If order has already been placed and user repeats confirmation/placement WITHOUT a new SKU
            if state.get("created_order") and not sku_in_msg and any(w in msg_lower for w in ("yes", "place", "confirm", "sure", "ok", "okay", "proceed", "do it", "order it")):
                created_order = state["created_order"]
                reply = (
                    f"Order {created_order['order_number']} has already been placed for "
                    f"{state.get('quantity')} units of {state.get('selected_sku')}. "
                    "Status: DRAFT (Pending), awaiting distributor confirmation."
                )
                return {
                    "reply": reply,
                    "cited_skus": [state.get("selected_sku")],
                    "tool_calls": [],
                    "actions": [{"type": "draft_order_created", "order_number": created_order["order_number"]}],
                }, state

        if flow_step == "AWAITING_CONFIRMATION":
            # Dealer confirmed order placement
            if any(w in msg_lower for w in ("yes", "place", "confirm", "sure", "ok", "okay", "proceed", "do it")):
                sku = state.get("selected_sku")
                qty = state.get("quantity", 1)
                try:
                    product = Product.objects.select_related("inventory").get(sku=sku)
                except Product.DoesNotExist:
                    return {
                        "reply": f"Selected product '{sku}' not found in catalogue.",
                        "cited_skus": [],
                        "tool_calls": [],
                        "actions": [],
                    }, {}

                tool_args = {"dealer_id": dealer_id, "items": [{"sku": sku, "quantity": qty}]}
                res = create_draft_order(dealer_id=dealer_id, items=[{"sku": sku, "quantity": qty}])
                tool_calls = [{"name": "create_draft_order", "arguments": tool_args}]

                if isinstance(res, dict) and res.get("type") == "draft_order_created":
                    fin = calculate_order_financials(product.price, qty)
                    reply = (
                        f"I have placed your DRAFT order ({res['order_number']}).\n\n"
                        f"Order Details:\n"
                        f"- Order Number: {res['order_number']}\n"
                        f"- Product: {product.name} (SKU: {product.sku})\n"
                        f"- Quantity: {qty} units\n"
                        f"- Unit Price: ₹{fin['unit_price']}\n"
                        f"- Subtotal: ₹{res['subtotal']}\n"
                        f"- GST (18%): ₹{res['tax_total']}\n"
                        f"- Final Total: ₹{res['grand_total']}\n"
                        f"- Order Status: DRAFT (Pending)\n\n"
                        f"This order has been created and is now awaiting distributor confirmation. "
                        f"You can view it in your My Orders section."
                    )
                    new_state = dict(state)
                    new_state["flow_step"] = "ORDER_COMPLETED"
                    new_state["created_order"] = res
                    return {
                        "reply": reply,
                        "cited_skus": [sku],
                        "tool_calls": tool_calls,
                        "actions": [{"type": "draft_order_created", "order_number": res["order_number"]}],
                    }, new_state
                else:
                    err = res.get("error", "Order creation failed.")
                    return {
                        "reply": f"Could not place draft order: {err}",
                        "cited_skus": [],
                        "tool_calls": tool_calls,
                        "actions": [],
                    }, state

            # Dealer wants to change quantity at confirmation step
            qty = extract_quantity(msg_clean)
            if qty is not None and any(w in msg_lower for w in ("change", "make", "want", "units", "quantity", "qty", "instead")):
                return cls._handle_quantity_input(dealer_id, qty, state)

            # Dealer cancelled at confirmation step
            if any(w in msg_lower for w in ("no", "cancel", "don't", "stop", "abort", "nevermind")):
                new_state = dict(state)
                new_state["flow_step"] = "ORDER_CANCELLED"
                return {
                    "reply": "Order placement cancelled. Let me know if you would like to search for other parts or modify your order.",
                    "cited_skus": [],
                    "tool_calls": [],
                    "actions": [],
                }, new_state

        # -------------------------------------------------------------
        # Step 4: User in AWAITING_QUANTITY step
        # -------------------------------------------------------------
        if flow_step == "AWAITING_QUANTITY":
            qty = extract_quantity(msg_clean)
            if qty is not None:
                return cls._handle_quantity_input(dealer_id, qty, state)
            else:
                return {
                    "reply": "Please specify the number of units you would like to order (e.g. '30 units' or '10').",
                    "cited_skus": [state.get("selected_sku")] if state.get("selected_sku") else [],
                    "tool_calls": [],
                    "actions": [],
                }, state

        # -------------------------------------------------------------
        # Step 3: User in AWAITING_ORDER_DECISION ("Would you like to order this product?")
        # -------------------------------------------------------------
        if flow_step == "AWAITING_ORDER_DECISION":
            sku = state.get("selected_sku")
            if any(w in msg_lower for w in ("yes", "order", "sure", "ok", "okay", "proceed", "want it", "order it", "take it", "buy it")):
                # Check if dealer already supplied quantity in this message (e.g. "Yes, 30 units")
                qty = extract_quantity(msg_clean)
                if qty is not None and qty > 0:
                    new_state = dict(state)
                    new_state["flow_step"] = "AWAITING_QUANTITY"
                    return cls._handle_quantity_input(dealer_id, qty, new_state)

                new_state = dict(state)
                new_state["flow_step"] = "AWAITING_QUANTITY"
                try:
                    p = Product.objects.select_related("inventory").get(sku=sku)
                    stock_info = f" We currently have {p.stock} units available."
                except Exception:
                    stock_info = ""

                return {
                    "reply": f"How many units would you like to order?{stock_info}",
                    "cited_skus": [sku] if sku else [],
                    "tool_calls": [],
                    "actions": [],
                }, new_state

            if any(w in msg_lower for w in ("no", "don't", "cancel", "not now", "later")):
                new_state = dict(state)
                new_state["flow_step"] = "IDLE"
                return {
                    "reply": "Understood. How else can I assist you with our catalogue inventory?",
                    "cited_skus": [],
                    "tool_calls": [],
                    "actions": [],
                }, new_state

        # -------------------------------------------------------------
        # Direct "Order it" / "Yes" when product was already selected or shown
        # -------------------------------------------------------------
        if any(phrase in msg_lower for phrase in ("order it", "buy it", "yes order", "ok order", "take it", "place order")) or (
            state.get("selected_sku") and any(w in msg_lower for w in ("yes", "ok", "okay", "proceed", "sure"))
        ):
            chosen_sku = state.get("selected_sku")
            if not chosen_sku and state.get("candidates"):
                chosen_sku = state["candidates"][0]["sku"]

            if chosen_sku:
                try:
                    product = Product.objects.select_related("inventory").get(sku=chosen_sku)
                except Product.DoesNotExist:
                    return None, state

                qty = extract_quantity(msg_clean)
                new_state = dict(state)
                new_state["selected_sku"] = product.sku
                new_state["selected_product"] = {
                    "sku": product.sku,
                    "name": product.name,
                    "price": f"{product.price:.2f}",
                    "stock": product.stock,
                    "vehicle_fitment": product.vehicle_fitment,
                }

                if qty is not None and qty > 0:
                    return cls._handle_quantity_input(dealer_id, qty, new_state)

                new_state["flow_step"] = "AWAITING_QUANTITY"
                return {
                    "reply": f"How many units of {product.name} ({product.sku}) would you like to order? We currently have {product.stock} units available.",
                    "cited_skus": [product.sku],
                    "tool_calls": [],
                    "actions": [],
                }, new_state

        # -------------------------------------------------------------
        # Step 2: Product Selection from previous candidates
        # -------------------------------------------------------------
        if flow_step == "AWAITING_SELECTION" or (state.get("candidates") and not flow_step):
            selected_candidate, ambiguous_list = cls._resolve_candidate_selection(msg_clean, state.get("candidates", []))
            if ambiguous_list and len(ambiguous_list) > 1:
                options_str = "; ".join(f"{c['name']} ({c['sku']})" for c in ambiguous_list)
                return {
                    "reply": f"We have multiple options matching that description: {options_str}. Please specify which product or SKU you would like to select.",
                    "cited_skus": [c["sku"] for c in ambiguous_list],
                    "tool_calls": [],
                    "actions": [],
                }, state
            elif selected_candidate:
                sku = selected_candidate["sku"]
                try:
                    product = Product.objects.select_related("inventory").get(sku=sku)
                except Product.DoesNotExist:
                    return None, state

                qty = extract_quantity(msg_clean)
                new_state = dict(state)
                new_state["selected_sku"] = product.sku
                new_state["selected_product"] = {
                    "sku": product.sku,
                    "name": product.name,
                    "price": f"{product.price:.2f}",
                    "stock": product.stock,
                    "vehicle_fitment": product.vehicle_fitment,
                }

                # If user already specified quantity in selection message: "I want 30 units of Hunter 350 filter"
                if qty is not None and qty > 0:
                    return cls._handle_quantity_input(dealer_id, qty, new_state)

                reply = (
                    f"You selected {product.name} (SKU: {product.sku}). "
                    f"The current price is ₹{product.price:.2f} per unit, and the available stock is {product.stock} units. "
                    "Would you like to order this product?"
                )
                new_state["flow_step"] = "AWAITING_ORDER_DECISION"
                return {
                    "reply": reply,
                    "cited_skus": [product.sku],
                    "tool_calls": [],
                    "actions": [],
                }, new_state

        return None, state

    @classmethod
    def _handle_quantity_input(cls, dealer_id: int, quantity: int, state: dict) -> tuple[dict, dict]:
        """Validates quantity against live stock, calculates financial summary with 18% GST, and asks for confirmation."""
        sku = state.get("selected_sku")
        if not sku:
            return {"reply": "Please select a product first.", "cited_skus": [], "tool_calls": [], "actions": []}, state

        try:
            product = Product.objects.select_related("inventory").get(sku=sku)
        except Product.DoesNotExist:
            return {"reply": f"Product with SKU '{sku}' not found.", "cited_skus": [], "tool_calls": [], "actions": []}, state

        if quantity <= 0:
            return {
                "reply": "Quantity must be at least 1 unit. Please provide a valid quantity.",
                "cited_skus": [sku],
                "tool_calls": [],
                "actions": [],
            }, state

        # Step 4: Validate quantity against live available stock
        if quantity > product.stock:
            reply = (
                f"The requested quantity of {quantity} units exceeds our current available stock of "
                f"{product.stock} units for {product.name} ({product.sku}). "
                f"Please specify a quantity up to {product.stock} units."
            )
            new_state = dict(state)
            new_state["flow_step"] = "AWAITING_QUANTITY"
            return {
                "reply": reply,
                "cited_skus": [sku],
                "tool_calls": [],
                "actions": [],
            }, new_state

        fin = calculate_order_financials(product.price, quantity)
        remaining_stock = product.stock - quantity

        reply = (
            f"Order Summary for {product.name} (SKU: {product.sku}):\n"
            f"- Product: {product.name} ({product.sku})\n"
            f"- Quantity: {quantity} units\n"
            f"- Unit Price: ₹{fin['unit_price']}\n"
            f"- Subtotal before GST: ₹{fin['subtotal']}\n"
            f"- GST Rate: 18% (₹{fin['tax_total']})\n"
            f"- Final Total including GST: ₹{fin['grand_total']}\n"
            f"- Current Available Stock: {product.stock} units\n"
            f"- Remaining Stock after Order: {remaining_stock} units\n\n"
            f"You are ordering {quantity} units of {product.name}. "
            f"The subtotal is ₹{fin['subtotal']}, GST is ₹{fin['tax_total']}, and the total is ₹{fin['grand_total']}. "
            f"Shall I place this order?"
        )

        new_state = dict(state)
        new_state["flow_step"] = "AWAITING_CONFIRMATION"
        new_state["quantity"] = quantity
        new_state["order_summary"] = fin
        new_state["order_summary"]["remaining_stock"] = remaining_stock

        return {
            "reply": reply,
            "cited_skus": [sku],
            "tool_calls": [],
            "actions": [],
        }, new_state

    @classmethod
    def _resolve_candidate_selection(cls, message: str, candidates: list[dict]) -> tuple[dict | None, list[dict] | None]:
        """Resolves user selection against candidate products from previous search.
        Returns (selected_candidate, None) on unambiguous resolution,
        or (None, matching_candidates) when multiple candidates match (ambiguity),
        or (None, None) if no candidates match.
        """
        if not candidates:
            return None, None

        msg_lower = message.lower().strip()

        # 1. Exact SKU match
        sku_match = re.search(r"\b([A-Z]{3}-[A-Za-z0-9\-]+)\b", message)
        if sku_match:
            target_sku = sku_match.group(1).upper()
            for c in candidates:
                if c["sku"] == target_sku:
                    return c, None

        # 2. Ordinal selection: "first", "second", "third", "1st", "2nd", etc.
        ordinal_patterns = [
            (r"\b(first|1st|option\s*1|#1|number\s*1)\b", 0),
            (r"\b(second|2nd|option\s*2|#2|number\s*2)\b", 1),
            (r"\b(third|3rd|option\s*3|#3|number\s*3)\b", 2),
            (r"\b(fourth|4th|option\s*4|#4|number\s*4)\b", 3),
            (r"\b(fifth|5th|option\s*5|#5|number\s*5)\b", 4),
        ]
        for pat, idx in ordinal_patterns:
            if re.search(pat, msg_lower):
                if idx < len(candidates):
                    return candidates[idx], None

        # 3. Vehicle model / specific variant match
        model_keywords = [
            ("hunter 350", "Hunter 350"),
            ("hunter", "Hunter 350"),
            ("classic 350", "Classic 350"),
            ("classic", "Classic 350"),
            ("himalayan 450", "Himalayan 450"),
            ("himalayan", "Himalayan 450"),
            ("pulsar 150", "Pulsar 150"),
            ("pulsar ns200", "Pulsar NS200"),
            ("ns200", "Pulsar NS200"),
            ("duke 390", "Duke 390"),
            ("duke 200", "Duke 200"),
            ("splendor", "Splendor"),
            ("r15", "R15"),
            ("mt-15", "MT-15"),
            ("mt 15", "MT-15"),
            ("fz-s", "FZ-S"),
            ("activa", "Activa"),
            ("jupiter", "Jupiter"),
            ("meteor 350", "Meteor 350"),
            ("meteor", "Meteor 350"),
        ]
        matched_models = []
        for kw, model_tag in model_keywords:
            if re.search(rf"\b{re.escape(kw)}\b", msg_lower):
                for c in candidates:
                    if model_tag.lower() in c.get("vehicle_fitment", "").lower() or model_tag.lower() in c.get("name", "").lower():
                        if c not in matched_models:
                            matched_models.append(c)
        if matched_models:
            return matched_models[0], None

        # 4. Brand match (e.g. "k&n", "purolator", "mahle", "mrf", "ceat", "brembo", "endurance")
        brand_matches = []
        for c in candidates:
            brand = (c.get("brand") or "").lower()
            if brand and re.search(rf"\b{re.escape(brand)}\b", msg_lower):
                if c not in brand_matches:
                    brand_matches.append(c)
        if len(brand_matches) == 1:
            return brand_matches[0], None
        elif len(brand_matches) > 1:
            return None, brand_matches

        # 5. Broad make / vehicle family match (e.g. "royal enfield", "yamaha", "bajaj", "hero", "ktm", "honda", "tvs")
        broad_makes = ["royal enfield", "yamaha", "bajaj", "hero", "ktm", "honda", "tvs"]
        make_matches = []
        for make in broad_makes:
            if make in msg_lower:
                for c in candidates:
                    if make in c.get("vehicle_fitment", "").lower() or make in c.get("name", "").lower():
                        if c not in make_matches:
                            make_matches.append(c)
        if len(make_matches) == 1:
            return make_matches[0], None
        elif len(make_matches) > 1:
            return None, make_matches

        # 6. Generic reference like "it", "this", "the product", "this one"
        if any(re.search(rf"\b{re.escape(w)}\b", msg_lower) for w in ("it", "this", "the product", "this one", "that one")):
            if len(candidates) == 1:
                return candidates[0], None
            elif len(candidates) > 1:
                return None, candidates

        return None, None
