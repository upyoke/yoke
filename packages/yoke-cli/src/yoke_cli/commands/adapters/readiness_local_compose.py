"""Answer a readiness host's request to read this machine's checkout.

Four readiness checks read the item project's files. When the control
plane running them has no checkout it says so and publishes what those
checks need; this turns that request into observations by running them
here, against the checkout this machine has registered for the project.

The collection lives in :mod:`yoke_core.engines.readiness_local_observations`
so the engine owns check execution. This module loads it dynamically and
reports a client without the engine as "cannot observe" rather than
failing — client packages must not take a static ``yoke_core`` import.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, Optional

from yoke_contracts.api.function_call import FunctionCallResponse


def local_execution_request(
    response: FunctionCallResponse,
) -> Optional[Dict[str, Any]]:
    """The request a readiness answer published, when it published one."""
    request = (response.result or {}).get("local_execution_request")
    return request if isinstance(request, dict) and request else None


def collect_observations(request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Run the requested checks here, or ``None`` when this machine cannot."""
    try:
        engine = importlib.import_module(
            "yoke_core.engines.readiness_local_observations"
        )
    except ImportError:
        return None
    return engine.collect_for_request(request)


__all__ = ["collect_observations", "local_execution_request"]
