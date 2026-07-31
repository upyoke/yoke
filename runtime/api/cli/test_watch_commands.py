"""``yoke watch <kind>`` adapter contract.

Covers the two properties that make the command correct where the bare
module form was not: every registered wrapper is reachable through a
``yoke`` token tuple, and the adapter binds a uv-managed project's own
environment instead of the environment owning the console script.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.commands import watchers
from yoke_cli.commands.tool_shaped import resolve_tool_shaped
from yoke_contracts.watch_cli_forms import WATCH_CLI_TOKENS, cli_form

WRAPPER_MODULES = tuple(WATCH_CLI_TOKENS)


@pytest.mark.parametrize("wrapper_module", WRAPPER_MODULES)
def test_every_wrapper_resolves_through_yoke_tokens(wrapper_module: str) -> None:
    tokens = WATCH_CLI_TOKENS[wrapper_module]
    resolved = resolve_tool_shaped([*tokens, "--", "runtime/api/"])
    assert resolved is not None, f"{wrapper_module} has no yoke CLI tokens"
    _adapter, remaining = resolved
    assert remaining == ["--", "runtime/api/"]


@pytest.mark.parametrize("wrapper_module", WRAPPER_MODULES)
def test_cli_form_is_a_yoke_watch_command(wrapper_module: str) -> None:
    assert cli_form(wrapper_module).startswith("yoke watch ")


def test_cli_form_is_none_for_wrappers_without_an_adapter() -> None:
    assert cli_form("yoke_core.tools.watch_advance") is None


def test_every_cli_form_carries_top_level_usage() -> None:
    forms = {cli_form(module) for module in WRAPPER_MODULES}
    assert forms == set(watchers.TOOL_SHAPED_USAGE)


def test_uv_project_root_requires_lockfile_beside_pyproject(tmp_path: Path) -> None:
    project = tmp_path / "project"
    nested = project / "packages" / "thing"
    nested.mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\n", encoding="utf-8")

    assert watchers.uv_project_root(nested) is None

    (project / "uv.lock").write_text("", encoding="utf-8")
    assert watchers.uv_project_root(nested) == project.resolve()


def _fake_uv_project(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    imports: bool = True,
) -> None:
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    (root / "uv.lock").write_text("", encoding="utf-8")
    monkeypatch.chdir(root)
    monkeypatch.setattr(watchers.shutil, "which", lambda _name: "/usr/bin/uv")
    monkeypatch.setattr(watchers, "project_env_imports", lambda _module: imports)


def test_reexec_binds_the_project_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _fake_uv_project(project, monkeypatch)

    argv = watchers.reexec_argv("yoke_core.tools.watch_pytest", ["--", "tests/"])

    assert argv == [
        "uv",
        "run",
        "--frozen",
        "python3",
        "-m",
        "yoke_core.tools.watch_pytest",
        "--",
        "tests/",
    ]


def test_reexec_declines_outside_a_uv_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(watchers.shutil, "which", lambda _name: "/usr/bin/uv")

    assert watchers.reexec_argv("yoke_core.tools.watch_pytest", []) is None


def test_reexec_declines_without_uv_on_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_uv_project(tmp_path, monkeypatch)
    monkeypatch.setattr(watchers.shutil, "which", lambda _name: None)

    assert watchers.reexec_argv("yoke_core.tools.watch_pytest", []) is None


def test_reexec_declines_when_the_project_env_cannot_import_the_wrapper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A project that installed Yoke as an isolated tool.

    ``yoke`` is on PATH but its own locked environment has no
    ``yoke_core``, so re-execing would reproduce the import failure this
    command exists to avoid. Run in-process instead.
    """
    _fake_uv_project(tmp_path, monkeypatch, imports=False)

    assert watchers.reexec_argv("yoke_core.tools.watch_pytest", []) is None


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], False),
        (["--help"], True),
        (["-h"], True),
        (["--", "--help"], False),
        (["--print-streaming-pair", "--", "tests/"], False),
    ],
)
def test_help_flag_before_the_separator_belongs_to_the_command(
    args: list[str],
    expected: bool,
) -> None:
    assert watchers._wants_help(args) is expected


def test_help_renders_under_the_command_the_operator_typed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    adapter = watchers.TOOL_SHAPED_SUBCOMMANDS[("watch", "pytest")]

    assert adapter(["--help"]) == 0

    assert "usage: yoke watch pytest" in capsys.readouterr().out
