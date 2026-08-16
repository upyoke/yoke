"""Capability-shaped test-environment declaration."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.test_environment_declaration import (
    CAPABILITY_TYPE,
    TestEnvironmentDeclaration,
    load_declaration,
    parse_declaration,
    resolve_uv_projects,
)


def test_parse_splits_csv_and_strips() -> None:
    declaration = parse_declaration(
        "platform",
        {
            "uv_project": " services/platform-svc ",
            "uv_extras": "engine, types",
            "uv_groups": "dev,",
        },
    )
    assert declaration.uv_project == "services/platform-svc"
    assert declaration.extras == ("engine", "types")
    assert declaration.groups == ("dev",)


def test_empty_settings_are_the_default_sync() -> None:
    declaration = parse_declaration("yoke", {})
    assert declaration.sync_argv() == ["uv", "sync", "--frozen"]
    assert declaration.run_python_argv(["-m", "pytest"]) == [
        "uv",
        "run",
        "--frozen",
        "python3",
        "-m",
        "pytest",
    ]


def test_run_python_argv_adds_extras_and_optional_project(
    tmp_path: Path,
) -> None:
    nested = tmp_path / "services" / "platform-svc"
    nested.mkdir(parents=True)
    (nested / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (nested / "uv.lock").write_text("", encoding="utf-8")
    declaration = TestEnvironmentDeclaration(
        project="platform",
        uv_project="services/platform-svc",
        extras=("engine",),
    )
    from_root = declaration.run_python_argv(["-m", "pytest"], cwd=tmp_path)
    assert from_root[:6] == [
        "uv",
        "run",
        "--frozen",
        "--project",
        "services/platform-svc",
        "--extra",
    ]
    from_nested = declaration.run_python_argv(["-m", "pytest"], cwd=nested)
    assert "--project" not in from_nested
    assert from_nested[3:5] == ["--extra", "engine"]


def test_resolve_uv_projects_refuses_a_missing_declared_path(
    tmp_path: Path,
) -> None:
    declaration = TestEnvironmentDeclaration(
        project="platform", uv_project="services/missing"
    )
    error = resolve_uv_projects(tmp_path, declaration, discover=lambda _p: [])
    assert isinstance(error, str)
    assert "services/missing" in error
    assert CAPABILITY_TYPE in error


def test_load_declaration_defaults_when_relay_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.control_plane_transport.relay",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("not_found")),
    )
    declaration = load_declaration("yoke")
    assert declaration.extras == ()
    assert declaration.groups == ()
    assert declaration.uv_project == ""
