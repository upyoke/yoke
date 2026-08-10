"""Loaded packages must survive the deletion of the tree they came from.

A merge finishes by removing the lane worktree, and the process running it may
have imported its own packages from there. Python caches a package's
``__path__`` at first import, so every lazy submodule import issued after the
removal searches a directory that no longer exists — the close-out then fails
on ``ImportError`` after the merge already landed. These tests use synthetic
packages so the live test process never has its real package paths rewritten.
"""

from __future__ import annotations

import shutil
import sys

from yoke_core.domain.worktree_import_reseat import (
    reseat_loaded_packages,
    reseat_off_launch_directory,
)


def _build_parallel_trees(tmp_path, *, pkg_name):
    doomed = tmp_path / "lane"
    surviving = tmp_path / "main"
    for base, marker in ((doomed, "from-lane"), (surviving, "from-main")):
        package = base / pkg_name
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("")
        (package / "sub.py").write_text(f"VALUE = {marker!r}\n")
    return doomed, surviving


def _load_from(directory, pkg_name):
    sys.path.insert(0, str(directory))
    try:
        return __import__(pkg_name)
    finally:
        sys.path.remove(str(directory))


def _forget(pkg_name):
    for name in list(sys.modules):
        if name == pkg_name or name.startswith(pkg_name + "."):
            sys.modules.pop(name, None)


class TestReseatLoadedPackages:
    def test_cached_path_is_repointed_at_the_surviving_tree(self, tmp_path):
        pkg_name = "_synthpkg_reseat_repoint"
        doomed, surviving = _build_parallel_trees(tmp_path, pkg_name=pkg_name)
        try:
            module = _load_from(doomed, pkg_name)
            assert list(module.__path__)[0] == str(doomed / pkg_name)
            shutil.rmtree(str(doomed))

            reseated = reseat_loaded_packages(
                doomed_root=doomed, surviving_root=surviving,
            )

            assert pkg_name in reseated
            assert list(sys.modules[pkg_name].__path__)[0] == str(
                (surviving / pkg_name).resolve()
            )
        finally:
            _forget(pkg_name)

    def test_lazy_submodule_import_succeeds_after_the_tree_is_deleted(
        self, tmp_path,
    ):
        pkg_name = "_synthpkg_reseat_lazy"
        doomed, surviving = _build_parallel_trees(tmp_path, pkg_name=pkg_name)
        try:
            module = _load_from(doomed, pkg_name)
            assert any(str(doomed) in entry for entry in list(module.__path__))
            shutil.rmtree(str(doomed))

            reseat_loaded_packages(doomed_root=doomed, surviving_root=surviving)

            # Submodule import consults the package's cached ``__path__``, not
            # ``sys.path``, so this is the exact import that used to raise.
            submodule = __import__(pkg_name + ".sub", fromlist=["sub"])
            assert submodule.VALUE == "from-main"
        finally:
            _forget(pkg_name)

    def test_packages_outside_the_doomed_tree_are_left_alone(self, tmp_path):
        pkg_name = "_synthpkg_reseat_elsewhere"
        doomed, surviving = _build_parallel_trees(tmp_path, pkg_name=pkg_name)
        elsewhere = tmp_path / "elsewhere"
        (elsewhere / pkg_name).mkdir(parents=True)
        (elsewhere / pkg_name / "__init__.py").write_text("")
        try:
            module = _load_from(elsewhere, pkg_name)
            before = list(module.__path__)

            assert reseat_loaded_packages(
                doomed_root=doomed, surviving_root=surviving,
            ) == []
            assert list(sys.modules[pkg_name].__path__) == before
        finally:
            _forget(pkg_name)

    def test_no_work_when_the_process_already_runs_from_the_surviving_tree(
        self, tmp_path,
    ):
        pkg_name = "_synthpkg_reseat_same_tree"
        (tmp_path / pkg_name).mkdir()
        (tmp_path / pkg_name / "__init__.py").write_text("")
        try:
            _load_from(tmp_path, pkg_name)

            assert reseat_loaded_packages(
                doomed_root=tmp_path, surviving_root=tmp_path,
            ) == []
        finally:
            _forget(pkg_name)


class TestReseatOffLaunchDirectory:
    def test_launch_directory_is_read_back_from_the_anchor_package(
        self, tmp_path,
    ):
        pkg_name = "_synthpkg_reseat_anchor"
        doomed, surviving = _build_parallel_trees(tmp_path, pkg_name=pkg_name)
        try:
            _load_from(doomed, pkg_name)
            shutil.rmtree(str(doomed))

            reseated = reseat_off_launch_directory(
                surviving, anchor_package=pkg_name,
            )

            assert pkg_name in reseated
        finally:
            _forget(pkg_name)

    def test_an_unloaded_anchor_reseats_nothing(self, tmp_path):
        assert reseat_off_launch_directory(
            tmp_path, anchor_package="_synthpkg_reseat_never_loaded",
        ) == []
