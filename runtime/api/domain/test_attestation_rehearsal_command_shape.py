"""Helper-level checks for rehearsal-command shape validation."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from yoke_core.domain.attestation_rehearsal_dryrun import _check_command_shape


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_existing_path_passes(repo_root: Path) -> None:
    assert (
        _check_command_shape(
            f"{sys.executable} -m pytest "
            "runtime/api/domain/test_attestation_rehearsal_dryrun.py -q",
            repo_root,
        )
        is None
    )


def test_unbalanced_quotes_flagged(repo_root: Path) -> None:
    result = _check_command_shape('echo "unbalanced', repo_root)
    assert result is not None
    assert result[0] == "shell_parse_error"


def test_inline_python_source_not_path_token(repo_root: Path) -> None:
    assert (
        _check_command_shape(
            f'{sys.executable} -c "import json; json.dumps({{}})"',
            repo_root,
        )
        is None
    )


def test_dotted_module_ref_not_path_token(repo_root: Path) -> None:
    assert (
        _check_command_shape(
            "python3 -m yoke_core.domain.migration_apply --help",
            repo_root,
        )
        is None
    )
