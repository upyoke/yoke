"""Resolve and protect a Command case's bound candidate source."""

from __future__ import annotations

import json
import os
from pathlib import Path

from yoke_contracts.qa_case_environment import COMMAND_CASE_CANDIDATE_TREE_ENV


def resolve(lane: Path | str | None) -> tuple[Path | None, str | None]:
    """Use the candidate by default; refuse a conflicting explicit lane."""
    raw = os.environ.get(COMMAND_CASE_CANDIDATE_TREE_ENV)
    if raw is None:
        return None, None
    try:
        binding = json.loads(raw)
        candidate_root = binding["root"]
        head_sha = binding["head_sha"]
        if not isinstance(candidate_root, str) or not candidate_root:
            raise ValueError("root must be a non-empty string")
        if not isinstance(head_sha, str) or not head_sha:
            raise ValueError("head_sha must be a non-empty string")
        candidate = Path(candidate_root).resolve()
    except (ValueError, TypeError, KeyError) as exc:
        return None, (
            f"QA-CANDIDATE-BINDING REFUSAL: {COMMAND_CASE_CANDIDATE_TREE_ENV} "
            f"is invalid ({exc}). Re-run the case through the QA runner to "
            "restore its candidate binding."
        )
    if lane is not None and Path(lane).expanduser().resolve() != candidate:
        return None, (
            "QA-CANDIDATE-SOURCE-REBIND REFUSAL: this Command case is bound to "
            f"candidate '{candidate}' at {head_sha}, but --lane selected "
            f"'{lane}'. Omit --lane to use the bound candidate."
        )
    return candidate, None
