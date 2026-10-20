"""The authored-file-limit contract names each failing file and its bound."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts.project_contract.file_byte_budget import ByteBudgetFail
from yoke_core.tools import ci_repo_contracts as crc
from yoke_harness.git_hooks import file_line_check as flc


def test_authored_file_limit_failure_names_each_file_and_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = ByteBudgetFail(
        "docs/public/agents/rules/shell-and-cli.md",
        "file_byte_budget_exceeded",
        "3329 bytes, budget 3250 (over by 79)",
    )
    grown = SimpleNamespace(path="runtime/big.py", new_line_count=353)
    monkeypatch.setattr(
        flc,
        "changed_files_check",
        lambda **_kw: SimpleNamespace(
            ok=False,
            summary="1 hard-fail(s), 0 warning(s), 1 byte-budget failure(s)",
            hard_fails=[grown],
            byte_budget_fails=[budget],
        ),
    )
    scope = crc.ChangedPathScope(base_sha="0" * 40, paths=())

    ok, detail = crc.check_authored_file_limit(Path("."), scope)

    assert ok is False
    assert f"runtime/big.py: 353 lines, limit {flc.LIMIT}" in detail
    assert (
        "shell-and-cli.md: file_byte_budget_exceeded: 3329 bytes, budget 3250"
    ) in detail
