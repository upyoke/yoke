"""Serialize short native spawn boundaries and check current machine headroom."""

from contextlib import contextmanager
import threading
import time

from yoke_contracts.machine_config.native_capacity import (
    NATIVE_SPAWN_STAGGER_SECONDS,
    observe_native_capacity,
)

_LOCK = threading.Lock()
_LAST_SPAWN = None


class NativeCapacityRefusal(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(
            f"{code}: no native was started. Recovery: free memory or swap "
            "headroom (stop unused processes), then retry the launch. "
            "If the reading is unavailable, restore the OS capacity probe first."
        )


@contextmanager
def native_spawn_admission(*, probe=None, clock=time.monotonic, sleeper=time.sleep):
    """Check immediately before spawn, after the previous spawn's short stagger."""
    global _LAST_SPAWN
    with _LOCK:
        if _LAST_SPAWN is not None:
            sleeper(max(0, NATIVE_SPAWN_STAGGER_SECONDS - (clock() - _LAST_SPAWN)))
        code = (probe or observe_native_capacity)().refusal()
        if code:
            raise NativeCapacityRefusal(code)
        yield
        _LAST_SPAWN = clock()


def run_admitted_adapter(context, adapter):
    """App creates and supervised subprocesses report the same capacity refusal."""
    from yoke_harness.session_relay_runtime import RelayAdapterResult

    try:
        if context.job_kind == "launch" and not context.surface.endswith("-cli"):
            with native_spawn_admission():
                return adapter(context)
        return adapter(context)
    except NativeCapacityRefusal as exc:
        return RelayAdapterResult(
            "not_created" if context.job_kind == "launch" else "failed",
            evidence={
                "result_code": exc.code,
                "skip_reason": "Recovery: free memory/swap and retry launch; restore the OS probe if unreadable.",
            },
        )
