"""SSH entries substitute the launcher while preserving literal shell content."""

from types import SimpleNamespace

import pytest

from yoke_core.domain.ssh_linux_host_control import SshLinuxHostControl
from yoke_core.domain.ssh_mac_host_control import SshMacHostControl


@pytest.mark.parametrize(
    "resolve",
    [
        SshLinuxHostControl._entry_surface,
        SshMacHostControl._resolve_entry_surface,
    ],
    ids=["linux", "macos"],
)
@pytest.mark.parametrize("launcher", ["{yoke_bin}", "yoke"])
def test_entry_preserves_distribution_dict_and_quotes_launcher(resolve, launcher):
    control = SimpleNamespace(
        path_state=SimpleNamespace(yoke_bin="/home/test user/.local/bin/yoke")
    )
    config = '{"origin": "https://api.stage.upyoke.com", "channel": "latest"}'
    entry = f"{launcher} --version; python3 -c 'config = {config}'"
    expected_launcher = (
        "'/home/test user/.local/bin/yoke'" if launcher == "{yoke_bin}" else "yoke"
    )

    assert resolve(control, entry) == (
        f"{expected_launcher} --version; python3 -c 'config = {config}'"
    )


def test_macos_entry_without_launcher_needs_no_path_state():
    entry = 'python3 -c \'config = {"origin": "https://api.stage.upyoke.com"}\''

    assert SshMacHostControl._resolve_entry_surface(SimpleNamespace(), entry) == entry
