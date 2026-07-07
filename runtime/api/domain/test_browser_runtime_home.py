"""Tests for :mod:`yoke_core.domain.browser_runtime_home`.

Fully hermetic: the packaged source root and the machine home are both
redirected into ``tmp_path`` so no test touches the real
``~/.yoke/browser-runtime`` or the real packaged sources.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import browser_runtime_home


@pytest.fixture()
def fake_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a fake packaged-source tree and point the module at it."""

    source = tmp_path / "pkg-source"
    (source / "src" / "routes").mkdir(parents=True)
    (source / "tests").mkdir()
    (source / "src" / "daemon.js").write_text("console.log('daemon');\n")
    (source / "src" / "routes" / "exec-routes.js").write_text("// routes\n")
    (source / "tests" / "daemon.test.js").write_text("// test\n")
    (source / "package.json").write_text('{"name": "yoke-browser"}\n')
    (source / "package-lock.json").write_text('{"lockfileVersion": 3}\n')
    monkeypatch.setattr(
        browser_runtime_home, "package_source_dir", lambda: source
    )
    return source


@pytest.fixture()
def machine_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "machine-home"
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


class TestRuntimeDir:
    def test_honors_machine_home_env(self, machine_home: Path) -> None:
        assert browser_runtime_home.runtime_dir() == (
            machine_home / "browser-runtime"
        )


class TestEnsureMaterialized:
    def test_first_call_copies_sources_and_writes_hash(
        self, fake_source: Path, machine_home: Path
    ) -> None:
        dest = browser_runtime_home.ensure_materialized()

        assert dest == machine_home / "browser-runtime"
        assert (dest / "src" / "daemon.js").read_text() == (
            "console.log('daemon');\n"
        )
        assert (dest / "src" / "routes" / "exec-routes.js").is_file()
        assert (dest / "tests" / "daemon.test.js").is_file()
        assert (dest / "package.json").is_file()
        assert (dest / "package-lock.json").is_file()
        marker = dest / browser_runtime_home.HASH_MARKER_NAME
        assert marker.read_text().strip() == (
            browser_runtime_home.source_hash(fake_source)
        )

    def test_second_call_with_same_hash_skips_copy(
        self,
        fake_source: Path,
        machine_home: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        browser_runtime_home.ensure_materialized()

        calls: list[tuple[Path, Path]] = []
        monkeypatch.setattr(
            browser_runtime_home,
            "_copy_sources",
            lambda src, dst: calls.append((src, dst)),
        )
        dest = browser_runtime_home.ensure_materialized()

        assert calls == []
        assert (dest / "src" / "daemon.js").is_file()

    def test_changed_source_rematerializes_preserving_runtime_state(
        self, fake_source: Path, machine_home: Path
    ) -> None:
        dest = browser_runtime_home.ensure_materialized()

        # Runtime state at the top level of the runtime dir.
        keep = dest / "node_modules" / "keep.txt"
        keep.parent.mkdir()
        keep.write_text("installed\n")
        state = dest / ".daemon-state.json"
        state.write_text('{"pid": 1}\n')
        # A file the old source tree had but the new one will not.
        stale = dest / "src" / "routes" / "exec-routes.js"
        assert stale.is_file()

        (fake_source / "src" / "daemon.js").write_text("// v2\n")
        (fake_source / "src" / "routes" / "exec-routes.js").unlink()
        dest2 = browser_runtime_home.ensure_materialized()

        assert dest2 == dest
        assert (dest / "src" / "daemon.js").read_text() == "// v2\n"
        assert not stale.exists()  # subtree replaced wholesale
        assert keep.read_text() == "installed\n"
        assert state.read_text() == '{"pid": 1}\n'
        marker = dest / browser_runtime_home.HASH_MARKER_NAME
        assert marker.read_text().strip() == (
            browser_runtime_home.source_hash(fake_source)
        )

    def test_hash_changes_with_content_and_relpath(
        self, fake_source: Path
    ) -> None:
        before = browser_runtime_home.source_hash(fake_source)
        (fake_source / "src" / "daemon.js").write_text("// changed\n")
        after = browser_runtime_home.source_hash(fake_source)
        assert before != after

        renamed = fake_source / "src" / "daemon2.js"
        (fake_source / "src" / "daemon.js").rename(renamed)
        assert browser_runtime_home.source_hash(fake_source) != after


class TestPackageSourceDir:
    def test_resolves_to_packaged_sources(self) -> None:
        source = browser_runtime_home.package_source_dir()
        assert source.name == "browser_runtime"
        assert (source / "src" / "daemon.js").is_file()
        assert (source / "package.json").is_file()
