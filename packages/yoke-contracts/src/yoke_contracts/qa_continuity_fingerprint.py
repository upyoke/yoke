"""Recorded file identities for machine QA that needs an earlier host state."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

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
