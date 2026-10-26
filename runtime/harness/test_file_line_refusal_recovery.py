"""File-line refusals name splitting as the recovery, never a gate bypass."""

from __future__ import annotations

from types import SimpleNamespace

from yoke_harness.git_hooks import file_line_cli, pre_commit


def _grown() -> SimpleNamespace:
    return SimpleNamespace(
        path="runtime/big.py", old_line_count=0, new_line_count=353, delta=353
    )


def test_pre_commit_hard_fail_names_splitting() -> None:
    verdict = SimpleNamespace(hard_fails=[_grown()])
    text = pre_commit._format_file_line_summary(verdict, limit=350)
    assert "Split each file into smaller modules by responsibility" in text
    assert "--no-verify" not in text


def test_diverged_warning_never_teaches_a_bypass() -> None:
    text = pre_commit._format_warning(["foo.py"])
    assert "git add" in text
    assert "--no-verify" not in text


def test_uninspectable_gate_names_the_inspect_command(monkeypatch, capsys) -> None:
    verdict = SimpleNamespace(ok=False, hard_fails=[], summary="git failed")
    monkeypatch.setattr(pre_commit, "_resolve_repo_root", lambda: "/tmp")
    monkeypatch.setattr(
        pre_commit.file_line_check, "changed_files_check", lambda **_kw: verdict
    )
    monkeypatch.setattr(
        pre_commit.file_line_check,
        "resolved_policy",
        lambda _root: SimpleNamespace(limit=350),
    )
    assert pre_commit._run_file_line_check_or_block() == 1
    err = capsys.readouterr().err
    assert "yoke check file-line --staged" in err
    assert "--no-verify" not in err


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
