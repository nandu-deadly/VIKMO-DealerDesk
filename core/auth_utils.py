from functools import wraps
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from rest_framework.permissions import BasePermission


def is_dealer(user) -> bool:
    """Checks whether the user is an authenticated dealer with an attached Dealer profile."""
    if not user or not user.is_authenticated:
        return False
    return hasattr(user, "dealer_profile") and user.dealer_profile is not None


def is_distributor(user) -> bool:
    """Checks whether the user is an authenticated distributor (staff/superuser/Distributor group, not dealer)."""
    if not user or not user.is_authenticated:
        return False
    # If explicitly linked to a dealer, they are not a distributor
    if hasattr(user, "dealer_profile") and user.dealer_profile is not None:
        return False
    return user.is_staff or user.is_superuser or user.groups.filter(name="Distributor").exists()


def dealer_required(view_func):
    """Decorator ensuring request.user is authenticated and associated with a Dealer profile."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/dealer/login/?{REDIRECT_FIELD_NAME}={request.path}")
        if not is_dealer(request.user):
            if is_distributor(request.user):
                # Distributor attempted to view dealer page
                return HttpResponseForbidden("Forbidden: Distributor accounts cannot access the Dealer portal. Please use the Distributor dashboard.")
            return HttpResponseForbidden("Forbidden: User is not authorized as a dealer.")
        return view_func(request, *args, **kwargs)
    return _wrapped


def distributor_required(view_func):
    """Decorator ensuring request.user is authenticated and has Distributor role."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"/distributor/login/?{REDIRECT_FIELD_NAME}={request.path}")
        if not is_distributor(request.user):
            if is_dealer(request.user):
                # Dealer attempted to access distributor dashboard
                return HttpResponseForbidden("Forbidden: Dealer accounts cannot access the Distributor operations portal.")
            return HttpResponseForbidden("Forbidden: User is not authorized as a distributor.")
        return view_func(request, *args, **kwargs)
    return _wrapped


class IsDealerUser(BasePermission):
    """DRF permission: allows access only to authenticated dealers."""
    message = "Forbidden: Access restricted to authorized dealers."

    def has_permission(self, request, view):
        return is_dealer(request.user)


class IsDistributorUser(BasePermission):
    """DRF permission: allows access only to authorized distributors."""
    message = "Forbidden: Access restricted to authorized distributors."

    def has_permission(self, request, view):
        return is_distributor(request.user)
