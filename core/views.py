from decimal import Decimal
from django.contrib.auth import authenticate, login, logout
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import render, redirect
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response

from core.auth_utils import (
    is_dealer,
    is_distributor,
    dealer_required,
    distributor_required,
    IsDealerUser,
    IsDistributorUser,
)
from core.models import Product, Inventory, Dealer, Order, OrderStatus
from core.serializers import (
    ProductSerializer,
    ProductCreateSerializer,
    ProductUpdateSerializer,
    DealerSerializer,
    DealerCreateSerializer,
    OrderSerializer,
)
from core.pagination import StandardPagination
from core.exceptions import (
    AppAPIException,
    NotFoundException,
    DuplicateException,
    UnauthorizedException,
    ForbiddenException,
    InvalidTransitionException,
)
from core.order_service import OrderService


def health(request):
    """GET /api/health/ — the grader polls this until your app is ready."""
    return JsonResponse({"status": "ok"})


def index(request):
    """GET / — serves the frontend operational dashboard."""
    return render(request, "core/index.html")


def dealer_login(request):
    """GET /dealer/login/ — renders Dealer Login page.
       POST /dealer/login/ — authenticates dealer and redirects to /dealer/dashboard/."""
    if request.user.is_authenticated:
        if is_dealer(request.user):
            return redirect("/dealer/dashboard/")
        elif is_distributor(request.user):
            return redirect("/distributor/dashboard/")

    error_message = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        if not username or not password:
            error_message = "Please enter both dealer username and password."
        else:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                if is_dealer(user):
                    login(request, user)
                    next_url = request.GET.get("next") or "/dealer/dashboard/"
                    return redirect(next_url)
                elif is_distributor(user):
                    error_message = "This account is a Distributor account. Please use the Distributor Login portal."
                else:
                    error_message = "This account is not associated with an authorized dealer."
            else:
                error_message = "Invalid dealer credentials. Please verify your username (e.g. DLR-001) and password."

    return render(request, "core/dealer_login.html", {"error": error_message})


def dealer_logout(request):
    """Logs out the dealer session and redirects to dealer login."""
    logout(request)
    return redirect("/dealer/login/")


def distributor_login(request):
    """GET /distributor/login/ — renders Distributor Login page.
       POST /distributor/login/ — authenticates distributor and redirects to /distributor/dashboard/."""
    if request.user.is_authenticated:
        if is_distributor(request.user):
            return redirect("/distributor/dashboard/")
        elif is_dealer(request.user):
            return redirect("/dealer/dashboard/")

    error_message = None
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        if not username or not password:
            error_message = "Please enter both distributor username and password."
        else:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                if is_distributor(user):
                    login(request, user)
                    next_url = request.GET.get("next") or "/distributor/dashboard/"
                    return redirect(next_url)
                elif is_dealer(user):
                    error_message = "This account is a Dealer account. Please use the Dealer Login portal."
                else:
                    error_message = "This account does not have distributor operations permissions."
            else:
                error_message = "Invalid distributor credentials. Please verify your username and password."

    return render(request, "core/distributor_login.html", {"error": error_message})


def distributor_logout(request):
    """Logs out the distributor session and redirects to distributor login."""
    logout(request)
    return redirect("/distributor/login/")


@dealer_required
def dealer_dashboard(request):
    """GET /dealer/dashboard/ — renders dealer-specific dashboard."""
    return render(request, "core/dealer_dashboard.html", {
        "dealer": request.user.dealer_profile,
    })


@distributor_required
def distributor_dashboard(request):
    """GET /distributor/dashboard/ — renders distributor operations dashboard."""
    return render(request, "core/distributor_dashboard.html", {
        "user": request.user,
    })


class ProductListCreateView(APIView):
    pagination_class = StandardPagination

    def get(self, request):
        queryset = Product.objects.select_related("inventory").all()

        search = request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(sku__icontains=search) | Q(name__icontains=search) | Q(brand__icontains=search) | Q(vehicle_fitment__icontains=search)
            )

        category = request.query_params.get("category")
        if category:
            queryset = queryset.filter(category__iexact=category)

        vehicle = request.query_params.get("vehicle")
        if vehicle:
            queryset = queryset.filter(vehicle_fitment__icontains=vehicle)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        serializer = ProductSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        sku = request.data.get("sku")
        if sku and isinstance(sku, str):
            val = sku.strip()
            if Product.objects.filter(sku=val).exists():
                raise DuplicateException(f"Product with SKU '{val}' already exists.")
        serializer = ProductCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product = serializer.save()
        return Response(ProductSerializer(product).data, status=status.HTTP_201_CREATED)


class ProductDetailView(APIView):
    def get_object(self, sku):
        try:
            return Product.objects.select_related("inventory").get(sku=sku)
        except Product.DoesNotExist:
            raise NotFoundException(f"Product with SKU '{sku}' not found.")

    def get(self, request, sku):
        product = self.get_object(sku)
        return Response(ProductSerializer(product).data)

    def patch(self, request, sku):
        product = self.get_object(sku)
        serializer = ProductUpdateSerializer(product, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        product.refresh_from_db()
        return Response(ProductSerializer(product).data)


class InventoryUpdateView(APIView):
    def put(self, request, sku):
        try:
            product = Product.objects.get(sku=sku)
        except Product.DoesNotExist:
            raise NotFoundException(f"Product with SKU '{sku}' not found.")

        qty_raw = request.data.get("quantity")
        if qty_raw is None or not isinstance(qty_raw, int) or isinstance(qty_raw, bool) or qty_raw < 0:
            raise AppAPIException(
                code="VALIDATION_ERROR",
                message="Field 'quantity' must be an integer >= 0.",
            )

        inventory, _ = Inventory.objects.update_or_create(
            product=product,
            defaults={"quantity": qty_raw},
        )
        return Response({"sku": sku, "quantity": inventory.quantity}, status=status.HTTP_200_OK)


class DealerListCreateView(APIView):
    pagination_class = StandardPagination

    def get(self, request):
        queryset = Dealer.objects.all()
        dealer_code = request.query_params.get("dealer_code")
        if dealer_code and isinstance(dealer_code, str):
            queryset = queryset.filter(dealer_code__iexact=dealer_code.strip())
        search = request.query_params.get("search")
        if search and isinstance(search, str):
            queryset = queryset.filter(
                Q(dealer_code__icontains=search.strip()) | Q(name__icontains=search.strip())
            )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        serializer = DealerSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        dealer_code = request.data.get("dealer_code")
        if dealer_code and isinstance(dealer_code, str):
            val = dealer_code.strip()
            if Dealer.objects.filter(dealer_code=val).exists():
                raise DuplicateException(f"Dealer with code '{val}' already exists.")
        serializer = DealerCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dealer = serializer.save()
        return Response(DealerSerializer(dealer).data, status=status.HTTP_201_CREATED)


class DealerDetailView(APIView):
    def get(self, request, pk):
        try:
            dealer = Dealer.objects.get(id=pk)
        except Dealer.DoesNotExist:
            raise NotFoundException(f"Dealer with id '{pk}' not found.")
        return Response(DealerSerializer(dealer).data)

    def delete(self, request, pk):
        try:
            dealer = Dealer.objects.get(id=pk)
        except Dealer.DoesNotExist:
            raise NotFoundException(f"Dealer with id '{pk}' not found.")

        # Protect authoritative seeded dealers from deletion
        import csv
        from django.conf import settings
        data_dir = getattr(settings, "DATA_DIR", settings.BASE_DIR / "data")
        dealers_csv = data_dir / "dealers.csv"
        if dealers_csv.exists():
            with open(dealers_csv, "r", encoding="utf-8") as f:
                seeded_codes = {r.get("dealer_code", "").strip() for r in csv.DictReader(f) if r.get("dealer_code")}
            if dealer.dealer_code in seeded_codes:
                raise ForbiddenException("Authoritative seeded dealers cannot be deleted.")

        if dealer.orders.exists():
            raise ForbiddenException("Cannot delete dealer with existing orders.")

        dealer.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OrderListCreateView(APIView):
    pagination_class = StandardPagination

    def get(self, request):
        queryset = Order.objects.prefetch_related("items", "dealer").all()

        # Role-based scoping: Authenticated dealers can ONLY view their own orders
        if is_dealer(request.user):
            queryset = queryset.filter(dealer=request.user.dealer_profile)
        else:
            dealer_id = request.query_params.get("dealer_id")
            if dealer_id:
                queryset = queryset.filter(dealer_id=dealer_id)

        status_param = request.query_params.get("status")
        if status_param:
            stat = "DRAFT" if status_param.upper() == "PENDING" else status_param.upper()
            queryset = queryset.filter(status=stat)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        serializer = OrderSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        idempotency_key = request.headers.get("Idempotency-Key") or request.META.get("HTTP_IDEMPOTENCY_KEY")

        # Role-based binding and anti-tampering verification:
        if is_dealer(request.user):
            dealer_profile = request.user.dealer_profile
            if hasattr(dealer_profile, "is_active") and not dealer_profile.is_active:
                raise ForbiddenException("Your dealer account is disabled or unauthorized to place orders.")
            # Automatically bind dealer_id to authenticated dealer profile, ignoring spoofed dealer_ids
            dealer_id = dealer_profile.id
        elif is_distributor(request.user):
            dealer_id = request.data.get("dealer_id") if isinstance(request.data, dict) else None
        else:
            dealer_id = request.data.get("dealer_id") if isinstance(request.data, dict) else None

        order, is_new = OrderService.create_order(
            dealer_id=dealer_id,
            items_data=request.data.get("items") if isinstance(request.data, dict) else None,
            idempotency_key=idempotency_key,
            raw_body=request.body,
        )
        status_code = status.HTTP_201_CREATED if is_new else status.HTTP_200_OK
        return Response(OrderSerializer(order).data, status=status_code)


class OrderDetailView(APIView):
    def get(self, request, order_number):
        try:
            order = Order.objects.prefetch_related("items", "dealer").get(order_number=order_number)
        except Order.DoesNotExist:
            raise NotFoundException(f"Order '{order_number}' not found.")

        # Role-based restriction: Dealer cannot view another dealer's orders
        if is_dealer(request.user) and order.dealer_id != request.user.dealer_profile.id:
            raise ForbiddenException("You do not have permission to view this order.")

        return Response(OrderSerializer(order).data)

    def put(self, request, order_number):
        if not request.user or not request.user.is_authenticated:
            raise UnauthorizedException("Authentication credentials were not provided or are invalid.")

        try:
            existing = Order.objects.get(order_number=order_number)
        except Order.DoesNotExist:
            raise NotFoundException(f"Order '{order_number}' not found.")

        # Role-based restriction: Dealer cannot modify another dealer's orders
        if is_dealer(request.user):
            if existing.dealer_id != request.user.dealer_profile.id:
                raise ForbiddenException("You do not have permission to modify this order.")
        elif not is_distributor(request.user):
            raise ForbiddenException("Access restricted to authorized distributors.")

        items_data = request.data.get("items") if isinstance(request.data, dict) else None
        order = OrderService.edit_order(order_number, items_data)
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)

    def delete(self, request, order_number):
        try:
            order = Order.objects.get(order_number=order_number)
        except Order.DoesNotExist:
            raise NotFoundException(f"Order '{order_number}' not found.")

        # Role-based restriction: Dealer cannot delete another dealer's orders
        if is_dealer(request.user) and order.dealer_id != request.user.dealer_profile.id:
            raise ForbiddenException("You do not have permission to delete this order.")

        # Only DRAFT and CANCELLED orders can be deleted
        if order.status not in (OrderStatus.DRAFT, OrderStatus.CANCELLED):
            raise InvalidTransitionException(f"Cannot delete order in status '{order.status}'. Cancel it first.")

        from core.models import IdempotencyRecord
        from django.db import transaction
        with transaction.atomic():
            IdempotencyRecord.objects.filter(order=order).delete()
            order.delete()

        return Response(status=status.HTTP_204_NO_CONTENT)


class OrderConfirmView(APIView):
    def post(self, request, order_number):
        # 1. Unauthenticated requests must receive HTTP 401
        if not request.user or not request.user.is_authenticated:
            raise UnauthorizedException("Authentication credentials were not provided or are invalid.")

        # 2. Authenticated dealers attempting confirmation must receive HTTP 403 Forbidden
        if is_dealer(request.user):
            raise ForbiddenException("Dealers are not authorized to confirm orders. Only distributors can confirm orders.")

        # 3. Authenticated non-distributors must receive HTTP 403 Forbidden
        if not is_distributor(request.user):
            raise ForbiddenException("Access restricted to authorized distributors.")

        # 4. Only authenticated distributors can confirm orders
        order = OrderService.confirm_order(order_number, confirmed_by_user=request.user)
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)


class OrderDispatchView(APIView):
    def post(self, request, order_number):
        if not request.user or not request.user.is_authenticated:
            raise UnauthorizedException("Authentication credentials were not provided or are invalid.")
        if not is_distributor(request.user):
            raise ForbiddenException("Access restricted to authorized distributors.")
        order = OrderService.dispatch_order(order_number)
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)


class OrderDeliverView(APIView):
    def post(self, request, order_number):
        if not request.user or not request.user.is_authenticated:
            raise UnauthorizedException("Authentication credentials were not provided or are invalid.")
        if not is_distributor(request.user):
            raise ForbiddenException("Access restricted to authorized distributors.")
        order = OrderService.deliver_order(order_number)
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)


class OrderCancelView(APIView):
    def post(self, request, order_number):
        if not request.user or not request.user.is_authenticated:
            raise UnauthorizedException("Authentication credentials were not provided or are invalid.")

        if is_dealer(request.user):
            try:
                existing = Order.objects.get(order_number=order_number)
            except Order.DoesNotExist:
                raise NotFoundException(f"Order '{order_number}' not found.")
            if existing.dealer_id != request.user.dealer_profile.id:
                raise ForbiddenException("You do not have permission to cancel another dealer's order.")
        elif not is_distributor(request.user):
            raise ForbiddenException("Access restricted to authorized distributors.")

        order = OrderService.cancel_order(order_number)
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)


class DealerDashboardStatsView(APIView):
    """API endpoint providing metrics and info specifically for the authenticated dealer."""
    def get(self, request):
        if not request.user or not request.user.is_authenticated:
            raise UnauthorizedException("Authentication credentials were not provided or are invalid.")
        if not is_dealer(request.user):
            raise ForbiddenException("Access restricted to authorized dealers.")
        dealer = request.user.dealer_profile
        orders = dealer.orders.all()
        total_orders = orders.count()
        pending_orders = orders.filter(status=OrderStatus.DRAFT).count()
        confirmed_orders = orders.filter(status=OrderStatus.CONFIRMED).count()
        total_spent = sum(o.grand_total for o in orders.filter(status=OrderStatus.CONFIRMED))

        return Response({
            "dealer": {
                "id": dealer.id,
                "dealer_code": dealer.dealer_code,
                "name": dealer.name,
                "city": dealer.city,
                "phone": dealer.phone,
                "email": dealer.email,
                "gstin": dealer.gstin,
                "credit_limit": f"{dealer.credit_limit:.2f}",
            },
            "stats": {
                "total_orders": total_orders,
                "pending_orders": pending_orders,
                "confirmed_orders": confirmed_orders,
                "total_spent": f"{total_spent:.2f}",
                "catalogue_count": Product.objects.count(),
            }
        }, status=status.HTTP_200_OK)


class DistributorPendingOrdersView(APIView):
    """API endpoint listing pending dealer orders for distributor review and approval."""
    def get(self, request):
        if not request.user or not request.user.is_authenticated:
            raise UnauthorizedException("Authentication credentials were not provided or are invalid.")
        if not is_distributor(request.user):
            raise ForbiddenException("Access restricted to authorized distributors.")
        pending = Order.objects.filter(status=OrderStatus.DRAFT).select_related("dealer").prefetch_related("items").order_by("-created_at")
        serializer = OrderSerializer(pending, many=True)
        return Response({"results": serializer.data, "count": pending.count()}, status=status.HTTP_200_OK)


class DistributorConfirmOrderView(APIView):
    """Distributor-specific order confirmation endpoint."""
    def post(self, request, order_number):
        if not request.user or not request.user.is_authenticated:
            raise UnauthorizedException("Authentication credentials were not provided or are invalid.")
        if not is_distributor(request.user):
            raise ForbiddenException("Access restricted to authorized distributors.")
        order = OrderService.confirm_order(order_number, confirmed_by_user=request.user)
        return Response(OrderSerializer(order).data, status=status.HTTP_200_OK)


class ForecastDetailView(APIView):
    def get(self, request, sku):
        from core.forecasting_service import ForecastingService
        data = ForecastingService.get_sku_forecast(sku)
        return Response(data, status=status.HTTP_200_OK)


class ReorderSuggestionsView(APIView):
    def get(self, request):
        from core.forecasting_service import ForecastingService
        results = ForecastingService.get_reorder_suggestions()
        return Response({"results": results}, status=status.HTTP_200_OK)


class AssistantChatView(APIView):
    def post(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        session_id = data.get("session_id")
        dealer_id = data.get("dealer_id")
        message = data.get("message")

        if not session_id or not isinstance(session_id, str):
            raise AppAPIException(code="VALIDATION_ERROR", message="Field 'session_id' must be a non-empty string.")

        if is_dealer(request.user):
            dealer_profile = request.user.dealer_profile
            if hasattr(dealer_profile, "is_active") and not dealer_profile.is_active:
                raise ForbiddenException("Your dealer account is disabled or unauthorized.")
            req_dealer_id = data.get("dealer_id")
            if req_dealer_id is not None:
                try:
                    if int(req_dealer_id) != dealer_profile.id:
                        raise ForbiddenException("You cannot access assistant sessions for another dealer.")
                except (ValueError, TypeError):
                    raise AppAPIException(code="VALIDATION_ERROR", message="Field 'dealer_id' must be a valid integer.")
            dealer_id = dealer_profile.id
        elif dealer_id is None or isinstance(dealer_id, bool) or not isinstance(dealer_id, int):
            raise AppAPIException(code="VALIDATION_ERROR", message="Field 'dealer_id' must be a valid integer.")

        try:
            dealer = Dealer.objects.get(id=dealer_id)
        except Dealer.DoesNotExist:
            raise NotFoundException(f"Dealer with id {dealer_id} not found.")

        if hasattr(dealer, "is_active") and not dealer.is_active:
            raise ForbiddenException(f"Dealer '{dealer.dealer_code}' is inactive or unauthorized.")

        if not message or not isinstance(message, str):
            raise AppAPIException(code="VALIDATION_ERROR", message="Field 'message' must be a non-empty string.")

        from core.assistant.sessions import SessionManager
        session_dealer_id = SessionManager.get_session_dealer_id(session_id.strip())
        if session_dealer_id is not None and session_dealer_id != dealer_id:
            raise ForbiddenException("This session belongs to another dealer.")

        from core.assistant.agent import AssistantAgent
        chat_response = AssistantAgent.chat(
            session_id=session_id.strip(),
            dealer_id=dealer_id,
            message=message.strip(),
        )
        return Response(chat_response, status=status.HTTP_200_OK)


class SupplierSyncView(APIView):
    def post(self, request):
        from core.supplier_sync import SupplierSyncService
        result = SupplierSyncService.sync_catalogue()
        return Response(result, status=status.HTTP_200_OK)

