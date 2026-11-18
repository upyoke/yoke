"""Every identity profile lives in the reset-preserved live store, created on demand."""

from __future__ import annotations

import os
import shutil

import pytest

from yoke_contracts.browser_identity import (
    BrowserIdentityError,
    LIVE_IDENTITY_STORE_HOME_ENTRY,
)
from yoke_cli.config import browser_profile


@pytest.fixture()
def machine_home(tmp_path, monkeypatch):
    home = tmp_path / "machine-home"
    home.mkdir()
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


def _legacy_profile(machine_home, identity="default"):
    from yoke_contracts.machine_config.capability_secrets import (
        browser_profile_relative_path,
    )

    path = machine_home / "secrets" / browser_profile_relative_path("acme", identity)
    path.mkdir(parents=True)
    return path


def test_an_absent_store_is_created_before_the_profile(machine_home) -> None:
    store = machine_home.parent / LIVE_IDENTITY_STORE_HOME_ENTRY
    assert not store.exists()
    assert browser_profile.authorized_profile_dir("acme", identity="admin") is None
    assert not store.exists()
    profile = browser_profile.ensure_profile_dir("acme", identity="admin")
    assert profile == store / "acme" / "admin"
    assert profile.is_dir() and not profile.is_symlink()
    if os.name != "nt":
        assert store.stat().st_mode & 0o777 == 0o700
    assert not (machine_home / "secrets").exists()
    (profile / "Cookies").write_text("refreshed by the site")
    # A reset deletes the machine home; the kept store still answers.
    shutil.rmtree(machine_home)
    machine_home.mkdir()
    again = browser_profile.authorized_profile_dir("acme", identity="admin")
    assert (again / "Cookies").read_text() == "refreshed by the site"


def test_a_profile_signed_in_under_the_machine_home_is_adopted(machine_home) -> None:
    legacy = _legacy_profile(machine_home)
    (legacy / "Cookies").write_text("default sign-in")
    adopted = browser_profile.authorized_profile_dir("acme")
    store = machine_home.parent / LIVE_IDENTITY_STORE_HOME_ENTRY
    assert adopted == store / "acme" / "default"
    assert (adopted / "Cookies").read_text() == "default sign-in"
    assert not legacy.exists()


def test_an_old_link_into_the_store_is_dropped(machine_home) -> None:
    profile = browser_profile.ensure_profile_dir("acme", identity="admin")
    (profile / "Cookies").write_text("kept")
    link = _legacy_profile(machine_home, "admin")
    link.rmdir()
    try:
        link.symlink_to(profile, target_is_directory=True)
    except OSError:
        pytest.skip("this host cannot create directory links")
    assert browser_profile.authorized_profile_dir("acme", identity="admin") == profile
    assert not link.is_symlink() and not link.exists()
    assert (profile / "Cookies").read_text() == "kept"


def test_a_profile_in_both_places_refuses_by_name(machine_home) -> None:
    browser_profile.ensure_profile_dir("acme", identity="admin")
    _legacy_profile(machine_home, "admin")
    with pytest.raises(BrowserIdentityError, match="browser_identity_store_conflict"):
        browser_profile.authorized_profile_dir("acme", identity="admin")


@pytest.mark.parametrize("shape", ["file", "link"])
def test_an_unusable_store_refuses_by_name(machine_home, tmp_path, shape) -> None:
    store = machine_home.parent / LIVE_IDENTITY_STORE_HOME_ENTRY
    if shape == "file":
        store.write_text("not a directory")
    else:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        try:
            store.symlink_to(elsewhere, target_is_directory=True)
        except OSError:
            pytest.skip("this host cannot create directory links")
    with pytest.raises(BrowserIdentityError, match="browser_identity_store_unavailable"):
        browser_profile.ensure_profile_dir("acme", identity="admin")
    assert not (machine_home / "secrets").exists()


def test_a_store_that_cannot_be_created_refuses_by_name(machine_home, monkeypatch) -> None:
    def denied(path):
        raise PermissionError(13, "Permission denied", str(path))

    monkeypatch.setattr(browser_profile, "create_private_directory", denied)
    with pytest.raises(BrowserIdentityError, match="browser_identity_store_unavailable"):
        browser_profile.ensure_profile_dir("acme")
    assert not (machine_home / "secrets").exists()
