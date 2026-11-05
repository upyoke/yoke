"""Wait for a project merge holder and acquire its lock atomically."""

import time

from yoke_core.domain import merge_lock, runtime_settings

MERGE_LOCK_POLL_SECONDS = 15


def wait_and_acquire(
    scope, branch, epic_ref, *, print_fn, sleep_fn=time.sleep, clock=time.monotonic
):
    ttl = runtime_settings.get_int(
        "merge_lock_ttl_minutes", merge_lock.DEFAULT_TTL_MINUTES
    )
    started = clock()
    deadline = started + ttl * 60
    while True:
        blocked = merge_lock.check(scope=scope)
        if not blocked:
            try:
                return merge_lock.acquire(branch, epic_ref, scope=scope)
            except merge_lock.MergeLockHeld as exc:
                blocked = merge_lock.check(scope=scope) or str(exc)
        elapsed = max(0, int(clock() - started))
        print_fn(
            f"Waiting for merge lock on {scope.project_slug}/{scope.target_branch}: "
            f"{blocked} (elapsed {elapsed // 60}m{elapsed % 60:02d}s of {ttl}m)"
        )
        remaining = deadline - clock()
        if remaining <= 0:
            return blocked
        sleep_fn(min(MERGE_LOCK_POLL_SECONDS, remaining))
