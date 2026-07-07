"""Core tests for ``install_yoke_launcher``."""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

from yoke_core.tools import install_yoke_launcher as isl
from yoke_core.tools import install_yoke_launcher_cleanup as cleanup


@pytest.fixture(autouse=True)
def no_real_editable_cleanup(monkeypatch):
    monkeypatch.setattr(
        isl,
        "cleanup_stale_editable_yoke_metadata",
        lambda *args, **kwargs: 0,
    )


def test_priority_tuple_is_single_source_of_truth():
    assert isl.TARGET_PRIORITY == (
        ("/opt/homebrew/bin", "homebrew_apple_silicon"),
        ("/usr/local/bin", "homebrew_intel_or_linux"),
        ("~/.local/bin", "fallback_user_local"),
    )


def test_verify_python_version_accepts_low_floor():
    isl.verify_python_version(min_version=(3, 0))


def test_verify_python_version_raises_when_below_minimum():
    too_new = (sys.version_info.major, sys.version_info.minor + 5)
    with pytest.raises(isl.InstallError):
        isl.verify_python_version(min_version=too_new)


def test_verify_repo_root_accepts_yoke_pyproject(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('name = "yoke"\nversion = "0.1.0"\n')
    assert isl.verify_repo_root(tmp_path) == tmp_path


def test_verify_repo_root_rejects_missing_pyproject(tmp_path: Path):
    with pytest.raises(isl.InstallError, match="no pyproject.toml"):
        isl.verify_repo_root(tmp_path)


def test_verify_repo_root_rejects_wrong_package(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text('name = "other-pkg"\n')
    with pytest.raises(isl.InstallError, match="does not declare"):
        isl.verify_repo_root(tmp_path)


_PYPROJECT_WITH_DEPS = (
    '[project]\n'
    'name = "yoke"\n'
    'version = "0.1.0"\n'
    'dependencies = [\n'
    '    "fastapi==0.128.8",\n'
    '    "uvicorn[standard]==0.39.0",\n'
    '    "pydantic==2.13.4",\n'
    ']\n'
    '\n'
    '[project.optional-dependencies]\n'
    'test = [\n'
    '    "pytest==8.4.2",\n'
    ']\n'
)


def test_read_pyproject_deps_parses_top_level_array(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT_WITH_DEPS)
    assert isl.read_pyproject_deps(tmp_path) == [
        "fastapi==0.128.8",
        "uvicorn[standard]==0.39.0",
        "pydantic==2.13.4",
    ]


def test_read_pyproject_deps_skips_optional_dependencies(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT_WITH_DEPS)
    result = isl.read_pyproject_deps(tmp_path)
    assert "pytest==8.4.2" not in result


def test_read_pyproject_deps_skips_workspace_packages(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\n'
        'name = "yoke"\n'
        'version = "0.1.0"\n'
        'dependencies = [\n'
        '    "yoke-contracts",\n'
        '    "yoke_cli>=0.1.0",\n'
        '    "fastapi==0.128.8",\n'
        ']\n'
    )

    assert isl.read_pyproject_deps(tmp_path) == ["fastapi==0.128.8"]


def test_read_pyproject_deps_regex_fallback_matches_tomllib(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT_WITH_DEPS)
    real_import = (
        __builtins__["__import__"]
        if isinstance(__builtins__, dict)
        else __builtins__.__import__
    )

    def fake_import(name, *args, **kwargs):
        if name == "tomllib":
            raise ImportError("simulated 3.9/3.10 environment")
        return real_import(name, *args, **kwargs)

    with mock.patch("builtins.__import__", side_effect=fake_import):
        result = isl.read_pyproject_deps(tmp_path)
    assert result == [
        "fastapi==0.128.8",
        "uvicorn[standard]==0.39.0",
        "pydantic==2.13.4",
    ]


def test_read_pyproject_deps_raises_when_missing(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "yoke"\nversion = "0.1.0"\n'
    )
    with pytest.raises(isl.InstallError, match="dependencies array"):
        isl.read_pyproject_deps(tmp_path)


def test_read_pyproject_deps_matches_real_yoke_pyproject():
    repo_root = Path(__file__).resolve().parents[3]
    deps = isl.read_pyproject_deps(repo_root)
    assert deps, "Yoke pyproject should declare runtime deps"
    for dep in deps:
        assert any(op in dep for op in ("==", ">=", "~=", "<", ">")), (
            f"unpinned dep {dep!r} in pyproject.toml - installer needs pins"
        )


def _write_minimal_pyproject(cwd: Path) -> None:
    (cwd / "pyproject.toml").write_text(_PYPROJECT_WITH_DEPS)


_EXPECTED_DEPS = [
    "fastapi==0.128.8",
    "uvicorn[standard]==0.39.0",
    "pydantic==2.13.4",
]


def test_run_pip_install_deps_installs_pinned_deps(tmp_path: Path):
    _write_minimal_pyproject(tmp_path)
    with mock.patch.object(isl.subprocess, "check_call") as cc, \
         mock.patch.object(isl, "_is_externally_managed", return_value=False):
        isl.run_pip_install_deps(tmp_path)
    assert cc.call_args_list[0] == mock.call(
        [
            sys.executable,
            "-m",
            "pip",
            "uninstall",
            "-y",
            *isl.YOKE_EDITABLE_PACKAGE_NAMES,
        ],
        cwd=str(tmp_path),
        env=mock.ANY,
    )
    assert cc.call_args_list[1] == mock.call(
        [sys.executable, "-m", "pip", "install", *_EXPECTED_DEPS],
        cwd=str(tmp_path),
        env=mock.ANY,
    )


def test_run_pip_install_deps_uninstalls_old_yoke_packages_first(
    tmp_path: Path,
):
    _write_minimal_pyproject(tmp_path)
    calls = []

    def fake_check_call(argv, **kwargs):
        calls.append((argv, kwargs))
        return 0

    with mock.patch.object(isl.subprocess, "check_call", side_effect=fake_check_call), \
         mock.patch.object(isl, "_is_externally_managed", return_value=False):
        isl.run_pip_install_deps(tmp_path)

    assert calls[0][0][:5] == [
        sys.executable,
        "-m",
        "pip",
        "uninstall",
        "-y",
    ]
    assert tuple(calls[0][0][5:]) == isl.YOKE_EDITABLE_PACKAGE_NAMES
    assert calls[1][0][:4] == [sys.executable, "-m", "pip", "install"]


def test_cleanup_stale_editable_metadata_removes_recorded_files(
    tmp_path: Path, monkeypatch
):
    site = tmp_path / "site-packages"
    dist_info = site / "yoke_cli-0.1.0.dist-info"
    dist_info.mkdir(parents=True)
    pth = site / "__editable__.yoke_cli-0.1.0.pth"
    pth.write_text("old-target\n")
    (dist_info / "direct_url.json").write_text(
        '{"dir_info": {"editable": true}, '
        '"url": "file:///tmp/deleted-yoke/packages/yoke-cli"}'
    )
    (dist_info / "RECORD").write_text(
        "__editable__.yoke_cli-0.1.0.pth,,\n"
        "yoke_cli-0.1.0.dist-info/direct_url.json,,\n"
        "yoke_cli-0.1.0.dist-info/RECORD,,\n"
    )
    monkeypatch.setattr(cleanup.sysconfig, "get_path", lambda name: str(site))

    stream = io.StringIO()
    removed = cleanup.cleanup_stale_editable_yoke_metadata(
        ("yoke-cli",),
        stream=stream,
    )

    assert removed == 4
    assert not pth.exists()
    assert not dist_info.exists()
    assert "yoke-cli" in stream.getvalue()


def test_run_pip_install_deps_auto_sets_pip_break_when_marker_present(
    tmp_path: Path, monkeypatch
):
    _write_minimal_pyproject(tmp_path)
    monkeypatch.delenv("PIP_BREAK_SYSTEM_PACKAGES", raising=False)
    stream = io.StringIO()
    with mock.patch.object(isl.subprocess, "check_call") as cc, \
         mock.patch.object(isl, "_is_externally_managed", return_value=True):
        isl.run_pip_install_deps(tmp_path, stream=stream)
    _, kwargs = cc.call_args_list[-1]
    assert kwargs["env"]["PIP_BREAK_SYSTEM_PACKAGES"] == "1"
    assert "externally-managed" in stream.getvalue().lower()


def test_run_pip_install_deps_respects_existing_pip_break_env(
    tmp_path: Path, monkeypatch
):
    _write_minimal_pyproject(tmp_path)
    monkeypatch.setenv("PIP_BREAK_SYSTEM_PACKAGES", "1")
    stream = io.StringIO()
    with mock.patch.object(isl.subprocess, "check_call"), \
         mock.patch.object(isl, "_is_externally_managed", return_value=True):
        isl.run_pip_install_deps(tmp_path, stream=stream)
    assert "externally-managed" not in stream.getvalue().lower()


def test_run_pip_install_deps_no_system_packages_raises_on_marker(
    tmp_path: Path, monkeypatch
):
    _write_minimal_pyproject(tmp_path)
    monkeypatch.delenv("PIP_BREAK_SYSTEM_PACKAGES", raising=False)
    with mock.patch.object(isl, "_is_externally_managed", return_value=True):
        with pytest.raises(isl.InstallError, match="externally-managed"):
            isl.run_pip_install_deps(tmp_path, allow_system_packages=False)


def test_run_pip_install_deps_no_marker_no_notice(tmp_path: Path, monkeypatch):
    _write_minimal_pyproject(tmp_path)
    monkeypatch.delenv("PIP_BREAK_SYSTEM_PACKAGES", raising=False)
    stream = io.StringIO()
    with mock.patch.object(isl.subprocess, "check_call") as cc, \
         mock.patch.object(isl, "_is_externally_managed", return_value=False):
        isl.run_pip_install_deps(tmp_path, stream=stream)
    _, kwargs = cc.call_args
    assert "PIP_BREAK_SYSTEM_PACKAGES" not in kwargs["env"]
    assert stream.getvalue() == ""


def test_auto_detect_target_picks_first_writable_on_path(tmp_path: Path):
    homebrew = tmp_path / "opt-homebrew-bin"
    homebrew.mkdir()
    env_path = f"{homebrew}{os.pathsep}/usr/bin"
    with mock.patch.object(
        isl,
        "TARGET_PRIORITY",
        (
            (str(homebrew), "homebrew_apple_silicon"),
            ("/nonexistent/usr/local/bin", "homebrew_intel_or_linux"),
            ("~/.local/bin", "fallback_user_local"),
        ),
    ):
        choice = isl.auto_detect_target(home=tmp_path, env_path=env_path)
    assert choice.path == homebrew.resolve()
    assert choice.label == "homebrew_apple_silicon"


def test_auto_detect_target_target_dir_override(tmp_path: Path):
    custom = tmp_path / "custom-bin"
    choice = isl.auto_detect_target(home=tmp_path, override=str(custom), env_path="")
    assert choice.path == custom.resolve()
    assert choice.label == "override"


def test_auto_detect_target_force_user_picks_third(tmp_path: Path):
    choice = isl.auto_detect_target(home=tmp_path, force_user=True, env_path="")
    assert choice.label == "fallback_user_local"
    assert str(choice.path).endswith(".local/bin")


def test_auto_detect_target_force_system_picks_second(tmp_path: Path):
    choice = isl.auto_detect_target(home=tmp_path, force_system=True, env_path="")
    assert choice.label == "homebrew_intel_or_linux"
    assert str(choice.path) == "/usr/local/bin"


def test_auto_detect_target_skips_writable_but_not_on_path(tmp_path: Path):
    off_path = tmp_path / "off-path"
    off_path.mkdir()
    user_local = tmp_path / "user-local"
    with mock.patch.object(
        isl,
        "TARGET_PRIORITY",
        (
            (str(off_path), "homebrew_apple_silicon"),
            ("/nonexistent/usr/local/bin", "homebrew_intel_or_linux"),
            (str(user_local), "fallback_user_local"),
        ),
    ):
        choice = isl.auto_detect_target(home=tmp_path, env_path="/usr/bin")
    assert choice.label == "fallback_user_local"
