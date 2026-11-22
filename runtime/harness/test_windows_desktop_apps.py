"""Native Windows desktop probes read installed registry metadata only."""

from __future__ import annotations

import subprocess

import pytest

from yoke_harness import session_relay_surface_probes as probes
from yoke_harness import windows_desktop_apps as windows
from yoke_harness.windows_desktop_apps import MSIX_REPOSITORY_KEY, UNINSTALL_KEY

_CURSOR_KEY = "{DADADADA-ADAD-ADAD-ADAD-ADADADADADAD}}_is1"


class FakeRegistry:
    def __init__(self, keys: dict[tuple[str, str], dict[str, object]] | None = None):
        self.keys = keys or {}

    def subkeys(self, hive: str, path: str) -> tuple[str, ...]:
        prefix = f"{path}\\"
        return tuple(
            key_path[len(prefix):]
            for key_hive, key_path in self.keys
            if key_hive == hive and key_path.startswith(prefix)
        )

    def value(self, hive: str, path: str, name: str) -> object | None:
        return self.keys.get((hive, path), {}).get(name)


def _lab_registry() -> FakeRegistry:
    """The registry shape recorded on windows-native-lab-2."""
    return FakeRegistry(
        {
            ("HKCU", f"{MSIX_REPOSITORY_KEY}\\Claude_6.28899.2.0_x64__pzs8sxrjxfjjc"): {},
            (
                "HKCU",
                f"{MSIX_REPOSITORY_KEY}\\OpenAI.CodexPrimaryRuntime.v26-1119-907-0"
                "_26.1119.907.0_x64__3k8sg7r9htsxt",
            ): {},
            (
                "HKCU",
                f"{MSIX_REPOSITORY_KEY}\\OpenAI.Codex_26.1117.4957.0_x64__2p2nqsd0c76g0",
            ): {},
            ("HKCU", f"{UNINSTALL_KEY}\\{_CURSOR_KEY}"): {
                "DisplayName": "Cursor (User)",
                "DisplayVersion": "3.30.14",
            },
        }
    )


@pytest.fixture
def on_windows(monkeypatch):
    monkeypatch.setattr(probes.sys, "platform", "win32")

    def use(registry: FakeRegistry) -> None:
        monkeypatch.setattr(
            probes,
            "read_windows_desktop_version",
            lambda surface: windows.read_windows_desktop_version(
                surface, reader=registry
            ),
        )

    def no_process(*_args, **_kwargs):
        raise AssertionError("a Windows desktop probe must start no process")

    monkeypatch.setattr(subprocess, "run", no_process)
    monkeypatch.setattr(subprocess, "Popen", no_process)
    return use


def test_msix_and_win32_installs_report_recorded_versions(on_windows) -> None:
    on_windows(_lab_registry())
    results = {surface: probes.probe_surface(surface) for surface in probes.APP_SURFACES}
    assert {s: (r.verdict, r.source, r.version) for s, r in results.items()} == {
        "claude-desktop": ("ok", "msix", "6.28899.2.0"),
        "codex-desktop": ("ok", "msix", "26.1117.4957.0"),
        "cursor-desktop": ("ok", "registry", "3.30.14"),
    }
    assert all(result.error is None for result in results.values())


def test_newest_msix_version_wins_and_machine_cursor_install_counts(on_windows) -> None:
    on_windows(
        FakeRegistry(
            {
                ("HKCU", f"{MSIX_REPOSITORY_KEY}\\Claude_1.9.0.0_x64__pzs8sxrjxfjjc"): {},
                ("HKCU", f"{MSIX_REPOSITORY_KEY}\\Claude_1.10.0.0_x64__pzs8sxrjxfjjc"): {},
                ("HKCU", f"{MSIX_REPOSITORY_KEY}\\Claude_9.0.0.0_x64__otherpublisher"): {},
                ("HKLM", f"{UNINSTALL_KEY}\\{_CURSOR_KEY}"): {
                    "DisplayName": "Cursor",
                    "DisplayVersion": "3.31.0",
                },
            }
        )
    )
    assert probes.probe_surface("claude-desktop").version == "1.10.0.0"
    cursor = probes.probe_surface("cursor-desktop")
    assert (cursor.verdict, cursor.version) == ("ok", "3.31.0")


def test_absent_apps_read_missing_with_windows_message(on_windows) -> None:
    on_windows(FakeRegistry())
    for surface in probes.APP_SURFACES:
        result = probes.probe_surface(surface)
        assert result.verdict == "missing"
        assert result.error.startswith("desktop_app_missing: no ")
        assert "Info.plist" not in result.error
        assert "\\Applications\\" not in result.error
        assert "/Applications/" not in result.error
    assert "OpenAI.Codex_2p2nqsd0c76g0" in probes.probe_surface("codex-desktop").error
    assert "'Cursor (User)'" in probes.probe_surface("cursor-desktop").error


def test_codex_runtime_package_alone_is_not_the_desktop_app(on_windows) -> None:
    registry = _lab_registry()
    del registry.keys[
        ("HKCU", f"{MSIX_REPOSITORY_KEY}\\OpenAI.Codex_26.1117.4957.0_x64__2p2nqsd0c76g0")
    ]
    on_windows(registry)
    assert probes.probe_surface("codex-desktop").verdict == "missing"
    assert probes.probe_surface("claude-desktop").verdict == "ok"


def test_unreadable_display_version_is_an_error(on_windows) -> None:
    registry = _lab_registry()
    registry.keys[("HKCU", f"{UNINSTALL_KEY}\\{_CURSOR_KEY}")]["DisplayVersion"] = 7
    on_windows(registry)
    result = probes.probe_surface("cursor-desktop")
    assert result.verdict == "error"
    assert result.error.startswith("desktop_metadata_unreadable: ")
    assert "DisplayVersion" in result.error


def test_registry_access_denied_is_an_error(on_windows) -> None:
    class Denied(FakeRegistry):
        def subkeys(self, hive, path):
            raise PermissionError(5, "Access is denied")

    on_windows(Denied())
    result = probes.probe_surface("claude-desktop")
    assert result.verdict == "error"
    assert "Access is denied" in result.error
    assert "Info.plist" not in result.error


def test_real_reader_refuses_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(windows.sys, "platform", "darwin")
    with pytest.raises(RuntimeError, match="only readable on Windows"):
        windows.read_windows_desktop_version("claude-desktop")
