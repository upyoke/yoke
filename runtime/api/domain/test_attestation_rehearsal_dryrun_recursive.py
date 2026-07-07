"""Recursive ``migration_apply`` self-call detection in the rehearsal dryrun.

Sibling of ``test_attestation_rehearsal_dryrun.py`` so the new check has
test coverage without pushing the main test file over the 350-line cap.

The detection: rehearsal_commands MUST NOT re-invoke
``python3 -m yoke_core.domain.migration_apply rehearse|live-apply``
because the rehearse runner would recurse into itself against the
validation surface — and the validation DB does not have the items
row that named the command. That manifests as ``Item YOK-N not found``
deep in the runner. Caught at refine time and surfaced as
``recursive_migration_apply_self_call``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.attestation_rehearsal_dryrun import _check_command_shape


_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("subcommand", ["rehearse", "live-apply"])
def test_recursive_migration_apply_self_call_caught(subcommand: str) -> None:
    result = _check_command_shape(
        f"python3 -m yoke_core.domain.migration_apply {subcommand} YOK-1",
        _REPO_ROOT,
    )
    assert result is not None
    assert result[0] == "recursive_migration_apply_self_call"


def test_dotted_module_ref_without_subcommand_passes() -> None:
    # A bare ``python3 -m yoke_core.domain.migration_apply --help``
    # (no rehearse/live-apply subcommand) must NOT trigger the
    # recursive-self-call guard — it's a meta-invocation, not a child
    # rehearsal run.
    assert _check_command_shape(
        "python3 -m yoke_core.domain.migration_apply --help",
        _REPO_ROOT,
    ) is None
