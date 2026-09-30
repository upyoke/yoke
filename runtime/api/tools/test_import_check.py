"""Coverage for the registered source import probe.

Two properties carry the command's whole value. A verdict names the file that
answered the import, so a pass cannot be borrowed from an installed copy of the
module; and a failure arrives diagnosed — a named reason plus the recovery step
— rather than as a raw traceback the caller has to classify.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from yoke_core.tools import import_check


def _checkout(tmp_path: Path) -> Path:
    """Build the marker layout that makes a directory a Yoke source checkout."""
    root = tmp_path / "checkout"
    (root / "packages" / "yoke-core" / "src" / "yoke_core").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    return root


def _install(monkeypatch: pytest.MonkeyPatch, name: str, module: object) -> None:
    monkeypatch.setitem(sys.modules, name, module)


def _module_at(name: str, origin: Path) -> ModuleType:
    module = ModuleType(name)
    module.__file__ = str(origin)
    return module


def test_origin_inside_the_checkout_passes_and_is_named(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _checkout(tmp_path)
    origin = root / "packages" / "yoke-core" / "src" / "yoke_core" / "thing.py"
    origin.write_text("", encoding="utf-8")
    _install(monkeypatch, "lane_owned", _module_at("lane_owned", origin))

    outcome = import_check.check_module("lane_owned", root=root)

    assert outcome.ok
    assert Path(outcome.origin) == origin.resolve()


def test_origin_outside_the_checkout_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An import answered by an installed copy says nothing about the lane, so
    reporting it as a pass would be the confabulation this command closes."""
    root = _checkout(tmp_path)
    elsewhere = tmp_path / "site-packages" / "installed.py"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_text("", encoding="utf-8")
    _install(monkeypatch, "installed", _module_at("installed", elsewhere))

    outcome = import_check.check_module("installed", root=root)

    assert not outcome.ok
    assert "imported from outside this checkout" in outcome.error
    assert str(elsewhere.resolve()) in outcome.error
    assert "yoke dev run" in outcome.error


def test_namespace_package_without_a_source_file_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _checkout(tmp_path)
    _install(monkeypatch, "namespaced", ModuleType("namespaced"))

    outcome = import_check.check_module("namespaced", root=root)

    assert not outcome.ok
    assert "namespace package" in outcome.error
    assert "__init__.py" in outcome.error


def _raising_import(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    def _import(_name: str):
        raise exc

    monkeypatch.setattr(import_check.importlib, "import_module", _import)


def test_missing_module_names_the_checkout_it_searched(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _checkout(tmp_path)
    _raising_import(monkeypatch, ModuleNotFoundError(name="absent.thing"))

    outcome = import_check.check_module("absent.thing", root=root)

    assert not outcome.ok
    assert "no module named 'absent.thing'" in outcome.error
    assert str(root) in outcome.error


def test_missing_dependency_is_distinguished_from_a_missing_target(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The probed module exists; something it imports does not. Naming the
    dependency is the difference between "fix your spelling" and "install it"."""
    root = _checkout(tmp_path)
    _raising_import(monkeypatch, ModuleNotFoundError(name="thirdparty"))

    outcome = import_check.check_module("yoke_core.domain.thing", root=root)

    assert "'thirdparty'" in outcome.error
    assert "not installed or not importable" in outcome.error


def test_circular_import_is_named_as_a_cycle(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _checkout(tmp_path)
    _raising_import(
        monkeypatch,
        ImportError(
            "cannot import name 'shared' from partially initialized module 'a' "
            "(most likely due to a circular import)"
        ),
    )

    outcome = import_check.check_module("a", root=root)

    assert "circular import" in outcome.error
    assert "defer one import into the function" in outcome.error


def test_import_time_failure_is_not_reported_as_an_import_problem(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _checkout(tmp_path)
    _raising_import(monkeypatch, RuntimeError("no config on this machine"))

    outcome = import_check.check_module("yoke_core.domain.thing", root=root)

    assert "raised RuntimeError while executing at import time" in outcome.error
    assert "no config on this machine" in outcome.error
    assert "move the work that failed into a function" in outcome.error


def test_failure_names_the_deepest_frame_inside_the_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The line that broke is the only thing the caller has to open."""
    root = _checkout(tmp_path)
    culprit = root / "packages" / "yoke-core" / "src" / "yoke_core" / "boom.py"
    culprit.write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    def _import(_name: str):
        exec(  # noqa: S102 - builds a traceback whose frame is a real lane file
            compile(culprit.read_text(encoding="utf-8"), str(culprit), "exec"),
            {},
        )

    monkeypatch.setattr(import_check.importlib, "import_module", _import)

    outcome = import_check.check_module("yoke_core.boom", root=root)

    assert f"{culprit}:1" in outcome.error


def test_run_reports_every_failure_together(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A four-module probe names all its failures in one pass; stopping at the
    first would cost a second round trip for the second break."""
    root = _checkout(tmp_path)
    good = root / "packages" / "yoke-core" / "src" / "yoke_core" / "ok.py"
    good.write_text("", encoding="utf-8")

    def _check(module: str, *, root: Path):
        if module == "good":
            return import_check.ImportOutcome(module, str(good), "")
        return import_check.ImportOutcome(module, "", f"{module} is broken")

    monkeypatch.setattr(import_check, "check_module", _check)

    assert import_check.run(["good", "bad", "worse"], root=root) == 1
    captured = capsys.readouterr()
    assert "bad is broken" in captured.err
    assert "worse is broken" in captured.err
    assert "2 of 3 module(s) failed" in captured.err


def test_run_passes_when_every_module_resolves(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _checkout(tmp_path)
    origin = root / "packages" / "yoke-core" / "src" / "yoke_core" / "ok.py"
    origin.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        import_check,
        "check_module",
        lambda module, *, root: import_check.ImportOutcome(module, str(origin), ""),
    )

    assert import_check.run(["one", "two"], root=root) == 0
    captured = capsys.readouterr()
    assert "all 2 module(s) imported" in captured.out
    assert "packages/yoke-core/src/yoke_core/ok.py" in captured.out


def test_a_tree_that_is_not_a_checkout_refuses_rather_than_probing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
    monkeypatch.setattr(import_check, "run", lambda *_a, **_k: pytest.fail("no probe"))
    monkeypatch.chdir(tmp_path)

    assert import_check.main(["yoke_core.domain.thing"]) == 1
    captured = capsys.readouterr()
    assert "refusing to attribute an import to a checkout" in captured.err
    assert "not a Yoke source checkout" in captured.err
    assert "yoke dev run" in captured.err


def test_main_probes_every_module_it_was_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = _checkout(tmp_path)
    captured: dict[str, object] = {}
    monkeypatch.setattr(import_check, "_checkout_root", lambda *_a: (root, None))
    monkeypatch.setattr(
        import_check,
        "run",
        lambda modules, *, root: captured.update({"modules": list(modules)}) or 0,
    )

    assert import_check.main(["alpha", "beta"]) == 0
    assert captured["modules"] == ["alpha", "beta"]


def test_no_module_argument_is_refused() -> None:
    with pytest.raises(SystemExit) as raised:
        import_check.main([])
    assert raised.value.code == 2


def test_cli_adapter_runs_the_probe_through_the_claimed_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lane supplies the ``sys.path`` the verdict is attributed to, so the
    probe must be reached through the source runner rather than run in place."""
    from yoke_cli.commands.adapters import source_dev_run as adapter

    captured: list[str] = []

    def _run(command: list[str]) -> int:
        captured.extend(command)
        return 7

    monkeypatch.setattr(
        adapter.importlib,
        "import_module",
        lambda name: (
            SimpleNamespace(run=_run)
            if name == "yoke_core.tools.source_dev_run"
            else None
        ),
    )

    assert adapter.import_check(["yoke_core.domain.thing"]) == 7
    assert captured == [
        "python3",
        "-m",
        "yoke_core.tools.import_check",
        "yoke_core.domain.thing",
    ]


def test_command_is_registered_as_a_local_tool() -> None:
    from yoke_cli import operation_inventory
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
    from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS, TOOL_SHAPED_USAGE

    assert ("dev", "import-check") not in SUBCOMMAND_REGISTRY
    assert ("dev", "import-check") in TOOL_SHAPED_SUBCOMMANDS
    assert TOOL_SHAPED_USAGE["yoke dev import-check"].startswith(
        "yoke dev import-check MODULE"
    )
    entry = operation_inventory.lookup("yoke dev import-check")
    assert entry is not None
    assert entry.status == operation_inventory.TOOL_CLI
    assert entry.family == "tools.import_check"
