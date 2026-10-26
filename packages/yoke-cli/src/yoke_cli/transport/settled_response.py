"""Finish every dispatcher response before the caller sees it.

The response is redacted, then any cloud Test Machine its lease release left
free (``released_test_machines``) is stopped from this machine, which holds
the project's aws-admin key. Whatever command made the call, the last lease
release is what stops the host.
"""

from __future__ import annotations

import importlib
import sys
from typing import Sequence

from yoke_cli.transport.public_ref_display import redact_response
from yoke_contracts.api.function_call import FunctionCallResponse


def settle_response(
    response: FunctionCallResponse, sensitive_values: Sequence[str] = ()
) -> FunctionCallResponse:
    response = redact_response(response, tuple(sensitive_values))
    if response.released_test_machines:
        try:
            stop = importlib.import_module("yoke_core.domain.test_machine_power_stop")
        except ImportError as exc:
            print(
                "test_machine_power_stop_failed: cloud Test Machines "
                f"{response.released_test_machines} stay running; this CLI cannot "
                f"load the stop ({exc}). Recovery: run `yoke update`, then "
                "`yoke test-machine verify`, whose release stops them.",
                file=sys.stderr,
                flush=True,
            )
        else:
            stop.stop_released(response.released_test_machines)
    return response


__all__ = ["settle_response"]
