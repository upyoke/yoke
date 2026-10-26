"""Find every golden registered for a Test Machine's home before verify.

Several projects can register one host and user, and each resets that home
from its own golden. A golden folder removed by hand leaves its project unable
to reset, and nothing else notices until that reset fails, so verify looks
for every registered golden first and refuses by name when one is missing.
"""

from __future__ import annotations

import shlex
from typing import Any, Sequence

from yoke_contracts.machine_qa_failures import HostControlLocalError

REGISTERED_GOLDEN_MISSING = "registered_golden_missing"
REGISTERED_GOLDEN_CHECK_FAILED = "registered_golden_check_failed"
PHASE = "registered_golden_check"


def check_registered_goldens(run: Any, registered: Sequence[dict[str, str]]) -> None:
    """Refuse, naming each project and path, when a registered golden is gone."""
    if not registered:
        return
    quoted = " ".join(shlex.quote(entry["path"]) for entry in registered)
    # A symlink is never a golden.
    script = (
        f"for path in {quoted}; do "
        'if [ -L "$path" ] || [ ! -d "$path" ]; then printf "%s\\n" "$path"; fi; '
        "done"
    )
    result = run(script, timeout=60)
    if getattr(result, "returncode", 1) != 0:
        raise HostControlLocalError(
            code=REGISTERED_GOLDEN_CHECK_FAILED,
            phase=PHASE,
            detail="Could not check the goldens registered for this host and user.",
            recovery_hint="Repair the SSH route named in stderr, then retry verify.",
            exit_code=getattr(result, "returncode", None),
            stderr=getattr(result, "stderr", "") or "",
        )
    printed = set((getattr(result, "stdout", "") or "").splitlines())
    missing = [entry for entry in registered if entry["path"] in printed]
    if not missing:
        return
    named = "; ".join(
        f"project {entry['project']} ({entry['test_machine']}) registers "
        f"{entry['path']}" for entry in missing
    )
    first = missing[0]
    raise HostControlLocalError(
        code=REGISTERED_GOLDEN_MISSING,
        phase=PHASE,
        detail=f"A registered golden is missing on this host: {named}.",
        recovery_hint=(
            "Capture a new golden for each named project: yoke test-machine "
            f"golden-capture --project {first['project']} --test-machine "
            f"{first['test_machine']}. Never delete or move a registered "
            "golden by hand."
        ),
    )


__all__ = [
    "REGISTERED_GOLDEN_CHECK_FAILED",
    "REGISTERED_GOLDEN_MISSING",
    "check_registered_goldens",
]
