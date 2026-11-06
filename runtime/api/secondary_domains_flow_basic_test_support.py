# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest


def _insert_projects(conn):
    created_at = "2026-04-20T00:00:00Z"
    for pid, slug, name in [
        (1, "yoke", "Yoke"),
        (2, "externalwebapp", "ExternalWebapp"),
    ]:
        conn.execute(
            "INSERT INTO projects (id, slug, name, "
            "public_item_prefix, created_at) "
            "VALUES (%s, %s, %s, 'YOK', %s) "
            "ON CONFLICT(id) DO NOTHING",
            (pid, slug, name, created_at),
        )
    conn.commit()
