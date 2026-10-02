"""Prevent lane-source commands from changing a Command case's candidate."""

from __future__ import annotations

import json
import os
from pathlib import Path

from yoke_contracts.qa_case_environment import COMMAND_CASE_CANDIDATE_TREE_ENV


def refusal(root: Path) -> str | None:
    """Judge the selected source root before any child command is launched."""
    raw = os.environ.get(COMMAND_CASE_CANDIDATE_TREE_ENV)
    if raw is None:
        return None
    recovery = (
        "Drop the `yoke dev run --` wrapper from the Command case; run "
        "`yoke watch pytest -- <test paths>` directly because it binds its own "
        "cwd to source. Other commands keep the candidate cwd and the product "
        "interpreter; cwd alone does not bind their imports to candidate source."
    )
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
        return (
            f"QA-CANDIDATE-BINDING REFUSAL: {COMMAND_CASE_CANDIDATE_TREE_ENV} "
            f"is invalid ({exc}). Re-run the case through the QA runner to "
            f"restore its candidate binding. {recovery}"
        )
    if root.resolve() == candidate:
        return None
    return (
        "QA-CANDIDATE-SOURCE-REBIND REFUSAL: this Command case is bound to "
        f"candidate '{candidate}' at {head_sha}, but dev run resolved "
        f"'{root.resolve()}'. That source cannot prove the candidate. {recovery}"
    )
