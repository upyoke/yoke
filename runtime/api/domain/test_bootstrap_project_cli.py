"""bootstrap_project — main CLI entry and _resolve_context coverage.

Split out of ``test_bootstrap_project.py`` to keep authored files under the
350-line limit.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.bootstrap_project import _resolve_context, main


def test_main_cli_preflight_only_skips_setup(tmp_path: Path, monkeypatch, capsys) -> None:
    calls: list[str] = []

    monkeypatch.setattr("yoke_core.domain.bootstrap_project.run_preflight", lambda ctx: calls.append("preflight") or 0)
    monkeypatch.setattr("yoke_core.domain.bootstrap_project.run_setup", lambda ctx: calls.append("setup") or 0)
    monkeypatch.setattr("yoke_core.domain.bootstrap_project.run_verify", lambda ctx: calls.append("verify") or 0)

    try:
        main(
            [
                "cli",
                "buzz",
                "--preflight-only",
                "--project-root",
                str(tmp_path),
                "--script-dir",
                str(tmp_path / ".agents" / "skills" / "yoke" / "scripts"),
                "--yoke-db",
                str(tmp_path / "runtime" / "yoke.db"),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 0

    assert calls == ["preflight"]
    assert "Preflight-only mode: skipping setup." in capsys.readouterr().out


def test_main_cli_runs_full_flow(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr("yoke_core.domain.bootstrap_project.run_preflight", lambda ctx: calls.append("preflight") or 0)
    monkeypatch.setattr("yoke_core.domain.bootstrap_project.run_setup", lambda ctx: calls.append("setup") or 0)
    monkeypatch.setattr("yoke_core.domain.bootstrap_project.run_verify", lambda ctx: calls.append("verify") or 0)

    try:
        main(
            [
                "cli",
                "buzz",
                "--project-root",
                str(tmp_path),
                "--script-dir",
                str(tmp_path / ".agents" / "skills" / "yoke" / "scripts"),
                "--yoke-db",
                str(tmp_path / "runtime" / "yoke.db"),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 0

    assert calls == ["preflight", "setup", "verify"]


def test_resolve_context_autodetects_paths(tmp_path: Path, monkeypatch) -> None:
    """Launcher may omit --project-root/--script-dir/--yoke-db; Python infers tokens."""
    fake_project_root = tmp_path / "repo"
    fake_project_root.mkdir()

    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project.resolve_main_root",
        lambda: str(fake_project_root),
    )
    monkeypatch.delenv("YOKE_SCRIPTS_DIR", raising=False)

    import argparse

    args = argparse.Namespace(
        project="buzz",
        project_root=None,
        script_dir=None,
        yoke_db=None,
    )
    ctx = _resolve_context(args)

    assert ctx.project == "buzz"
    assert ctx.project_root == fake_project_root
    assert ctx.yoke_db == fake_project_root / "data" / "yoke.db"
    assert ctx.script_dir == fake_project_root / ".agents" / "skills" / "yoke" / "scripts"


def test_resolve_context_respects_yoke_scripts_dir_env(tmp_path: Path, monkeypatch) -> None:
    """YOKE_SCRIPTS_DIR env var overrides the default script dir inference."""
    fake_project_root = tmp_path / "repo"
    fake_project_root.mkdir()
    override_scripts = tmp_path / "real-scripts"
    override_scripts.mkdir()

    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project.resolve_main_root",
        lambda: str(fake_project_root),
    )
    monkeypatch.setenv("YOKE_SCRIPTS_DIR", str(override_scripts))

    import argparse

    args = argparse.Namespace(
        project="buzz",
        project_root=None,
        script_dir=None,
        yoke_db=None,
    )
    ctx = _resolve_context(args)

    assert ctx.script_dir == override_scripts


def test_resolve_context_explicit_args_override_autodetect(tmp_path: Path, monkeypatch) -> None:
    """Explicit CLI args take precedence over auto-detection."""
    # Poison the autodetectors so any accidental fallback surfaces as a clear failure.
    monkeypatch.setattr(
        "yoke_core.domain.bootstrap_project.resolve_main_root",
        lambda: (_ for _ in ()).throw(AssertionError("should not be called")),
    )
    import argparse

    args = argparse.Namespace(
        project="buzz",
        project_root=str(tmp_path),
        script_dir=str(tmp_path / "scripts"),
        yoke_db=str(tmp_path / "yoke.db"),
    )
    ctx = _resolve_context(args)

    assert ctx.project_root == tmp_path
    assert ctx.script_dir == tmp_path / "scripts"
    assert ctx.yoke_db == tmp_path / "yoke.db"
