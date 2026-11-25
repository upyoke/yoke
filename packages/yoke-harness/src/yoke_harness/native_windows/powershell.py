"""Literal PowerShell arguments and encoded command payloads."""

import base64


# PowerShell treats straight and typographic single quotes as delimiters.
_SINGLE_QUOTES = str.maketrans({quote: quote * 2 for quote in "'‘’‚‛"})


def quote(value: str) -> str:
    return "'" + str(value).translate(_SINGLE_QUOTES) + "'"


def encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")
