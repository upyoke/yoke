"""Source-bound CLI commands preserve the checkout instead of reinstalling."""

import pytest

from yoke_cli.commands import self_host
from yoke_cli.commands.adapters import self_update
from yoke_cli.config import install_binding
from yoke_cli.self_host import bundle, release_target, upgrade


@pytest.fixture()
def source_checkout(tmp_path, monkeypatch):
    checkout = tmp_path / "yoke"
    checkout.mkdir()
    (checkout / "pyproject.toml").write_text('name = "yoke"\n')
    (checkout / "runtime" / "harness").mkdir(parents=True)
    module = checkout / "packages" / "yoke-cli" / "src" / "yoke_cli" / "__init__.py"
    module.parent.mkdir(parents=True)
    module.write_text("# source install must survive\n")
    monkeypatch.setattr(install_binding.yoke_cli, "__file__", str(module))

    def forbidden(*_args, **_kwargs):
        pytest.fail("source checkout must refuse before release, installer, or Docker")

    for name in ("channel_release_target", "fetch_installer", "run_installer"):
        monkeypatch.setattr(release_target, name, forbidden)
    monkeypatch.setattr(upgrade, "_CHECK_DOCKER", forbidden)
    monkeypatch.setattr(upgrade, "_RUN", forbidden)
    return checkout, module


@pytest.mark.parametrize(
    "command,args",
    [
        (self_update.update, []),
        (self_update.update, ["--json"]),
        (self_host.self_host_upgrade, []),
        (self_host.self_host_upgrade, ["--yes"]),
        (self_host.self_host_upgrade, ["--yes", "--json"]),
    ],
)
def test_commands_refuse_source_checkout_before_any_upgrade(
    source_checkout, command, args, monkeypatch, capsys
):
    checkout, module = source_checkout
    before = module.read_bytes()
    monkeypatch.setattr(
        bundle,
        "validate_existing_bundle",
        lambda **_kwargs: pytest.fail("refuse before inspecting a bundle"),
    )
    assert command(args) == 1
    captured = capsys.readouterr()
    diagnostic = captured.out + captured.err
    assert "source checkout" in diagnostic
    assert str(checkout) in diagnostic
    assert "git workflow" in diagnostic
    assert "yoke core upgrade --from-checkout PATH --build" in diagnostic
    assert module.read_bytes() == before


def test_execution_rechecks_source_binding_and_preserves_bundle(
    source_checkout, tmp_path
):
    directory = tmp_path / "server-bundle"
    bundle.write_bundle(
        directory=str(directory), image="ghcr.io/upyoke/yoke-server:old"
    )
    before = {
        path: path.read_bytes() for path in directory.rglob("*") if path.is_file()
    }
    plan = upgrade.UpgradePlan(
        directory=directory,
        target=release_target.ReleaseTarget(
            version="1.0.0",
            source_commit="a" * 40,
            image="ghcr.io/upyoke/yoke-server:new",
            base_url="https://distribution.example",
            channel="stable",
            installer_url="https://distribution.example/dist/install.py",
        ),
        docker_executable="/usr/bin/docker",
        previous_image="ghcr.io/upyoke/yoke-server:old",
    )
    with pytest.raises(upgrade.SelfHostUpgradeError) as raised:
        upgrade.execute_upgrade(plan)
    assert raised.value.code == "source-checkout"
    assert {
        path: path.read_bytes() for path in directory.rglob("*") if path.is_file()
    } == before


def test_wheel_under_checkout_remains_a_packaged_install(source_checkout, monkeypatch):
    checkout, _module = source_checkout
    origin = checkout / ".venv" / "site-packages" / "yoke_cli" / "__init__.py"
    monkeypatch.setattr(install_binding.yoke_cli, "__file__", str(origin))
    binding = install_binding.require_packaged_install("yoke self-host upgrade")
    assert binding["kind"] == install_binding.KIND_PACKAGED_WHEEL
    assert binding["checkout_root"] is None
