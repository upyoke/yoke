"""Tests for the webapp container-registry Pulumi Pack component.

Mirrors ``test_webapp_database_stack_rotation.py``'s harness mechanics: fake
``pulumi`` / ``pulumi_aws`` modules are injected into ``sys.modules`` and the
Pack module is loaded straight from its immutable source.

The fakes themselves live in ``webapp_pulumi_fakes_test_support``; they are
re-exported here because sibling stack tests have long imported them from
this module.
"""

from __future__ import annotations

import importlib.util
import sys
import types

from runtime.api.domain.webapp_pulumi_test_support import _pack_program_source
from runtime.api.domain.webapp_pulumi_fakes_test_support import (  # noqa: F401
    _FakeArgs,
    _Recorder,
    _build_fake_aws,
    _build_fake_pulumi,
    _make_resource_class,
)



def _load_pack_module(monkeypatch, recorder, filename, extra_modules=None):
    fake_pulumi = _build_fake_pulumi(recorder)
    monkeypatch.setitem(sys.modules, "pulumi", fake_pulumi)
    monkeypatch.setitem(sys.modules, "pulumi.dynamic", fake_pulumi.dynamic)
    monkeypatch.setitem(sys.modules, "pulumi_aws", _build_fake_aws(recorder))
    for name, module in (extra_modules or {}).items():
        monkeypatch.setitem(sys.modules, name, module)
    path = _pack_program_source(filename)
    monkeypatch.syspath_prepend(str(path.parent))
    module_name = f"_{filename[:-3]}_under_test"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def _registry_stack(
    monkeypatch,
    repository_name="yoke-core",
    *,
    github_repo="",
    **arg_overrides,
):
    recorder = _Recorder()
    extra_modules = {}
    if github_repo:
        monkeypatch.setenv(
            "RUNNER_FLEET_GITHUB_TOKEN", "repository-token"
        )
        monkeypatch.setenv("GITHUB_TOKEN", "repository-token")
        pulumi_github = types.ModuleType("pulumi_github")
        pulumi_github.Provider = _make_resource_class(
            recorder, "pulumi:providers:github"
        )
        pulumi_github.ActionsVariable = _make_resource_class(
            recorder, "github:index/actionsVariable:ActionsVariable"
        )
        provider = _load_pack_module(
            monkeypatch,
            recorder,
            "webapp_github_repository_provider.py",
            extra_modules={"pulumi_github": pulumi_github},
        )
        variables = _load_pack_module(
            monkeypatch,
            recorder,
            "webapp_registry_github_variables.py",
            extra_modules={
                "pulumi_github": pulumi_github,
                "webapp_github_repository_provider": provider,
            },
        )
        extra_modules["webapp_registry_github_variables"] = variables
    module = _load_pack_module(
        monkeypatch, recorder, "webapp_registry_stack.py", extra_modules,
    )
    stack = module.WebappRegistryStack(
        "yoke-registry",
        module.WebappRegistryArgs(
            deploy_namespace="yoke",
            repository_name=repository_name,
            github_repo=github_repo,
            state_bucket="yoke-pulumi-state",
            kms_key_alias="alias/yoke-pulumi-state",
            **arg_overrides,
        ),
    )
    return recorder, stack
