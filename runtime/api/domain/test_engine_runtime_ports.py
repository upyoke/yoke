"""Installed execution providers honor domain-owned runtime interfaces."""

import importlib
from pathlib import Path
import tomllib

import pytest

from yoke_core.domain import engine_runtime_ports as ports


ROOT = Path(__file__).resolve().parents[3]
DECLARED = tomllib.loads(
    (ROOT / "packages/yoke-core/pyproject.toml").read_text()
)["project"]["entry-points"]["yoke.runtime"]
NAMES = sorted(name.removeprefix("get_") for name in vars(ports) if name.startswith("get_"))


@pytest.mark.parametrize("name", NAMES)
def test_installed_provider_retains_module_and_exception_identity(name):
    provider = getattr(ports, f"get_{name}")()
    assert provider is importlib.import_module(DECLARED[name])
    assert getattr(ports, f"get_{name}")() is provider


def test_lane_refusal_can_be_caught_through_domain_port():
    provider = ports.get_lane_base_update()
    from yoke_core.engines.lane_base_update import LaneBaseUpdateRefused

    with pytest.raises(provider.LaneBaseUpdateRefused):
        raise LaneBaseUpdateRefused("lane base refused")


def test_missing_provider_names_install_recovery(monkeypatch):
    from yoke_contracts.runtime_ports import loader

    monkeypatch.setattr(loader, "_installed_ports", lambda: ())
    loader.load_port.cache_clear()
    try:
        with pytest.raises(loader.RuntimeAdapterUnavailable) as exc:
            ports.get_main_checkout_sync()
        assert "runtime_adapter_unavailable: main_checkout_sync" in str(exc.value)
        assert "Install matching Yoke packages" in str(exc.value)
    finally:
        loader.load_port.cache_clear()
