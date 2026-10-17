import logging

from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from .exceptions import ServiceError

logger = logging.getLogger(__name__)


def exception_handler(exc, context):
    response = drf_exception_handler(exc, context)
    if response is None:
        if isinstance(exc, ServiceError):
            status_code = exc.status_code
            code = exc.code
            message = str(exc)
            details = {"retryable": exc.retryable}
        else:
            logger.exception("Unhandled API exception")
            status_code = 500
            code = "internal_error"
            message = "An internal error occurred."
            details = None
        response = Response(
            {"error": {"code": str(code), "message": message, "details": details}},
            status=status_code,
        )
        return response

    if isinstance(exc, APIException):
        code = exc.default_code
        message = exc.detail
    else:
        code = "internal_error"
        message = "An internal error occurred."
    details = response.data if response.status_code < 500 else None
    response.data = {"error": {"code": str(code), "message": message, "details": details}}
    return response
