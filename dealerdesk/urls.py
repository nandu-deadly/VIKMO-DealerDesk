from django.contrib import admin
from django.urls import include, path
from core import views

urlpatterns = [
    path("", views.index, name="dashboard"),
    path("dealer/login/", views.dealer_login, name="dealer-login"),
    path("dealer/logout/", views.dealer_logout, name="dealer-logout"),
    path("dealer/dashboard/", views.dealer_dashboard, name="dealer-dashboard"),
    path("distributor/login/", views.distributor_login, name="distributor-login"),
    path("distributor/logout/", views.distributor_logout, name="distributor-logout"),
    path("distributor/dashboard/", views.distributor_dashboard, name="distributor-dashboard"),
    path("admin/", admin.site.urls),
    path("api/", include("core.urls")),
]
