from django.urls import path
from core import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("products/", views.ProductListCreateView.as_view(), name="product-list-create"),
    path("products/<str:sku>/", views.ProductDetailView.as_view(), name="product-detail"),
    path("inventory/<str:sku>/", views.InventoryUpdateView.as_view(), name="inventory-update"),
    path("dealers/", views.DealerListCreateView.as_view(), name="dealer-list-create"),
    path("dealers/<int:pk>/", views.DealerDetailView.as_view(), name="dealer-detail"),
    path("orders/", views.OrderListCreateView.as_view(), name="order-list-create"),
    path("orders/<str:order_number>/", views.OrderDetailView.as_view(), name="order-detail"),
    path("orders/<str:order_number>/confirm/", views.OrderConfirmView.as_view(), name="order-confirm"),
    path("orders/<str:order_number>/dispatch/", views.OrderDispatchView.as_view(), name="order-dispatch"),
    path("orders/<str:order_number>/deliver/", views.OrderDeliverView.as_view(), name="order-deliver"),
    path("orders/<str:order_number>/cancel/", views.OrderCancelView.as_view(), name="order-cancel"),
    path("forecast/<str:sku>/", views.ForecastDetailView.as_view(), name="forecast-detail"),
    path("reorder-suggestions/", views.ReorderSuggestionsView.as_view(), name="reorder-suggestions"),
    path("assistant/chat/", views.AssistantChatView.as_view(), name="assistant-chat"),
    path("sync/supplier/", views.SupplierSyncView.as_view(), name="supplier-sync"),
    path("dealer/dashboard-stats/", views.DealerDashboardStatsView.as_view(), name="dealer-dashboard-stats"),
    path("dealer/stats/", views.DealerDashboardStatsView.as_view(), name="dealer-stats"),
    path("distributor/pending-orders/", views.DistributorPendingOrdersView.as_view(), name="distributor-pending-orders"),
    path("distributor/orders/pending/", views.DistributorPendingOrdersView.as_view(), name="distributor-orders-pending"),
    path("distributor/orders/<str:order_number>/confirm/", views.DistributorConfirmOrderView.as_view(), name="distributor-confirm-order"),
]
