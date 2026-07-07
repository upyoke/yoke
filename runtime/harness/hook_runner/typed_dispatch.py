"""Typed-policy dispatch with a dual watchdog (SIGALRM / worker thread).

``dispatch_typed`` imports a policy module and invokes ``evaluate(context)``
under a timeout. In the main thread (the per-invocation hook subprocess) the
watchdog is POSIX ``SIGALRM``, which can interrupt CPU-bound policy code.
Off the main thread — ``POST /v1/hooks/evaluate`` evaluates inside a FastAPI
worker thread, where ``signal.signal`` raises ``ValueError`` — the evaluator
runs on a daemon worker thread joined with the same timeout. A hung policy
then leaks its daemon thread until it returns, but the chain proceeds to
deadline bookkeeping instead of crashing the request; the leak is bounded by
the policy's own work and is the price of preempting nothing.
"""

from __future__ import annotations

import importlib
import signal
import threading
from typing import Any, Optional

from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


__all__ = ["audit_only_synthetic", "dispatch_typed"]


class _RunnerTimeout(BaseException):
    """Raised by the SIGALRM handler so the runner can recognize timeouts."""


def _alarm_handler(signum, frame):  # noqa: ARG001 — signal handler shape
    raise _RunnerTimeout("module evaluate exceeded timeout")


def audit_only_synthetic() -> HookDecision:
    """Neutral decision used for failures and non-decision policy returns."""
    return HookDecision(outcome=Outcome.AUDIT_ONLY, next=Next.CONTINUE)


def _normalize(result: Any) -> tuple[Optional[HookDecision], Optional[str]]:
    if isinstance(result, HookDecision):
        return result, None
    return audit_only_synthetic(), None


def dispatch_typed(
    module_id: str,
    *,
    context: HookContext,
    timeout_ms: int,
) -> tuple[Optional[HookDecision], Optional[str]]:
    """Import + invoke a typed policy under a timeout watchdog."""
    try:
        module = importlib.import_module(module_id)
    except Exception:
        return None, "import_error"
    evaluator = getattr(module, "evaluate", None)
    if not callable(evaluator):
        return None, "missing_evaluate"
    if threading.current_thread() is threading.main_thread():
        return _evaluate_with_sigalrm(evaluator, context, timeout_ms)
    return _evaluate_on_worker_thread(evaluator, context, timeout_ms)


def _evaluate_with_sigalrm(
    evaluator, context: HookContext, timeout_ms: int,
) -> tuple[Optional[HookDecision], Optional[str]]:
    previous_handler = signal.signal(signal.SIGALRM, _alarm_handler)
    signal.setitimer(signal.ITIMER_REAL, timeout_ms / 1000.0)
    try:
        result = evaluator(context)
    except _RunnerTimeout:
        return None, f"timeout_{timeout_ms}ms"
    except Exception as exc:  # noqa: BLE001 — fail open, never crash chain
        return None, f"exception_{type(exc).__name__}"
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
    return _normalize(result)


def _evaluate_on_worker_thread(
    evaluator, context: HookContext, timeout_ms: int,
) -> tuple[Optional[HookDecision], Optional[str]]:
    box: dict[str, Any] = {}

    def _run() -> None:
        try:
            box["result"] = evaluator(context)
        except Exception as exc:  # noqa: BLE001 — fail open, never crash chain
            box["error"] = exc

    worker = threading.Thread(
        target=_run, name=f"hook-policy-{module_name(evaluator)}", daemon=True,
    )
    worker.start()
    worker.join(timeout_ms / 1000.0)
    if worker.is_alive():
        return None, f"timeout_{timeout_ms}ms"
    if "error" in box:
        return None, f"exception_{type(box['error']).__name__}"
    return _normalize(box.get("result"))


def module_name(evaluator) -> str:
    return getattr(evaluator, "__module__", "") or "policy"
