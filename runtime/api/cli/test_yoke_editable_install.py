"""Tests for the config-driven editable path shim.

Covers the loader's resolution order, the installer's artifact swap, and the
end-to-end payoff: imports resolve after a checkout *move* with no reinstall,
because the shim reads the repo root from machine config at each interpreter
start instead of a baked-in absolute path.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from yoke_cli.config import _editable_loader_template as loader
from yoke_cli.config import editable_install


def _make_checkout(root: Path) -> Path:
    """Create a minimal tree that :func:`loader._is_yoke_checkout` accepts."""
    for name in ("yoke-contracts", "yoke-cli", "yoke-harness", "yoke-core"):
        pkg = name.replace("-", "_")
        (root / "packages" / name / "src" / pkg).mkdir(parents=True, exist_ok=True)
    (root / "packages" / "yoke-core" / "src" / "yoke_core" / "__init__.py").write_text(
        "", encoding="utf-8"
    )
    (root / "runtime").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "__init__.py").write_text("", encoding="utf-8")
    return root


def _write_config(path: Path, *checkouts: Path) -> Path:
    projects = {str(c): {"project_id": 1 + i} for i, c in enumerate(checkouts)}
    path.write_text(json.dumps({"projects": projects}), encoding="utf-8")
    return path


# --- loader: resolution order ------------------------------------------------


def test_resolve_prefers_valid_repo_root_env(tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    other = _make_checkout(tmp_path / "other")
    config = _write_config(tmp_path / "config.json", other)

    resolved = loader.resolve_repo_root(
        environ={"YOKE_REPO_ROOT": str(checkout)}, config_path=config
    )

    assert resolved == checkout


def test_resolve_ignores_bogus_repo_root_env_and_uses_config(tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    config = _write_config(tmp_path / "config.json", checkout)

    resolved = loader.resolve_repo_root(
        environ={"YOKE_REPO_ROOT": str(tmp_path / "does-not-exist")},
        config_path=config,
    )

    assert resolved == checkout


def test_resolve_picks_yoke_shaped_project_among_several(tmp_path: Path) -> None:
    not_a_checkout = tmp_path / "buzz"
    not_a_checkout.mkdir()
    checkout = _make_checkout(tmp_path / "yoke")
    config = _write_config(tmp_path / "config.json", not_a_checkout, checkout)

    resolved = loader.resolve_repo_root(environ={}, config_path=config)

    assert resolved == checkout


def test_relative_machine_config_env_anchors_under_machine_home(tmp_path: Path) -> None:
    home = tmp_path / "machine-home"
    checkout = _make_checkout(tmp_path / "checkout")
    config = home / "machine-config" / "config.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    _write_config(config, checkout)

    resolved = loader.resolve_repo_root(
        environ={
            "YOKE_MACHINE_HOME": str(home),
            "YOKE_MACHINE_CONFIG_FILE": "machine-config/config.json",
        }
    )

    assert resolved == checkout


def test_resolve_returns_none_when_nothing_matches(tmp_path: Path) -> None:
    config = _write_config(tmp_path / "config.json")  # empty projects

    resolved = loader.resolve_repo_root(environ={}, config_path=config)

    assert resolved is None


def test_editable_paths_are_src_dirs_then_root_skipping_missing(tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    # Drop one src dir to prove missing entries are skipped, not emitted.
    harness_src = checkout / "packages" / "yoke-harness" / "src"
    for child in list(harness_src.iterdir()):
        child.rmdir()
    harness_src.rmdir()

    paths = loader.editable_paths(checkout)

    assert paths[-1] == str(checkout)
    assert str(checkout / "packages" / "yoke-core" / "src") in paths
    assert all("yoke-harness" not in p for p in paths)


def test_install_into_sys_path_appends_and_dedups(monkeypatch, tmp_path: Path) -> None:
    checkout = _make_checkout(tmp_path / "checkout")
    config = _write_config(tmp_path / "config.json", checkout)
    sentinel = "/sentinel/pythonpath/entry"
    monkeypatch.setattr(sys, "path", [sentinel, *sys.path])

    added = loader.install_into_sys_path(environ={}, config_path=config)

    assert added, "expected the checkout src dirs to be added"
    # Appended, never inserted: the pre-existing PYTHONPATH entry stays first so
    # an explicit worktree override still wins.
    assert sys.path[0] == sentinel
    assert all(sys.path.index(entry) > 0 for entry in added)
    # Idempotent: a second call adds nothing.
    assert loader.install_into_sys_path(environ={}, config_path=config) == []


def test_install_into_sys_path_never_raises_on_bad_config(tmp_path: Path) -> None:
    bad = tmp_path / "config.json"
    bad.write_text("not json {", encoding="utf-8")

    assert loader.install_into_sys_path(environ={}, config_path=bad) == []
    assert loader.install_into_sys_path(environ={}, config_path=tmp_path / "nope") == []


# --- installer: artifact swap ------------------------------------------------


def test_loader_source_is_verbatim_template() -> None:
    assert editable_install.loader_source() == Path(
        loader.__file__
    ).read_text(encoding="utf-8")


def test_swap_writes_shim_and_removes_stale_pip_artifacts(tmp_path: Path) -> None:
    site = tmp_path / "site-packages"
    site.mkdir()
    checkout = _make_checkout(tmp_path / "checkout")
    # Stale setuptools editable artifacts for Yoke + an unrelated distribution.
    (site / "__editable__.yoke-0.1.1.dev1.pth").write_text("x", encoding="utf-8")
    (site / "__editable__.yoke_core-0.1.1.dev1.pth").write_text("x", encoding="utf-8")
    (site / "__editable___yoke_0_1_1_dev1_finder.py").write_text("x", encoding="utf-8")
    (site / "__editable__.buzz-9.9.pth").write_text("keep", encoding="utf-8")

    report = editable_install.swap_to_config_driven(site, repo_root=checkout)

    assert (site / "_yoke_editable_loader.py").read_text(
        encoding="utf-8"
    ) == editable_install.loader_source()
    assert (site / editable_install.SIDECAR_FILE_NAME).read_text(
        encoding="utf-8"
    ).strip() == str(checkout.resolve())
    assert (site / editable_install.PTH_FILE_NAME).read_text(
        encoding="utf-8"
    ) == editable_install.PTH_CONTENT
    # Yoke pip artifacts gone; the unrelated distribution untouched.
    assert not (site / "__editable__.yoke-0.1.1.dev1.pth").exists()
    assert not (site / "__editable___yoke_0_1_1_dev1_finder.py").exists()
    assert (site / "__editable__.buzz-9.9.pth").exists()
    assert len(report["removed"]) == 3


def test_swap_is_idempotent(tmp_path: Path) -> None:
    site = tmp_path / "site-packages"
    site.mkdir()
    checkout = _make_checkout(tmp_path / "checkout")

    first = editable_install.swap_to_config_driven(site, repo_root=checkout)
    second = editable_install.swap_to_config_driven(site, repo_root=checkout)

    assert first["written"] == second["written"]
    assert second["removed"] == []  # nothing stale left the second time


# --- end to end: the .pth resolves the checkout, survives a move -------------


def _sys_path_after_addsitedir(site: Path, config: Path, extra_env=None) -> list[str]:
    """Run the installed .pth in a subprocess and return the resulting sys.path."""
    env = {
        k: v for k, v in _base_env().items() if k != "YOKE_REPO_ROOT"
    }
    env["YOKE_MACHINE_CONFIG_FILE"] = str(config)
    if extra_env:
        env.update(extra_env)
    code = (
        "import site, sys, json;"
        f"site.addsitedir({str(site)!r});"
        "print(json.dumps(sys.path))"
    )
    result = subprocess.run(
        [sys.executable, "-S", "-c", code],
        env=env, text=True, capture_output=True, check=True,
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def _base_env() -> dict:
    import os
    return dict(os.environ)


def test_pth_resolves_checkout_via_config_and_survives_move(tmp_path: Path) -> None:
    site = tmp_path / "site-packages"
    site.mkdir()
    checkout = _make_checkout(tmp_path / "yoke-original")
    editable_install.swap_to_config_driven(site, repo_root=checkout)
    config = _write_config(tmp_path / "config.json", checkout)

    path_before = _sys_path_after_addsitedir(site, config)
    core_src = str(checkout / "packages" / "yoke-core" / "src")
    assert core_src in path_before
    assert str(checkout) in path_before

    # Simulate a checkout MOVE: rename the tree and point config at the new path.
    # The install-time sidecar still names the old (now-gone) path, and we do NOT
    # re-run the installer — config alone must make imports resolve again.
    moved = tmp_path / "yoke-renamed"
    checkout.rename(moved)
    config_moved = _write_config(tmp_path / "config.json", moved)

    path_after = _sys_path_after_addsitedir(site, config_moved)
    assert str(moved / "packages" / "yoke-core" / "src") in path_after
    assert str(moved) in path_after
    assert core_src not in path_after  # the stale original path is not re-added


def test_pth_repo_root_env_overrides_config(tmp_path: Path) -> None:
    site = tmp_path / "site-packages"
    site.mkdir()
    config_checkout = _make_checkout(tmp_path / "from-config")
    env_checkout = _make_checkout(tmp_path / "from-env")
    editable_install.swap_to_config_driven(site, repo_root=config_checkout)
    config = _write_config(tmp_path / "config.json", config_checkout)

    path = _sys_path_after_addsitedir(
        site, config, extra_env={"YOKE_REPO_ROOT": str(env_checkout)}
    )

    assert str(env_checkout / "packages" / "yoke-core" / "src") in path
    assert str(config_checkout / "packages" / "yoke-core" / "src") not in path
