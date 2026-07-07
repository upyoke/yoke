"""Shared project-context response contract for product clients and API."""

from __future__ import annotations

CHECKOUT_CONTEXT_FIELDS = ("id", "slug", "name", "public_item_prefix")

__all__ = ["CHECKOUT_CONTEXT_FIELDS"]
