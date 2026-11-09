"""Service-owned implementation of the domain handler-registry port."""

from __future__ import annotations


def ensure_handlers_registered() -> None:
    """Install all handlers; the registrar owns locking and reset detection."""
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers

    register_all_handlers()
