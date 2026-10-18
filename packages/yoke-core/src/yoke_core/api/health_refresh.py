"""Lifespan-owned health refresh, isolated from HTTP worker admission."""

from __future__ import annotations

import threading
from contextlib import contextmanager

from yoke_core.domain import runtime_settings


@contextmanager
def health_refresh_lifespan():
    # Delay route import until main has finished constructing its application.
    from yoke_core.api.routes import items_health

    items_health.initialize_health_metadata()
    interval = runtime_settings.get_seconds(
        items_health.MIGRATIONS_PROBE_TTL_KEY,
        items_health.MIGRATIONS_PROBE_TTL_DEFAULT,
    )
    stopped = threading.Event()

    def refresh() -> None:
        while not stopped.is_set():
            items_health.refresh_health_snapshot()
            if stopped.wait(interval):
                return

    worker = threading.Thread(target=refresh, name="yoke-health-refresh", daemon=True)
    worker.start()
    try:
        yield
    finally:
        stopped.set()
        worker.join()
