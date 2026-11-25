"""File-line refusals name splitting as the recovery, never a gate bypass."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_harness.git_hooks import file_line_cli


def _grown() -> SimpleNamespace:
    return SimpleNamespace(
        path="runtime/big.py", old_line_count=0, new_line_count=353, delta=353
    )


def test_check_cli_failure_names_splitting(capsys) -> None:
    verdict = SimpleNamespace(
        ok=False,
        summary="1 hard-fail(s)",
        hard_fails=[_grown()],
        warnings=[],
        pre_existing=[],
    )
    file_line_cli.print_verdict(verdict, limit=350, as_json=False)
    out = capsys.readouterr().out
    assert "Split or shorten each file named above" in out
    assert "--no-verify" not in out
