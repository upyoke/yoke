"""Attach the leased host's case ownership to fresh onboarding projects."""

from __future__ import annotations

import json
import os
from pathlib import Path

from yoke_contracts.qa_project_ownership import OWNER_FILE, OWNER_ENV


def test_project_owner() -> str | None:
    if os.environ.get(OWNER_ENV):
        return os.environ[OWNER_ENV]
    marker = Path.home() / ".yoke" / OWNER_FILE
    if not marker.exists():
        return None
    try:
        value = json.loads(marker.read_text())
    except (OSError, ValueError) as exc:
        raise ValueError(
            "qa_project_owner_unreadable: repair the leased host's "
            "owner marker through mission preparation before onboarding"
        ) from exc
    owner = value.get("owner") if isinstance(value, dict) else None
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError(
            "qa_project_owner_invalid: repair the leased host's owner marker "
            "through mission preparation before onboarding a test project"
        )
    return owner
