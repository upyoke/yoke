"""Done-transition Step 8: GitHub done-state sync wrapper.

Routes the closeout sync (labels + body + close) through
:func:`yoke_core.domain.backlog_github_sync.sync_done_item`, classifies
its return code, and emits a structured result so the runner can record
either ``"8"`` (clean), ``"8-degraded"`` (sync returned non-zero), or
``"8-skipped"`` (no linked GitHub issue / dry run / gh missing) instead
of unconditionally marking the step complete on a silent failure.

The runner's single integration point is :func:`apply_step_8`, which
runs Step 8 and stamps the resulting marker + structured warning onto
the caller's ``TransitionResult``. Tests reach for :func:`run_step_8`
directly to assert the classification.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional, TextIO

from yoke_contracts.item_ref import format_item_ref


@dataclass(frozen=True)
class Step8Result:
    """Outcome of the Step 8 GitHub done-state sync."""

    returncode: int
    step_marker: str  # "8", "8-degraded", or "8-skipped"
    message: str

    @property
    def is_degraded(self) -> bool:
        return self.step_marker == "8-degraded"


def run_step_8(
    item_id: int,
    old_status: str,
    *,
    stderr: Optional[TextIO] = None,
    item_ref: Optional[str] = None,
) -> Step8Result:
    """Run the done-state GitHub sync and classify the outcome.

    The runner records ``step_marker`` on the result file and consults
    ``returncode`` to decide whether to exit non-zero. A non-zero
    ``returncode`` indicates a non-recoverable GitHub failure that the
    operator must see — Step 8 stops claiming success in that case.
    """
    stderr = stderr or sys.stderr
    ref = item_ref or format_item_ref(None, None, None, item_id=item_id)

    try:
        from yoke_core.domain import backlog_github_sync
    except ImportError as exc:
        message = (
            f"backlog_github_sync import failed for {ref}: {exc}"
        )
        print(f"Warning: {message}", file=stderr)
        return Step8Result(
            returncode=0,
            step_marker="8-skipped",
            message=message,
        )

    try:
        rc = backlog_github_sync.sync_done_item(
            str(item_id), old_status, stdout=stderr, stderr=stderr,
        )
    except Exception as exc:  # pragma: no cover - defensive
        message = f"sync_done_item raised for {ref}: {exc}"
        print(f"Warning: {message}", file=stderr)
        return Step8Result(
            returncode=1,
            step_marker="8-degraded",
            message=message,
        )

    if rc == 0:
        return Step8Result(returncode=0, step_marker="8", message="ok")

    message = (
        f"sync_done_item returned {rc} for {ref} — GitHub closeout "
        "failed; Step 8 recorded as degraded."
    )
    print(f"Warning: {message}", file=stderr)
    return Step8Result(
        returncode=rc,
        step_marker="8-degraded",
        message=message,
    )


def apply_step_8(
    item_id: int,
    old_status: str,
    result,
    *,
    item_ref: Optional[str] = None,
) -> Step8Result:
    """Run Step 8 and stamp the outcome onto the caller's ``TransitionResult``.

    Records ``step_marker`` (``"8"``, ``"8-degraded"``, or ``"8-skipped"``)
    in ``result.steps_completed`` and appends a structured
    ``github_sync_degraded`` warning on the degraded path. Returns the
    underlying :class:`Step8Result` for callers that need it.

    The bundled ``sync_done_item`` call is not one operation. It resolves the
    authorization the closeout needs, writes the issue body through the typed
    writer, adds and removes labels one REST call at a time, and finally
    closes the issue — each of them able to fail while the ones before it
    stand. A non-zero rc therefore means the closeout stopped somewhere in
    that sequence, and everything up to that point is already applied: a
    failure at the close leaves an issue whose body reads done while the
    issue is still open. Resolving the authorization first removes the one
    failure that used to open that window routinely, not the window itself.
    Emit a structured ``SyncFailed(operation="state")`` event so
    ``/yoke resync --fix`` has the same observability surface it has for the
    per-operation paths.
    """
    import sys
    outcome = run_step_8(
        item_id, old_status, stderr=sys.stderr, item_ref=item_ref
    )
    result.add_step(outcome.step_marker)
    if outcome.is_degraded:
        result.warnings.append({
            "code": "github_sync_degraded",
            "step": "8",
            "message": outcome.message,
        })
        from yoke_core.domain.backlog_rendering import _record_sync_failure
        _record_sync_failure(
            item_id, "state",
            f"done_transition step 8 degraded: {outcome.message}",
        )
    return outcome


__all__ = ["Step8Result", "run_step_8", "apply_step_8"]
