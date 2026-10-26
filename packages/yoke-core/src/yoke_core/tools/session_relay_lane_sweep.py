"""The standing relay's periodic sweep of finished lanes on its machine.

A lane lives on one machine's disk, and the control plane that closes its
item often runs somewhere else: a hosted server settles a release where no
checkout exists. The relay is the one long-lived process on the lanes' own
machine, so it sweeps every checkout its connection maps — once when it
starts, then every 15 minutes — through ``sweep_managed_lanes``, the same
fail-closed path every other caller uses. Unmerged, dirty, claimed or open
lanes are kept, and every lane removed or kept is named in the relay log.

Only the prod relay sweeps. A stage relay judges lanes against a disposable
rehearsal database that may call a real lane finished, so it never deletes
one; it says so once in its log instead.

The sweep runs on its own thread, so the relay's poll loop never waits on
git or the network, and a sweep still running when the next one is due is
not started twice.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from typing import Any

SWEEP_INTERVAL_SECONDS = 15 * 60
LOG_PREFIX = "lane sweep"


def _log(message: str, **_kw: Any) -> None:
    print(f"{LOG_PREFIX}: {message}", file=sys.stderr, flush=True)


def _default_branch(project_id: int) -> tuple[str, str]:
    """The project's default branch, or why it could not be read."""
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

    try:
        response = call_dispatcher(
            function_id="projects.get",
            target=TargetRef(kind="global"),
            payload={"project": str(project_id)},
        )
    except Exception as exc:  # noqa: BLE001 - named in the relay log
        return "", str(exc) or exc.__class__.__name__
    if not response.success:
        error = response.error
        return "", error.message if error is not None else "project read refused"
    row = (response.result or {}).get("row") or {}
    branch = str(row.get("default_branch") or "")
    return branch, "" if branch else "the project names no default branch"


def sweep_mapped_checkouts(*, log: Callable[..., None] = _log) -> None:
    """Sweep each checkout the selected connection maps, naming every outcome."""
    from yoke_contracts.machine_config import runtime as machine_config
    from yoke_contracts.machine_config.schema import mapped_checkouts
    from yoke_core.domain.terminal_lane_cleanup import sweep_managed_lanes

    for checkout, project_id in sorted(mapped_checkouts(machine_config.load_config())):
        target, refusal = _default_branch(int(project_id))
        if refusal:
            log(
                f"{checkout} skipped: project {project_id} could not be read "
                f"({refusal}); the next sweep retries it"
            )
            continue
        warnings, swept = sweep_managed_lanes(
            repo_root=checkout, target=target, emit=log
        )
        for warning in warnings:
            log(f"{checkout}: {warning}")
        skipped = swept.get("skipped") or ""
        log(
            f"{checkout} against {target}: removed "
            f"{len(swept.get('removed') or ())}, kept "
            f"{len(swept.get('preserved') or ())}"
            + (f", skipped: {skipped}" if skipped else "")
        )


class RelayLaneSweep:
    """The relay's maintenance hook: start a due sweep, never wait for one."""

    def __init__(
        self,
        *,
        off_reason: str = "",
        interval_seconds: float = SWEEP_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        sweep: Callable[..., None] = sweep_mapped_checkouts,
        log: Callable[..., None] = _log,
    ) -> None:
        self._off_reason = off_reason
        self._interval = interval_seconds
        self._clock = clock
        self._sweep = sweep
        self._log = log
        self._due_at: float | None = None
        self._thread: threading.Thread | None = None
        self._told_off = False

    def __call__(self) -> None:
        if self._off_reason:
            if not self._told_off:
                self._log(self._off_reason)
                self._told_off = True
            return
        if self._thread is not None and self._thread.is_alive():
            return
        now = self._clock()
        if self._due_at is not None and now < self._due_at:
            return
        self._due_at = now + self._interval
        self._thread = threading.Thread(
            target=self._run, name="relay-lane-sweep", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        try:
            self._sweep(log=self._log)
        except Exception as exc:  # noqa: BLE001 - the relay keeps standing
            self._log(
                f"stopped after an unexpected refusal: {exc}; the next sweep "
                f"runs in {self._interval / 60:.0f} minutes"
            )


def relay_lane_sweep(instance: Any) -> RelayLaneSweep:
    """The sweep for one relay instance; off unless it is the prod relay."""
    if instance.prod:
        return RelayLaneSweep()
    return RelayLaneSweep(
        off_reason=(
            f"off: relay env {instance.environment!r} is not the prod "
            "connection, and only the prod relay judges lanes against a "
            "control plane real work lives in"
        )
    )


__all__ = [
    "SWEEP_INTERVAL_SECONDS",
    "RelayLaneSweep",
    "relay_lane_sweep",
    "sweep_mapped_checkouts",
]
