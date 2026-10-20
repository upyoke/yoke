"""The path-claim guard skips the argv ``host-command`` runs remotely.

``yoke qa mission host-command ... -- ARGV`` ships its argv over the
mission's Test Machine lease, so an ``sh -c`` inventory there is not an
opaque local shell. What still runs here — a redirect, a substitution, or
an ``sh -c`` outside the host-command — stays enforced.
"""

from __future__ import annotations

import pytest

from yoke_core.domain.path_claim_bash_guard import evaluate_payload
from yoke_core.domain.path_claim_bash_parser import extract_mutations

HOST = (
    "yoke --env prod qa mission host-command --item YOK-4368 "
    "--execution-id exec-1 --requirement-id 53788 --"
)
INVENTORY = f"{HOST} /bin/sh -c 'ls -la /Users/testy; sw_vers; df -h /'"


def _claim(worktree: str) -> dict:
    return {
        "id": 99,
        "owner_kind": "item",
        "owner_item_id": 1577,
        "integration_target": "main",
        "state": "active",
        "covered_paths": ("runtime/api/domain",),
        "worktree_path": worktree,
        "public_ref": "YOK-1577",
    }


def _verdict(command: str, worktree) -> str:
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(worktree),
        "session_id": "sess-A",
    }
    return evaluate_payload(payload, claim=_claim(str(worktree))).outcome


def test_remote_shell_inventory_is_allowed(tmp_path) -> None:
    assert extract_mutations(INVENTORY) == []
    assert _verdict(INVENTORY, tmp_path) == "allow"


@pytest.mark.parametrize(
    "command",
    [
        f"/bin/sh -c 'ls /Users/testy' && {HOST} /bin/pwd",
        f"{HOST} /bin/pwd | sh -c 'rm docs/x.md'",
        "yoke qa mission host-command --item YOK-1 /bin/sh -c 'rm docs/x.md'",
    ],
)
def test_local_opaque_shell_stays_refused(tmp_path, command: str) -> None:
    assert _verdict(command, tmp_path) == "deny"


def test_local_redirect_after_remote_argv_stays_enforced(tmp_path) -> None:
    command = f"{HOST} /bin/cat /Users/testy/notes.txt > docs/notes.txt"
    assert _verdict(command, tmp_path) == "deny"
