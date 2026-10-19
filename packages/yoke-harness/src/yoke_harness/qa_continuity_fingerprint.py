"""Check declared continuity files before any machine QA setup mutates a host."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.qa_continuity_fingerprint import KEY, normalize_fingerprint
from yoke_contracts.machine_qa_failures import HostControlLocalError

RECOVERY = (
    "Restore the required continuity state on the leased machine, record its "
    "stable file SHA-256 hashes in method_config.continuity_fingerprint, then "
    "save the plan and rematerialize its cases before retrying. Do not replace "
    "the expected hashes until the required state is proven again. If checking "
    "failed, repair Python 3, SSH or file access before retrying."
)
_PROGRAM = r"""
import hashlib, json, pathlib, sys
failures = []
for name, expected in json.loads(sys.argv[1]).items():
    path = pathlib.Path(name).expanduser()
    try:
        if path.is_symlink() or not path.is_file():
            failures.append({"path": name, "reason": "missing_or_not_regular"})
            continue
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1048576), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            failures.append({"path": name, "reason": "changed"})
    except OSError:
        failures.append({"path": name, "reason": "unreadable"})
print(json.dumps({"ok": not failures, "failures": failures}))
sys.exit(bool(failures))
"""


def check_continuity(control: Any, config: dict[str, Any]) -> dict[str, Any] | None:
    """Fail closed on missing, changed, unreadable or uncheckable state."""
    if KEY not in config:
        return None
    fingerprint = normalize_fingerprint(config[KEY])
    try:
        completed = control.run_command(
            ["python3", "-c", _PROGRAM, json.dumps(fingerprint)], timeout=30
        )
        evidence = json.loads(completed.stdout)
        if completed.returncode == 0 and evidence == {"ok": True, "failures": []}:
            return {"ok": True, "checked_files": list(fingerprint)}
    except Exception:
        pass
    raise HostControlLocalError(
        code="continuity_lost",
        phase="continuity_fingerprint",
        detail="Recorded continuity files are missing, changed, unreadable, or could not be checked; the case did not start",
        recovery_hint=RECOVERY,
    )
