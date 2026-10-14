from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    NotFound,
    ValidationError as DRFValidationError,
    MethodNotAllowed,
    NotAuthenticated,
    PermissionDenied,
)
from django.http import Http404
from django.core.exceptions import ValidationError as DjangoValidationError


class AppAPIException(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "VALIDATION_ERROR"
    default_message = "An error occurred"

    def __init__(self, message=None, code=None, status_code=None, details=None):
        if message is not None:
            self.message = message
        else:
            self.message = self.default_message
        if code is not None:
            self.code = code
        else:
            self.code = self.default_code
        if status_code is not None:
            self.status_code = status_code
        self.details = details if details is not None else []
        super().__init__(self.message)


class DuplicateException(AppAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "DUPLICATE"
    default_message = "Resource already exists"


class NotFoundException(AppAPIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_code = "NOT_FOUND"
    default_message = "Resource not found"


class InsufficientStockException(AppAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "INSUFFICIENT_STOCK"
    default_message = "Insufficient stock available"


class InvalidTransitionException(AppAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "INVALID_TRANSITION"
    default_message = "Invalid status transition"


class OrderLockedException(AppAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "ORDER_LOCKED"
    default_message = "Order is locked and cannot be edited"


class IdempotencyConflictException(AppAPIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = "IDEMPOTENCY_CONFLICT"
    default_message = "Idempotency key conflict"


class SupplierUnavailableException(AppAPIException):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_code = "SUPPLIER_UNAVAILABLE"
    default_message = "Supplier service unavailable"


class UnauthorizedException(AppAPIException):
    status_code = status.HTTP_401_UNAUTHORIZED
    default_code = "UNAUTHORIZED"
    default_message = "Authentication credentials were not provided or are invalid."


class ForbiddenException(AppAPIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_code = "FORBIDDEN"
    default_message = "You do not have permission to perform this action."


def custom_exception_handler(exc, context):
    # Call REST framework's default exception handler first to get the standard error response.
    response = exception_handler(exc, context)

    # If it's already an AppAPIException instance
    if isinstance(exc, AppAPIException):
        return Response(
            {
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "details": exc.details if isinstance(exc.details, list) else [],
                }
            },
            status=exc.status_code,
        )

    if isinstance(exc, NotAuthenticated):
        return Response(
            {
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": str(exc.detail) if hasattr(exc, "detail") else "Authentication credentials were not provided or are invalid.",
                    "details": [],
                }
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if isinstance(exc, PermissionDenied):
        return Response(
            {
                "error": {
                    "code": "FORBIDDEN",
                    "message": str(exc.detail) if hasattr(exc, "detail") else "You do not have permission to perform this action.",
                    "details": [],
                }
            },
            status=status.HTTP_403_FORBIDDEN,
        )

    if isinstance(exc, (NotFound, Http404)):
        return Response(
            {
                "error": {
                    "code": "NOT_FOUND",
                    "message": str(exc.detail) if hasattr(exc, "detail") else "Resource not found",
                    "details": [],
                }
            },
            status=status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, (DRFValidationError, DjangoValidationError)):
        details = []
        message = "Validation error"
        if hasattr(exc, "detail"):
            if isinstance(exc.detail, dict):
                for k, v in exc.detail.items():
                    msg = v if isinstance(v, str) else (v[0] if isinstance(v, list) else str(v))
                    details.append({"field": k, "issue": str(msg)})
                message = "; ".join(f"{d['field']}: {d['issue']}" for d in details) or message
            elif isinstance(exc.detail, list):
                details = [{"issue": str(i)} for i in exc.detail]
                message = "; ".join(d["issue"] for d in details) or message
            else:
                message = str(exc.detail)
        elif hasattr(exc, "message_dict"):
            for k, v in exc.message_dict.items():
                details.append({"field": k, "issue": "; ".join(v)})
            message = "; ".join(f"{d['field']}: {d['issue']}" for d in details) or message
        elif hasattr(exc, "messages"):
            details = [{"issue": m} for m in exc.messages]
            message = "; ".join(exc.messages) or message

        return Response(
            {
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": message,
                    "details": details,
                }
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if response is not None:
        status_code = response.status_code
        code = "VALIDATION_ERROR"
        if status_code == 401:
            code = "UNAUTHORIZED"
        elif status_code == 403:
            code = "FORBIDDEN"
        elif status_code == 404:
            code = "NOT_FOUND"
        elif status_code == 409:
            code = "DUPLICATE"
        elif status_code >= 500:
            code = "SERVER_ERROR"

        msg = "An error occurred"
        if isinstance(response.data, dict) and "detail" in response.data:
            msg = str(response.data["detail"])
        elif isinstance(response.data, list) and response.data:
            msg = str(response.data[0])

        return Response(
            {
                "error": {
                    "code": code,
                    "message": msg,
                    "details": [],
                }
            },
            status=status_code,
        )

    return None

