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


def presence_script(paths: Sequence[str]) -> str:
    """Return a POSIX script printing ``missing N`` for each absent golden.

    ``N`` is the 1-based position. A symlink is never a golden.
    """
    quoted = " ".join(shlex.quote(path) for path in paths)
    return "\n".join(
        (
            "index=0",
            f"for path in {quoted}; do",
            "  index=$((index + 1))",
            '  if [ -L "$path" ] || [ ! -d "$path" ]; then printf "missing %s\\n" "$index"; fi',
            "done",
        )
    )


def missing_goldens(
    registered: Sequence[dict[str, str]], stdout: str
) -> list[dict[str, str]]:
    """Return the registrations whose position the script reported missing."""
    positions = {
        int(parts[1])
        for parts in (line.split() for line in stdout.splitlines())
        if len(parts) == 2 and parts[0] == "missing" and parts[1].isdigit()
    }
    return [entry for i, entry in enumerate(registered, 1) if i in positions]


def check_registered_goldens(run: Any, registered: Sequence[dict[str, str]]) -> None:
    """Refuse, naming each project and path, when a registered golden is gone."""
    if not registered:
        return
    result = run(presence_script([entry["path"] for entry in registered]), timeout=60)
    if getattr(result, "returncode", 1) != 0:
        raise HostControlLocalError(
            code=REGISTERED_GOLDEN_CHECK_FAILED,
            phase=PHASE,
            detail="Could not check the goldens registered for this host and user.",
            recovery_hint="Repair the SSH route named in stderr, then retry verify.",
            exit_code=getattr(result, "returncode", None),
            stderr=getattr(result, "stderr", "") or "",
        )
    missing = missing_goldens(registered, getattr(result, "stdout", "") or "")
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


def check_contract_goldens(execution: dict[str, Any], registered: Any) -> None:
    """Run the check over the issued contract's own host connection.

    A server from before this check names no goldens, so nothing is checked.
    """
    if not registered:
        return
    from yoke_contracts.machine_qa_execution import HostControlExecutionContract
    from yoke_harness.host_operations import host_operations_for

    contract = HostControlExecutionContract.model_validate(execution)
    check_registered_goldens(host_operations_for(contract)._run, registered)


__all__ = [
    "REGISTERED_GOLDEN_CHECK_FAILED",
    "REGISTERED_GOLDEN_MISSING",
    "check_contract_goldens",
    "check_registered_goldens",
    "missing_goldens",
    "presence_script",
]
