from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
import logging

logger = logging.getLogger(__name__)


def custom_exception_handler(exc, context):
    """
    Return a consistent JSON error envelope:
    {
        "success": false,
        "message": "...",
        "errors": {...}   (only for validation errors)
    }
    """
    response = exception_handler(exc, context)

    if response is not None:
        # DRF already handled it
        data = response.data
        new_data = {"success": False}

        # Validation error: data is a dict of field: [messages]
        if isinstance(data, dict):
            # Flatten "detail" if present
            detail = data.get("detail")
            if detail:
                new_data["message"] = str(detail)
                # Remove 'detail' key; keep any other keys as errors
                remaining = {k: v for k, v in data.items() if k != "detail"}
                if remaining:
                    new_data["errors"] = remaining
            else:
                new_data["message"] = "Validation error."
                new_data["errors"] = data
        elif isinstance(data, list):
            new_data["message"] = " ".join(str(e) for e in data)
        else:
            new_data["message"] = str(data)

        response.data = new_data

    return response