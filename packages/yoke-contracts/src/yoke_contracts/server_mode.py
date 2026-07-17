"""Explicit runtime mode for server-only product boundaries."""

from __future__ import annotations

SERVER_MODE_ENV = "YOKE_SERVER_MODE"
SERVER_MODE_SELF_HOST = "self-host"

__all__ = ["SERVER_MODE_ENV", "SERVER_MODE_SELF_HOST"]
