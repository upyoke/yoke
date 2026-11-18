"""Literal PowerShell arguments and encoded command payloads."""

import base64


def quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")
