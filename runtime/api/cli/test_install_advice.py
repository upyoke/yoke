"""Environment authority stays intact through user-facing repair advice."""

import json
import subprocess

import pytest

from yoke_cli.config import install_advice
from yoke_cli.commands.adapters.onboard_hosted_authorization import usage_error
from yoke_contracts.api_urls import (
    DISTRIBUTION_PROD_URL,
    DISTRIBUTION_STAGE_URL,
    HOSTED_PLATFORM_URL,
    HOSTED_STAGE_PLATFORM_URL,
)


@pytest.fixture
def configure(tmp_path, monkeypatch):
    monkeypatch.delenv("YOKE_INSTALL_BASE_URL", raising=False)
    monkeypatch.delenv("YOKE_MACHINE_HOME", raising=False)
    config = tmp_path / "config.json"
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config))

    def write(origin, api_url=None):
        payload = {
            "settings": {"distribution": {"origin": origin, "channel": "stable"}}
        }
        if api_url:
            payload.update(
                {
                    "active_env": "selected",
                    "connections": {
                        "selected": {"transport": "https", "api_url": api_url},
                    },
                }
            )
        config.write_text(json.dumps(payload))
        return config

    return write


@pytest.mark.parametrize("origin", [DISTRIBUTION_STAGE_URL, DISTRIBUTION_PROD_URL])
def test_recorded_origin_reaches_advisory_shims_and_standalone_launcher(
    configure, origin, tmp_path, monkeypatch
):
    configure(origin)
    command = f"curl -fsSL {origin}/install | sh"
    assert install_advice.install_command() == command
    from yoke_core.domain import main_agent_packet
    from yoke_core.tools.install_yoke_launcher_core import write_launcher
    from yoke_cli.project_install.managed_git_hooks import managed_git_hook_specs

    monkeypatch.setattr(main_agent_packet.shutil, "which", lambda name: None)
    assert command in main_agent_packet.render_install_advisory_block()
    for spec in managed_git_hook_specs():
        assert command in spec["content"]
        subprocess.run(["sh", "-n"], input=spec["content"], text=True, check=True)
    launcher = tmp_path / "launcher"
    write_launcher(launcher)
    namespace = {}
    exec(compile(launcher.read_text(), str(launcher), "exec"), namespace)
    assert command in namespace["RELEASE_RECOVERY"]


@pytest.mark.parametrize(
    "platform,origin",
    [
        (HOSTED_STAGE_PLATFORM_URL, DISTRIBUTION_STAGE_URL),
        (HOSTED_PLATFORM_URL, DISTRIBUTION_PROD_URL),
    ],
)
def test_connection_authority_precedes_install_record(configure, platform, origin):
    configure("https://distribution.example.invalid", platform + "/api/orgs/example")
    assert install_advice.install_command() == f"curl -fsSL {origin}/install | sh"


@pytest.mark.parametrize("platform", [HOSTED_STAGE_PLATFORM_URL, HOSTED_PLATFORM_URL])
@pytest.mark.parametrize("token", [True, False])
def test_fresh_hosted_refusal_names_requested_connect_url(platform, token):
    message = usage_error("hosted", token, False, False, api_url=platform)
    assert f"--connect {platform}`" in message


def test_missing_origin_teaches_repair_without_a_default(configure):
    configure("")
    message = install_advice.install_command()
    assert message.startswith("install_origin_unavailable:")
    assert "yoke settings set distribution" in message
    assert DISTRIBUTION_PROD_URL not in message


def test_served_distribution_is_explicit(configure, monkeypatch):
    configure(DISTRIBUTION_PROD_URL)
    monkeypatch.setenv("YOKE_INSTALL_BASE_URL", DISTRIBUTION_STAGE_URL)
    assert DISTRIBUTION_STAGE_URL in install_advice.install_command()


def test_windows_guidance_names_unsupported_native_path(monkeypatch) -> None:
    from yoke_contracts.api_urls import DISTRIBUTION_STAGE_URL

    monkeypatch.setenv("YOKE_INSTALL_BASE_URL", DISTRIBUTION_STAGE_URL)
    from yoke_cli.config import project_git_prerequisite

    advice = project_git_prerequisite.install_advice(
        platform_name="win32", which=lambda name: None
    )

    assert advice.command is None
    assert "Install WSL" in advice.note
    assert f"curl -fsSL {DISTRIBUTION_STAGE_URL}/install | sh" in advice.note


def test_linux_without_known_package_manager_uses_generic_guidance() -> None:
    from yoke_cli.config import project_git_prerequisite

    advice = project_git_prerequisite.install_advice(platform_name="linux", which=lambda name: None)

    assert advice.command is None
    assert "package named git" in advice.note


