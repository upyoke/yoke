"""Recorded file identities for machine QA that needs an earlier host state."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from yoke_contracts.machine_qa_failures import HostControlLocalError

KEY = "continuity_fingerprint"


def normalize_fingerprint(raw: Any) -> dict[str, str]:
    """Require a small explicit set of stable files and recorded SHA-256 hashes."""
    if not isinstance(raw, Mapping) or not 1 <= len(raw) <= 16:
        raise ValueError(
            "continuity_fingerprint requires 1..16 file paths and SHA-256 hashes"
        )
    for path, digest in raw.items():
        if (
            not isinstance(path, str)
            or not path.startswith(("/", "~/"))
            or len(path) > 1000
            or ".." in PurePosixPath(path).parts
            or path in {"/", "~/"}
            or any(ord(char) < 32 for char in path)
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise ValueError(
                "continuity_fingerprint requires absolute or ~/ file paths and lowercase SHA-256 hashes"
            )
    return dict(raw)


def require_continuity_state(case: Any) -> None:
    """A fingerprint belongs only to a case that keeps the machine as found."""
    config = (
        case.get("method_config", {})
        if isinstance(case, Mapping)
        else case.method_config
    )
    if KEY not in config:
        return
    state = (
        case.get("starting_state") if isinstance(case, Mapping) else case.starting_state
    )
    if state != "as_is":
        raise ValueError(
            "continuity_fingerprint requires starting_state as_is; remove the reset or fingerprint"
        )
    normalize_fingerprint(config[KEY])


CONTINUITY_PROTOCOL = "host-control-continuity-v1"


def execution_protocol(cases: Any) -> str:
    """Old runners must reject a continuity contract rather than ignore it."""
    from yoke_contracts.machine_qa_host_control import HOST_CONTROL_PROTOCOL

    return (
        CONTINUITY_PROTOCOL
        if any(KEY in case.method_config for case in cases)
        else HOST_CONTROL_PROTOCOL
    )


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
