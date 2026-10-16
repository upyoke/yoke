"""The record of every harness setting Yoke writes outside a project.

Approval posture and folder trust live in each harness's own user-level
config, beside settings the operator owns. A value Yoke wrote and the same
value the operator chose look identical there, so ``yoke uninstall`` reverts
only what this record says Yoke wrote, and only while the harness still holds
exactly that value (:mod:`yoke_contracts.harness_settings_revert`).

The record lives in the machine home, which uninstall deletes last, after the
revert. Each entry is one of:

- ``{"kind": "json", "file", "keys", "value", "existing_depth"}`` — a JSON
  leaf at ``keys``;
- ``{"kind": "codex_key", "file", "key", "value"}`` — a top-level Codex key;
- ``{"kind": "codex_trust", "file", "trust_key"}`` — a Codex trust table;
- ``{"kind": "created_file", "file"}`` — a file Yoke created whole.
"""

from __future__ import annotations

import json
import os
import fcntl
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from yoke_contracts.machine_config.runtime import yoke_home

LEDGER_NAME = "harness-settings-written.json"


def ledger_path() -> Path:
    return yoke_home() / LEDGER_NAME


def read() -> List[Dict[str, Any]]:
    """Recorded entries; raises ``ValueError`` when the record is unreadable."""
    path = ledger_path()
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(e, dict) for e in payload):
        raise ValueError(f"{path} is not a list of entries")
    return payload


def record(entry: Mapping[str, Any]) -> Optional[str]:
    """Add *entry* once; return a report line when it could not be recorded.

    The harness write already happened, so a failure here never undoes it;
    it is reported so the operator knows uninstall will not revert it.
    """
    path = ledger_path()
    try:
        with mutation() as entries:
            if dict(entry) not in entries:
                entries.append(dict(entry))
    except (OSError, ValueError) as exc:
        return (
            f"not recorded in {path} ({exc}); yoke uninstall will not revert "
            f"this setting in {entry.get('file')}"
        )
    return None


def json_entry(
    file: Path, keys: List[str], value: Any, *, existing_depth: int
) -> Dict[str, Any]:
    """A JSON leaf; ``existing_depth`` containers on its path predate the write.

    Revert drops the containers Yoke created once they are empty, and never
    the ones the operator already had.
    """
    return {
        "kind": "json",
        "file": str(file),
        "keys": list(keys),
        "value": value,
        "existing_depth": existing_depth,
    }


def existing_depth(payload: Any, containers: List[str]) -> int:
    """How many of *containers*, walked from *payload*, already exist."""
    depth = 0
    node = payload
    for key in containers:
        if not isinstance(node, dict) or not isinstance(node.get(key), dict):
            break
        node = node[key]
        depth += 1
    return depth


def codex_key_entry(file: Path, key: str, value: str) -> Dict[str, Any]:
    return {"kind": "codex_key", "file": str(file), "key": key, "value": value}


def codex_trust_entry(file: Path, trust_key: str) -> Dict[str, Any]:
    return {"kind": "codex_trust", "file": str(file), "trust_key": trust_key}


def created_file_entry(file: Path) -> Dict[str, Any]:
    return {"kind": "created_file", "file": str(file)}


@contextmanager
def mutation():
    """Serialize ledger read, selective consumption and atomic replacement."""
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        entries = read()
        before = deepcopy(entries)
        yield entries
        if entries != before:
            tmp = path.with_suffix(path.suffix + ".yoke-tmp")
            tmp.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp, path)


__all__ = [
    "LEDGER_NAME",
    "codex_key_entry",
    "codex_trust_entry",
    "created_file_entry",
    "existing_depth",
    "json_entry",
    "ledger_path",
    "mutation",
    "read",
    "record",
]
