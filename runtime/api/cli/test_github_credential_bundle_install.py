"""Atomic publication coverage for the installed Git credential bundle."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from yoke_cli.config import github_git_credential_bundle
from yoke_cli.config import github_git_credential_file
from yoke_cli.config import github_git_credential_helper
from yoke_cli.config import github_git_credential_launcher
from yoke_cli.config import github_git_credential_store
from yoke_cli.config import github_git_credentials, github_response_safety
from yoke_contracts import github_app_tokens, github_origin


def _next_sources(tmp_path: Path) -> list[tuple[Path, str]]:
    sources = []
    for source, target_name in github_git_credential_bundle._bundle_sources():
        copied = tmp_path / "next" / target_name
        copied.parent.mkdir(exist_ok=True)
        copied.write_bytes(source.read_bytes() + b"\n# next bundle\n")
        sources.append((copied, target_name))
    return sources


def test_helper_bundle_failure_keeps_old_entrypoint_and_pointer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = tmp_path / "site"
    helper = github_git_credentials.install_stable_helper(site)
    old_entrypoint = helper.read_bytes()
    pointer = site / github_git_credential_launcher.BUNDLE_POINTER_NAME
    old_pointer = pointer.read_bytes()
    real_write = github_git_credential_bundle._write_unpublished_source
    sources = _next_sources(tmp_path)
    monkeypatch.setattr(
        github_git_credential_bundle, "_bundle_sources", lambda: tuple(sources),
    )

    def fail_before_store(source: Path, target: Path) -> None:
        if target.name == github_git_credentials.STABLE_STORE_FILE_NAME:
            raise OSError("simulated publish failure")
        real_write(source, target)

    monkeypatch.setattr(
        github_git_credential_bundle,
        "_write_unpublished_source",
        fail_before_store,
    )
    with pytest.raises(OSError, match="simulated publish failure"):
        github_git_credentials.install_stable_helper(site)
    assert helper.read_bytes() == old_entrypoint
    assert pointer.read_bytes() == old_pointer
    assert not list((site / github_git_credential_launcher.BUNDLE_ROOT_NAME).glob(
        ".bundle-*"
    ))


def test_pointer_switch_before_launcher_failure_selects_complete_new_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = tmp_path / "site"
    github_git_credentials.install_stable_helper(site)
    old_bundle = github_git_credential_launcher.selected_bundle(site)
    sources = _next_sources(tmp_path)
    monkeypatch.setattr(
        github_git_credential_bundle, "_bundle_sources", lambda: tuple(sources),
    )
    monkeypatch.setattr(
        github_git_credential_bundle,
        "_publish_launcher",
        lambda *args: (_ for _ in ()).throw(OSError("launcher cut")),
    )
    with pytest.raises(OSError, match="launcher cut"):
        github_git_credentials.install_stable_helper(site)
    selected = github_git_credential_launcher.selected_bundle(site)
    assert selected != old_bundle
    assert {path.name for path in selected.iterdir()} == {
        target_name for _source, target_name in sources
    }
    for source, target_name in sources:
        assert (selected / target_name).read_bytes() == source.read_bytes()


def test_concurrent_helper_bundle_installs_publish_complete_sources(
    tmp_path: Path,
) -> None:
    site = tmp_path / "site"
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(
            lambda _index: github_git_credentials.install_stable_helper(site),
            range(8),
        ))
    assert len(set(paths)) == 1
    expected = {
        github_git_credentials.STABLE_ORIGIN_FILE_NAME: Path(github_origin.__file__),
        github_git_credentials.STABLE_TOKEN_CONTRACT_NAME: Path(
            github_app_tokens.__file__
        ),
        github_git_credentials.STABLE_RESPONSE_SAFETY_NAME: Path(
            github_response_safety.__file__
        ),
        github_git_credentials.STABLE_FILE_IO_NAME: Path(
            github_git_credential_file.__file__
        ),
        github_git_credentials.STABLE_STORE_FILE_NAME: Path(
            github_git_credential_store.__file__
        ),
        github_git_credentials.STABLE_HELPER_FILE_NAME: Path(
            github_git_credential_helper.__file__
        ),
    }
    bundle = github_git_credential_launcher.selected_bundle(site)
    for name, source in expected.items():
        assert (bundle / name).read_bytes() == source.read_bytes()
    assert paths[0].read_bytes() == Path(
        github_git_credential_launcher.__file__
    ).read_bytes()


def test_refresh_installed_helper_upgrades_legacy_store_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    site = tmp_path / "site"
    site.mkdir()
    (site / github_git_credentials.STABLE_HELPER_FILE_NAME).write_text(
        "legacy helper\n", encoding="utf-8"
    )
    monkeypatch.setattr(github_git_credentials, "_helper_site_dir", lambda: site)
    assert github_git_credentials.refresh_installed_helper() is True
    bundle = github_git_credential_launcher.selected_bundle(site)
    store = (bundle / github_git_credentials.STABLE_STORE_FILE_NAME).read_text(
        encoding="utf-8"
    )
    assert "CREDENTIAL_SCHEMA_VERSION = 2" in store
    assert (bundle / github_git_credentials.STABLE_RESPONSE_SAFETY_NAME).is_file()
