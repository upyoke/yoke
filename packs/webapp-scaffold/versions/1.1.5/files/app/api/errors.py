"""Shared error mapping for {{project_display_name}} API routers."""

from fastapi import HTTPException

ERROR_STATUS_MAP = {
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_ARG": 400,
    "ERR_MISSING_ARG": 400,
    "ERR_INVALID_STATUS": 409,
    "ERR_CONFLICT": 409,
}


def raise_from_helper_error(error_string: str):
    """Parse ERR_CODE from helper error string and raise HTTPException.

    Helper functions return errors like: "ERR_NOT_FOUND: Item 42 not found."
    This parses the prefix, maps to an HTTP status code, and raises.
    """
    code = "ERR_INTERNAL"
    message = error_string
    for prefix in ERROR_STATUS_MAP:
        if error_string.startswith(prefix):
            code = prefix
            if ": " in error_string:
                message = error_string.split(": ", 1)[1]
            break
    status = ERROR_STATUS_MAP.get(code, 500)
    raise HTTPException(
        status_code=status,
        detail={"code": code, "message": message},
    )
