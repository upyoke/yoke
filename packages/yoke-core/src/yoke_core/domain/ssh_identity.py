"""Validate the native OpenSSH identity at the actual subprocess boundary."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Sequence

from yoke_contracts.owner_private_path import is_owner_private_file
from yoke_contracts.refusal_recovery import compose_refusal

_NATIVE_WINDOWS = os.name == "nt"


def validate_identity(argv: Sequence[str]) -> None:
    if (
        not _NATIVE_WINDOWS
        or not argv
        or Path(argv[0]).name.lower() not in {"ssh", "ssh.exe"}
    ):
        return
    if "-i" not in argv:
        return
    path = Path(argv[argv.index("-i") + 1]).expanduser()
    if is_owner_private_file(path):
        return
    raise RuntimeError(
        compose_refusal(
            f"ssh_identity_not_private: Windows OpenSSH identity {path} is missing "
            "or permits access beyond its owner and trusted administrators",
            recovery="restore the private key and restrict its Windows Security "
            "permissions to its owner, SYSTEM and Administrators, then retry; "
            "Yoke-managed keys are written with owner-private ACLs",
        )
    )
