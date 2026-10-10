"""Named browser identities: separate profiles, the live store, and the human gate."""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from runtime.api.cli.browser_toolchain_test_support import install_fake_toolchain
from yoke_contracts.browser_identity import (
    BrowserIdentityError,
    LIVE_IDENTITY_STORE_HOME_ENTRY,
    parse_identity_declarations,
)
from yoke_cli.commands import browser_authorize, browser_verify
from yoke_cli.config import browser_identities, browser_profile
from yoke_harness import browser_client, browser_human_gate, browser_identity_check

SITES = {
    site: {
        "site": site,
        "origin": f"https://{site}.example.com",
        "account": f"buyer@{site}.example.com",
        "probe": {"url": f"https://{site}.example.com/me", "signed_in_status": 200},
    }
    for site in ("google", "yoke", "paypal")
}


@pytest.fixture()
def machine_home(tmp_path, monkeypatch):
    home = tmp_path / "machine-home"
    home.mkdir()
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))
    return home


def test_two_identities_persist_side_by_side(machine_home) -> None:
    member = browser_profile.ensure_profile_dir("acme", identity="member")
    admin = browser_profile.ensure_profile_dir("acme", identity="admin")
    (member / "Cookies").write_text("member session")
    (admin / "Cookies").write_text("admin session")
    assert member != admin
    assert browser_profile.authorized_profile_dir("acme", identity="member") == member
    assert browser_profile.remove_profile_dir("acme", identity="admin") == admin
    assert (member / "Cookies").read_text() == "member session"
    assert browser_profile.authorized_profile_dir("acme", identity="admin") is None


def test_a_machine_with_a_live_store_links_each_identity_into_it(machine_home) -> None:
    store = machine_home.parent / LIVE_IDENTITY_STORE_HOME_ENTRY
    store.mkdir(mode=0o700)
    assert browser_profile.authorized_profile_dir("acme", identity="admin") is None
    profile = browser_profile.ensure_profile_dir("acme", identity="admin")
    assert profile.is_symlink()
    assert profile.resolve() == (store / "acme" / "admin").resolve()
    (profile / "Cookies").write_text("refreshed by the site")
    # A fresh ~/.yoke after a reset links straight back to the kept sign-in.
    profile.unlink()
    again = browser_profile.authorized_profile_dir("acme", identity="admin")
    assert (again / "Cookies").read_text() == "refreshed by the site"


def test_a_profile_signed_in_before_the_store_existed_is_adopted(machine_home) -> None:
    legacy = browser_profile.ensure_profile_dir("acme")
    (legacy / "Cookies").write_text("default sign-in")
    store = machine_home.parent / LIVE_IDENTITY_STORE_HOME_ENTRY
    store.mkdir(mode=0o700)
    adopted = browser_profile.authorized_profile_dir("acme")
    assert adopted == legacy and adopted.is_symlink()
    assert (store / "acme" / "default" / "Cookies").read_text() == "default sign-in"


def test_a_profile_in_both_places_refuses_by_name(machine_home) -> None:
    browser_profile.ensure_profile_dir("acme", identity="admin")
    store = machine_home.parent / LIVE_IDENTITY_STORE_HOME_ENTRY
    (store / "acme" / "admin").mkdir(parents=True)
    with pytest.raises(BrowserIdentityError, match="browser_identity_store_conflict"):
        browser_profile.authorized_profile_dir("acme", identity="admin")


@pytest.mark.parametrize(
    "clock", ["1970-01-01T00:00:00Z", "1970-01-01T05:29:59.123456+05:30"]
)
def test_the_human_gate_stops_every_daemon_and_refuses_new_ones(
    tmp_path, monkeypatch, clock
):
    from yoke_contracts.timestamps import format_instant, parse_instant

    native = parse_instant(clock)
    monkeypatch.setattr(browser_human_gate, "utc_now", lambda: native)
    for key, profile in (("a", "/p/acme/admin"), ("b", "")):
        state = tmp_path / "daemons" / key / ".daemon-state.json"
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({"pid": os.getpid(), "profileDir": profile}))
    stopped: list = []
    monkeypatch.setattr(browser_client, "daemon_running", lambda state=None: True)
    monkeypatch.setattr(
        browser_client,
        "daemon_stop",
        lambda profile_dir=None: stopped.append(profile_dir),
    )
    with browser_human_gate.human_gate(
        browser_client, tmp_path, project="acme", identity="admin"
    ) as names:
        marker = json.loads(
            (tmp_path / browser_human_gate.HUMAN_GATE_FILE_NAME).read_text()
        )
        assert marker["started_at"] == format_instant(native)
        assert parse_instant(marker["started_at"]) == native
        assert marker["identity"] == "admin"
        assert sorted(names) == ["", "/p/acme/admin"]
        assert stopped == ["/p/acme/admin", None]
        with pytest.raises(browser_human_gate.HumanGateActiveError, match="'admin'"):
            browser_human_gate.refuse_during_human_gate(tmp_path)
    browser_human_gate.refuse_during_human_gate(tmp_path)


def test_a_crashed_sign_in_leaves_no_gate(tmp_path) -> None:
    marker = tmp_path / browser_human_gate.HUMAN_GATE_FILE_NAME
    marker.write_text(json.dumps({"pid": 2**22 + 12345, "identity": "admin"}))
    assert browser_human_gate.active_human_gate(tmp_path) is None
    assert not marker.exists()


@pytest.fixture()
def buyer(machine_home, tmp_path, monkeypatch):
    """Identity `buyer` on three sites; the fake browser serves their states."""
    runtime = tmp_path / "browser-runtime"
    (runtime / "src").mkdir(parents=True)
    for script in ("authorize.js", "verify-sign-in.js"):
        (runtime / "src" / script).write_text("")
    monkeypatch.setattr(
        "yoke_harness.browser_runtime_home.ensure_materialized", lambda: runtime
    )
    monkeypatch.setattr(
        "yoke_harness.browser_setup.ensure_browser_runtime", lambda *a, **k: {}
    )
    install_fake_toolchain(monkeypatch, tmp_path / "node-bin")
    monkeypatch.setattr(
        browser_identities,
        "declared_identities",
        lambda key, **kw: parse_identity_declarations(
            {"identities": {"buyer": {"sites": list(SITES.values())}}}
        ),
    )
    monkeypatch.setattr(
        browser_client.DaemonState, "load", staticmethod(lambda path=None: None)
    )
    for module in (browser_authorize, browser_identity_check):
        monkeypatch.setattr(module, "keep_sign_in_cookies", lambda profile: 0)
    world = {"states": {}, "after_window": {}, "windows": [], "gate": []}

    def fake_run(command, **kwargs):
        if command[1].endswith("verify-sign-in.js"):
            checks = json.loads(command[command.index("--checks") + 1])
            sites = [
                {"site": c["site"], "state": world["states"][c["site"]], "detail": "-"}
                for c in checks
            ]
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"sites": sites}), ""
            )
        world["windows"].append(
            [command[i + 1] for i, a in enumerate(command) if a == "--url"]
        )
        world["gate"].append(browser_human_gate.active_human_gate(runtime))
        world["states"].update(world["after_window"])
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    browser_profile.ensure_profile_dir("acme", identity="buyer")
    return world


def _authorize(*extra):
    return browser_authorize.browser_authorize(
        ["--project", "acme", "--identity", "buyer", *extra]
    )


def test_authorize_skips_the_window_when_every_site_is_signed_in(buyer, capsys):
    buyer["states"] = dict.fromkeys(SITES, "signed_in")
    assert _authorize("--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["window_opened"] is False and buyer["windows"] == []
    assert [site["state"] for site in payload["sites"]] == ["signed_in"] * 3


def test_authorize_asks_only_for_the_expired_site(buyer, capsys):
    buyer["states"] = {"google": "signed_in", "yoke": "signed_in", "paypal": "expired"}
    buyer["after_window"] = {"paypal": "signed_in"}
    assert _authorize() == 0
    out = capsys.readouterr().out
    assert "buyer: google ok, yoke ok, paypal expired" in out
    assert (
        "Sign in to paypal (https://paypal.example.com) for identity buyer as "
        "buyer@paypal.example.com." in out
    )
    assert buyer["windows"] == [["https://paypal.example.com"]]
    # No automated browser may start while the window is open.
    assert buyer["gate"][0]["identity"] == "buyer"
    assert "buyer: google ok, yoke ok, paypal ok" in out


def test_authorize_fails_naming_a_site_still_signed_out(buyer, capsys):
    buyer["states"] = {"google": "signed_in", "yoke": "expired", "paypal": "signed_in"}
    assert _authorize() == 1
    assert "browser_sign_in_incomplete" in capsys.readouterr().err
    assert buyer["windows"] == [["https://yoke.example.com"]]


def test_authorize_never_asks_a_human_to_fix_an_unreachable_site(buyer, capsys):
    buyer["states"] = {
        "google": "unreachable",
        "yoke": "expired",
        "paypal": "signed_in",
    }
    assert _authorize() == 1
    assert "browser_sign_in_site_unreachable" in capsys.readouterr().err
    assert buyer["windows"] == []


def test_verify_reports_each_site_without_a_window(buyer, capsys):
    buyer["states"] = {"google": "signed_in", "yoke": "signed_in", "paypal": "expired"}
    code = browser_verify.browser_verify(
        ["--project", "acme", "--identity", "buyer", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)
    assert code == 1 and buyer["windows"] == []
    assert payload["summary"] == "buyer: google ok, yoke ok, paypal expired"
    assert payload["sites"][2]["account"] == "buyer@paypal.example.com"


def test_an_undeclared_identity_refuses_before_any_browser(buyer, capsys):
    code = browser_verify.browser_verify(["--project", "acme", "--identity", "admin"])
    assert code == 2
    assert "browser_identity_undeclared" in capsys.readouterr().err


def test_a_host_without_the_control_plane_verifies_from_supplied_declarations(
    buyer, monkeypatch, capsys
):
    def unreachable(key, **kwargs):
        raise BrowserIdentityError("browser_identity_declarations_unreadable: offline")

    monkeypatch.setattr(browser_identities, "declared_identities", unreachable)
    buyer["states"] = dict.fromkeys(SITES, "signed_in")
    document = json.dumps({"identities": {"buyer": {"sites": list(SITES.values())}}})
    code = browser_verify.browser_verify(
        ["--project", "acme", "--identity", "buyer", "--declarations-json", document]
    )
    assert code == 0
    assert "buyer: google ok, yoke ok, paypal ok" in capsys.readouterr().out
    assert (
        browser_verify.browser_verify(["--project", "acme", "--identity", "buyer"]) == 2
    )
