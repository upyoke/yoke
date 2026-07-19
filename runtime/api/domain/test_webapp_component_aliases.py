"""Pulumi component type alias configuration tests."""

from __future__ import annotations

import types

import pytest

from runtime.api.domain.test_webapp_registry_stack import (
    _load_pack_module,
    _Recorder,
)


def _module(monkeypatch, raw):
    module = _load_pack_module(
        monkeypatch,
        _Recorder(),
        "webapp_component_aliases.py",
    )
    module.pulumi.Config = lambda: types.SimpleNamespace(
        get_object=lambda _key: raw,
    )
    return module


def test_component_type_aliases_selects_one_stack_kind(monkeypatch):
    module = _module(monkeypatch, {
        "infra": [" legacy:infra:EdgeStack "],
        "vps": ["legacy:infra:HostStack"],
    })

    assert module.component_type_aliases("infra") == (
        "legacy:infra:EdgeStack",
    )


@pytest.mark.parametrize("raw", [[], {"infra": "not-a-list"}, {"infra": [""]}])
def test_component_type_aliases_rejects_invalid_config(monkeypatch, raw):
    module = _module(monkeypatch, raw)

    with pytest.raises(RuntimeError):
        module.component_type_aliases("infra")
