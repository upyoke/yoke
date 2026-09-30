"""Both real entry points -- the public installer's own completion, and
`yoke update` running that same installer -- repair a wiped git
credential-helper bundle through the real repair function, never a mocked
outcome, and a real repair failure fails both entry points too. Success is
proven with an ordinary `git credential fill` against fixture credentials.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from runtime.api.cli.credential_helper_installer_test_support import (
    INSTALLER_PATH,
    _assert_git_helper_works,
    _fixture,
    _run_real_installer,
)
from yoke_cli.config import github_git_credentials, self_update
from yoke_cli.self_host import release_target
from yoke_contracts.api_urls import DISTRIBUTION_PROD_URL
from yoke_contracts.server_image import pinned_server_image


def test_public_installer_completion_repairs_bundle_and_git_works(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "installer-repair-secret"
    repo, config, site, yoke_bin = _fixture(tmp_path, monkeypatch, token=token)

    completed = _run_real_installer(
        config=config,
        yoke_bin=yoke_bin,
        name="yoke_installer_repair_entry_point",
    )

    assert completed.returncode == 0
    assert (site / github_git_credentials.STABLE_HELPER_FILE_NAME).is_file()
    assert "Rebuilt the git credential helper bundle" in completed.stdout
    _assert_git_helper_works(repo, tmp_path, token)


def test_public_installer_completion_fails_when_repair_genuinely_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real repair failure (the bundle write itself fails) must fail the
    installer -- readiness requires the repair to have completed, not
    merely been attempted."""
    token = "installer-failure-secret"
    _repo, config, _site, yoke_bin = _fixture(tmp_path, monkeypatch, token=token)
    monkeypatch.setattr(
        github_git_credentials,
        "install_stable_helper",
        lambda *_a, **_k: (_ for _ in ()).throw(
            github_git_credentials.GitHubCredentialBundleError("disk full")
        ),
    )

    completed = _run_real_installer(
        config=config,
        yoke_bin=yoke_bin,
        name="yoke_installer_repair_failure",
    )

    assert completed.returncode != 0
    assert "credential helper repair failed" in completed.stderr
    assert "disk full" in completed.stderr
    # The friendly stdout screen never reaches the "ready" completion state
    # a caller could mistake for success.
    assert "Rebuilt the git credential helper bundle" not in completed.stdout


def _stub_update_through_real_installer(
    *,
    monkeypatch: pytest.MonkeyPatch,
    config: Path,
    yoke_bin: str,
    installer_module_name: str,
) -> None:
    monkeypatch.setattr(
        self_update.install_binding,
        "detect",
        lambda: {
            "kind": "packaged_wheel",
            "checkout_root": None,
            "module_origin": "/wherever/yoke_cli/__init__.py",
            "version": "0.1.1+launch.433",
        },
    )
    monkeypatch.setattr(self_update.shutil, "which", lambda _name: yoke_bin)
    source_commit = "4" * 40
    target = release_target.ReleaseTarget(
        version="2.0.0",
        source_commit=source_commit,
        image=pinned_server_image(source_commit),
        base_url=DISTRIBUTION_PROD_URL,
        channel="stable",
        installer_url=f"{DISTRIBUTION_PROD_URL}/dist/install.py",
    )
    monkeypatch.setattr(
        self_update.release_target,
        "channel_release_target",
        lambda **_k: target,
    )
    monkeypatch.setattr(
        self_update.release_target,
        "fetch_installer",
        lambda _target: INSTALLER_PATH.read_bytes(),
    )
    monkeypatch.setattr(
        self_update.release_target,
        "run_installer",
        lambda _target, installer_bytes, **_k: _run_real_installer(
            config=config,
            yoke_bin=yoke_bin,
            name=installer_module_name,
            source_bytes=installer_bytes,
        ),
    )
    monkeypatch.setattr(
        self_update,
        "_RUN",
        lambda command, **_k: subprocess.CompletedProcess(command, 0, "2.0.0\n", ""),
    )


def test_yoke_update_runs_the_real_installer_and_git_works(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "update-repair-secret"
    repo, config, site, yoke_bin = _fixture(tmp_path, monkeypatch, token=token)
    _stub_update_through_real_installer(
        monkeypatch=monkeypatch,
        config=config,
        yoke_bin=yoke_bin,
        installer_module_name="yoke_installer_repair_via_update",
    )

    result = self_update.run_update()

    # A successful reinstall carries no independent repair signal: the
    # installer performed and enforced the repair itself.
    assert result["credential_helper_configured"] is None
    assert result["credential_helper_repaired"] is None
    assert result["credential_helper_error"] is None
    assert (site / github_git_credentials.STABLE_HELPER_FILE_NAME).is_file()
    _assert_git_helper_works(repo, tmp_path, token)


def test_yoke_update_surfaces_a_real_installer_repair_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same real repair failure the installer entry point fails on must
    also reach `yoke update` as a real failure, not silent success."""
    token = "update-failure-secret"
    _repo, config, _site, yoke_bin = _fixture(tmp_path, monkeypatch, token=token)
    monkeypatch.setattr(
        github_git_credentials,
        "install_stable_helper",
        lambda *_a, **_k: (_ for _ in ()).throw(
            github_git_credentials.GitHubCredentialBundleError("disk full")
        ),
    )
    _stub_update_through_real_installer(
        monkeypatch=monkeypatch,
        config=config,
        yoke_bin=yoke_bin,
        installer_module_name="yoke_installer_repair_failure_via_update",
    )

    with pytest.raises(self_update.SelfUpdateError) as raised:
        self_update.run_update()

    assert "credential helper repair failed" in str(raised.value)
    assert "disk full" in str(raised.value)
