"""A test-machine reset never quits Tailscale, the tunnel its own SSH runs over."""

from __future__ import annotations

from runtime.api.domain.test_ssh_mac_terminal_restart import _SESSION, SessionHost
from yoke_harness.ssh_mac_gui_app_sweep import KEPT_BUNDLE_IDS, TRANSPORT_BUNDLE_IDS
from yoke_harness.ssh_mac_terminal_restart import quit_reset_apps

_TAILSCALE = [
    ("Tailscale", "io.tailscale.ipn.macsys", 8126, "Foreground"),
    ("Tailscale App Store", "io.tailscale.ipn.macos", 8127, "Foreground"),
]


def test_reset_keeps_tailscale_and_still_quits_every_other_leftover_app() -> None:
    host = SessionHost(apps=[*_SESSION, *_TAILSCALE])

    result = quit_reset_apps(host, "tester")

    assert result.ok, result.evidence
    quit = [entry["app"] for entry in result.evidence["gui_apps_quit"]]
    assert quit == ["Terminal", "Claude", "Cursor", "Codex"]
    kept = result.evidence["gui_apps_kept"]
    assert "Tailscale" in kept and "Tailscale App Store" in kept
    assert {8126, 8127} <= host.alive
    for bundle, pid in (("io.tailscale.ipn.macsys", 8126), ("io.tailscale.ipn.macos", 8127)):
        assert not any(bundle in c for c in host.commands)
        assert not any(f"grep -x {pid}" in c for c in host.commands)
    assert not any("Tailscale" in c for c in host.commands)


def test_the_transport_apps_stay_on_the_keep_list() -> None:
    assert TRANSPORT_BUNDLE_IDS
    assert TRANSPORT_BUNDLE_IDS <= KEPT_BUNDLE_IDS
