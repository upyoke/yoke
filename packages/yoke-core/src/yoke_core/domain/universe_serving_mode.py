"""Resolve the universe's local, self-hosted, or hosted serving mode."""

import os
from typing import Literal

from yoke_contracts.server_mode import SERVER_MODE_ENV, SERVER_MODE_SELF_HOST
from yoke_core.domain import universe_startup_lock


def universe_mode() -> Literal["local", "self-host", "hosted"]:
    if universe_startup_lock.hosted_tenant_container_process():
        return "hosted"
    if os.environ.get(SERVER_MODE_ENV, "").strip() == SERVER_MODE_SELF_HOST:
        return "self-host"
    return "local"
