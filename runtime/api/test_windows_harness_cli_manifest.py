"""Native harness lookup and recovery work without Unix install commands."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from yoke_cli.config.path_harness_clis import resolve_harness_clis
from yoke_contracts import harness_cli_manifest as registry
from yoke_contracts.harness_cli_manifest import HARNESS_CLI_MANIFESTS


def test_windows_manifests_name_native_install_and_bundle_routes():
    for manifest in HARNESS_CLI_MANIFESTS:
        assert manifest.install_for_platform(windows=True)
        candidates, patterns = manifest.bundles_for_platform(windows=True)
        assert candidates or patterns
        assert all("/Applications/" not in path for path in (*candidates, *patterns))
        assert "bash" not in manifest.install_for_platform(windows=True)
        assert (
            manifest.to_json()["windows"]["install_command"]
            == manifest.windows_install_command
        )


@pytest.mark.parametrize("index", range(len(HARNESS_CLI_MANIFESTS)))
def test_windows_bundled_cli_found_off_path(tmp_path, monkeypatch, index):
    original = HARNESS_CLI_MANIFESTS[index]
    bundled = tmp_path / (original.executable + ".exe")
    bundled.write_text("fake executable\n")
    bundled.chmod(0o755)
    manifest = replace(original, windows_bundled_candidates=(str(bundled),))
    monkeypatch.setattr(registry, "os", SimpleNamespace(name="nt"))
    resolved = resolve_harness_clis("", manifests=(manifest,))[0]
    assert resolved.path == str(bundled) and resolved.source == "bundled"
    assert original.windows_install_command in manifest.missing_cli_recovery()
