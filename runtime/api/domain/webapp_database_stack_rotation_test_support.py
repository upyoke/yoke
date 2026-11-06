# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import importlib.util

import sys

import types

import pytest


class _FakeCreateResult:
    def __init__(self, id_: str, outs: dict):
        self.id = id_
        self.outs = outs


class _FakeDiffResult:
    def __init__(self, changes: bool):
        self.changes = changes


class _FakeUpdateResult:
    def __init__(self, outs: dict):
        self.outs = outs


class _FakeResourceProvider:
    pass


class _FakeResource:
    def __init__(self, provider, name, props, opts=None):
        self.provider = provider
        self.name = name
        self.props = props
        self.opts = opts


def _load_database_stack_module(monkeypatch):
    fake_pulumi = types.ModuleType("pulumi")
    fake_pulumi.ComponentResource = object
    fake_pulumi.ResourceOptions = object
    fake_pulumi.Input = object
    fake_pulumi.Output = object
    fake_pulumi.RunError = RuntimeError
    fake_dynamic = types.ModuleType("pulumi.dynamic")
    fake_dynamic.ResourceProvider = _FakeResourceProvider
    fake_dynamic.Resource = _FakeResource
    fake_dynamic.CreateResult = _FakeCreateResult
    fake_dynamic.DiffResult = _FakeDiffResult
    fake_dynamic.UpdateResult = _FakeUpdateResult
    fake_aws = types.ModuleType("pulumi_aws")
    monkeypatch.setitem(sys.modules, "pulumi", fake_pulumi)
    monkeypatch.setitem(sys.modules, "pulumi.dynamic", fake_dynamic)
    monkeypatch.setitem(sys.modules, "pulumi_aws", fake_aws)

    from runtime.api.domain.webapp_pulumi_test_support import _pack_program_source

    path = _pack_program_source("webapp_database_stack.py")
    spec = importlib.util.spec_from_file_location("_webapp_database_stack_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    monkeypatch.setitem(sys.modules, "_webapp_database_stack_test", module)
    spec.loader.exec_module(module)
    return module
