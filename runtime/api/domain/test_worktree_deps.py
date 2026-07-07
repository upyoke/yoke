"""worktree — detect_deps coverage.

Split out of ``test_worktree.py`` to keep authored files under the 350-line
limit.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from yoke_core.domain import runtime_settings, worktree_deps
from yoke_core.domain.worktree import detect_deps


@pytest.fixture(autouse=True)
def _stub_which(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend every install tool is on PATH so detection tests exercise the
    detection branches independent of the host's installed tooling. The new
    `shutil.which` pre-check in `_detect_nested_deps` would otherwise drop
    nested specs on machines that lack npm/pip/etc.
    """
    monkeypatch.setattr(worktree_deps.shutil, "which", lambda _name: "/stub")


class TestDetectDeps:
    def test_package_lock(self, tmp_path):
        (tmp_path / "package-lock.json").write_text("{}")
        (tmp_path / "package.json").write_text('{"name":"t"}')
        specs = detect_deps(str(tmp_path))
        assert len(specs) == 1
        assert specs[0].tool == "npm"
        assert specs[0].command == ["npm", "ci"]

    def test_package_json_only(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name":"t"}')
        specs = detect_deps(str(tmp_path))
        assert len(specs) == 1
        assert specs[0].command == ["npm", "install"]

    def test_requirements_txt(self, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask==2.0\n")
        specs = detect_deps(str(tmp_path))
        assert len(specs) == 1
        assert specs[0].tool == "pip"

    def test_yarn_lock(self, tmp_path):
        (tmp_path / "yarn.lock").write_text("# yarn\n")
        specs = detect_deps(str(tmp_path))
        assert len(specs) == 1
        assert specs[0].tool == "yarn"

    def test_go_sum(self, tmp_path):
        (tmp_path / "go.sum").write_text("github.com/foo/bar v1.0.0\n")
        specs = detect_deps(str(tmp_path))
        assert len(specs) == 1
        assert specs[0].tool == "go"

    def test_multiple_ecosystems(self, tmp_path):
        """JS + Python both detected at root level."""
        (tmp_path / "package.json").write_text('{"name":"t"}')
        (tmp_path / "requirements.txt").write_text("flask\n")
        specs = detect_deps(str(tmp_path))
        assert len(specs) == 2
        tools = {s.tool for s in specs}
        assert "npm" in tools
        assert "pip" in tools

    def test_root_priority_over_nested(self, tmp_path):
        """Root-level deps suppress nested fallback."""
        (tmp_path / "package-lock.json").write_text("{}")
        (tmp_path / "package.json").write_text('{"name":"t"}')
        nested = tmp_path / "app" / "web"
        nested.mkdir(parents=True)
        (nested / "package-lock.json").write_text("{}")
        specs = detect_deps(str(tmp_path))
        assert len(specs) == 1
        assert specs[0].cwd == str(tmp_path)

    def test_nested_package_lock(self, tmp_path):
        """Nested fallback finds package-lock.json."""
        nested = tmp_path / "app" / "web"
        nested.mkdir(parents=True)
        (nested / "package-lock.json").write_text("{}")
        (nested / "package.json").write_text('{"name":"t"}')
        specs = detect_deps(str(tmp_path))
        assert len(specs) == 1
        assert specs[0].command == ["npm", "ci"]
        assert specs[0].cwd == str(nested)

    def test_nested_package_json_no_lock(self, tmp_path):
        """Nested fallback finds package.json without lockfile."""
        nested = tmp_path / "src" / "frontend"
        nested.mkdir(parents=True)
        (nested / "package.json").write_text('{"name":"t"}')
        specs = detect_deps(str(tmp_path))
        assert len(specs) == 1
        assert specs[0].command == ["npm", "install"]

    def test_no_deps(self, tmp_path):
        specs = detect_deps(str(tmp_path))
        assert specs == []

    def test_gemfile(self, tmp_path):
        (tmp_path / "Gemfile.lock").write_text("GEM\n")
        specs = detect_deps(str(tmp_path))
        assert len(specs) == 1
        assert specs[0].tool == "bundle"


class TestNestedDetectorRespectsPath:
    """Regression: a nested lockfile in the repo used to queue ``npm ci``
    on every worktree create. On hosts without npm, that yielded N
    signal-less ``Warning: dependency install failed`` lines (one per
    worktree). The detector now skips at detect-time when the install
    tool is not on PATH and emits a single diagnostic line.
    """

    def test_skip_when_npm_not_on_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ) -> None:
        monkeypatch.setattr(worktree_deps.shutil, "which", lambda _name: None)
        nested = tmp_path / "frontend"
        nested.mkdir()
        (nested / "package-lock.json").write_text("{}")
        specs = detect_deps(str(tmp_path))
        captured = capsys.readouterr()
        assert specs == []
        assert "npm not on PATH" in captured.err

    def test_packaged_browser_runtime_is_never_detected(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The packaged Browser QA sources (runtime/browser_runtime/) must
        never queue an npm install — that tree installs into the machine
        runtime dir, not into a checkout."""
        monkeypatch.setattr(
            worktree_deps.shutil, "which", lambda name: "/usr/bin/" + name
        )
        packaged = tmp_path / "runtime" / "browser_runtime"
        packaged.mkdir(parents=True)
        (packaged / "package-lock.json").write_text("{}")
        (packaged / "package.json").write_text("{}")
        specs = detect_deps(str(tmp_path))
        assert specs == []

    def test_skip_when_pip_not_on_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys,
    ) -> None:
        monkeypatch.setattr(worktree_deps.shutil, "which", lambda _name: None)
        nested = tmp_path / "py"
        nested.mkdir()
        (nested / "requirements.txt").write_text("flask\n")
        specs = detect_deps(str(tmp_path))
        captured = capsys.readouterr()
        assert specs == []
        assert "pip not on PATH" in captured.err


class TestRunSurfaces:
    """Regression: ``_run`` previously caught ``FileNotFoundError`` and
    returned an empty ``stderr``, so the install-deps caller printed a
    content-free "non-fatal" warning. The captured failure now lands in
    stderr so operators can tell "tool missing" from a real install bug.
    """

    def test_file_not_found_surfaces_in_stderr(self) -> None:
        proc = worktree_deps._run(["definitely_not_a_real_command_xyz"], timeout=5)
        assert proc.returncode == 1
        assert "FileNotFoundError" in proc.stderr
        assert "definitely_not_a_real_command_xyz" in proc.stderr


class TestInstallTimeoutFromConfig:
    """``install_worktree_deps`` reads its subprocess timeout from config.

    The previous hardcoded 300s ceiling fired as a fake-failure on slow
    bun/npm installs. The migration routes the timeout through
    ``runtime_settings.get_seconds(worktree_dep_install_timeout_seconds)``
    so operators can set it high enough for the real install duration.
    """

    def test_long_install_completes_when_timeout_high_enough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A 'long' install command completes when the configured timeout exceeds it."""
        # Trigger the convention-detection path with a single npm spec.
        (tmp_path / "package.json").write_text('{"name":"t"}')
        (tmp_path / "package-lock.json").write_text("{}")

        # Force the config-derived timeout to be 60s — comfortably above the
        # short sleep our stand-in install command performs.
        monkeypatch.setattr(
            runtime_settings,
            "get_seconds",
            lambda key, default, *, config_path=None: (
                60
                if key == worktree_deps.DEPS_INSTALL_TIMEOUT_CONFIG
                else default
            ),
        )

        # Capture the ``timeout=`` kwarg the call site forwards to ``_run``
        # and short-circuit the actual subprocess so the test never shells out.
        recorded: dict[str, object] = {}

        def _fake_run(cmd, cwd=None, timeout=30):
            import subprocess

            recorded["cmd"] = cmd
            recorded["timeout"] = timeout
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(worktree_deps, "_run", _fake_run)

        rc = worktree_deps.install_worktree_deps(str(tmp_path))

        assert rc == 0
        assert recorded["timeout"] == 60
        # Sanity check we exercised the convention-based install path.
        assert recorded["cmd"][:2] == ["npm", "ci"]

    def test_install_timeout_falls_back_to_default_when_unset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without an override, the call site uses the module default."""
        (tmp_path / "requirements.txt").write_text("flask\n")

        # Restore the real reader to validate fallback semantics from a
        # sandbox config file with no override key.
        empty_cfg = tmp_path / "data-config"
        empty_cfg.write_text("# no overrides here\n", encoding="utf-8")
        monkeypatch.setattr(
            runtime_settings,
            "_canonical_config_path",
            lambda: empty_cfg,
        )

        recorded: dict[str, object] = {}

        def _fake_run(cmd, cwd=None, timeout=30):
            import subprocess

            recorded["timeout"] = timeout
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        monkeypatch.setattr(worktree_deps, "_run", _fake_run)
        worktree_deps.install_worktree_deps(str(tmp_path))

        assert (
            recorded["timeout"]
            == worktree_deps.DEFAULT_DEPS_INSTALL_TIMEOUT_SECONDS
        )
