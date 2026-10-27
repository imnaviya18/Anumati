from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import IntegrityError
from rest_framework.response import Response
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        return response
    if isinstance(exc, ObjectDoesNotExist):
        return Response({"detail": "Record not found."}, status=404)
    if isinstance(exc, ValidationError):
        return Response({"detail": "; ".join(exc.messages)}, status=400)
    if isinstance(exc, ValueError):
        return Response({"detail": "Invalid input value or identifier."}, status=400)
    if isinstance(exc, IntegrityError):
        return Response({"detail": "This record conflicts with existing data or a required relationship."}, status=409)
    return None
