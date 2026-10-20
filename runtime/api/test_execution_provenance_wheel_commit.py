"""An installed wheel reports the commit its scm_version.json recorded."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts import install_binding
from yoke_contracts.execution_provenance import collect_execution_provenance
from yoke_contracts.runtime_identity import build_runtime_identity

COMMIT = "e2ec8be23286fbc918a6375dc2717c3d612dc87c"


class _Distribution:
    def __init__(self, root: Path, files: tuple[Path, ...], scm_version: str) -> None:
        self._root = root
        self.version = "7.8.9"
        self.files = files
        self._scm_version = scm_version

    def locate_file(self, path: str | Path) -> Path:
        return self._root / path

    def read_text(self, filename: str) -> str | None:
        if filename == install_binding.SCM_VERSION_FILENAME:
            return self._scm_version
        return None


@pytest.fixture
def wheel_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    site_packages = tmp_path / "venv" / "site-packages"
    relative = Path("yoke_contracts/execution_provenance.py")
    module_file = site_packages / relative
    module_file.parent.mkdir(parents=True)
    module_file.write_text("")
    monkeypatch.setattr(
        install_binding,
        "_distribution",
        lambda _name: _Distribution(
            site_packages, (relative,), f'{{"node": "g{COMMIT}"}}'
        ),
    )
    monkeypatch.delenv("YOKE_BUILD_SHA", raising=False)
    return module_file


def test_provenance_reads_the_wheel_commit(wheel_module: Path) -> None:
    probed = collect_execution_provenance(module_file=str(wheel_module), env={})

    assert probed["install_kind"] == "installed_wheel"
    assert probed["source_sha"] == COMMIT


def test_build_sha_still_wins_over_the_wheel_commit(wheel_module: Path) -> None:
    probed = collect_execution_provenance(
        module_file=str(wheel_module), env={"YOKE_BUILD_SHA": "c" * 40}
    )

    assert probed["source_sha"] == "c" * 40


def test_runtime_identity_build_falls_back_to_the_wheel_commit(
    wheel_module: Path,
) -> None:
    packet = build_runtime_identity(module_file=wheel_module)

    assert packet["build"] == COMMIT
