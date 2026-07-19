"""User-facing Pack client failures."""


class PackClientError(RuntimeError):
    """A Pack operation cannot proceed; the message names the repair."""


__all__ = ["PackClientError"]
