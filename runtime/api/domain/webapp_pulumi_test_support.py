"""Pulumi output and dynamic-resource fakes shared by webapp stack tests."""

from __future__ import annotations

import types
from pathlib import Path

from yoke_core.domain.pack_catalog import (
    list_pack_descriptors,
    pack_version_root,
)


def _pack_program_source(filename: str) -> Path:
    """Resolve the one latest Pack that owns an infrastructure program file."""

    matches = []
    for descriptor in list_pack_descriptors():
        candidate = pack_version_root(descriptor["slug"]) / "infra" / filename
        if candidate.is_file():
            matches.append(candidate)
    assert len(matches) == 1, (
        f"expected one latest Pack to own infra/{filename}, found {matches}"
    )
    return matches[0]


class _FakeOutput:
    """Stand-in for ``pulumi.Output`` with immediate ``apply`` evaluation."""

    def __init__(self, value):
        self.value = value

    def apply(self, fn):
        return fn(self.value)

    @staticmethod
    def from_input(value):
        return value if isinstance(value, _FakeOutput) else _FakeOutput(value)

    @staticmethod
    def concat(*parts):
        return "".join(
            str(part.value if isinstance(part, _FakeOutput) else part)
            for part in parts
        )

    @staticmethod
    def all(*args, **kwargs):
        def unwrap(value):
            return value.value if isinstance(value, _FakeOutput) else value

        if args and kwargs:
            raise TypeError("Output.all accepts positional or keyword inputs")
        resolved = (
            [unwrap(value) for value in args]
            if args
            else {key: unwrap(value) for key, value in kwargs.items()}
        )
        return _FakeOutput(resolved)


def _make_dynamic_module(recorder):
    dynamic = types.ModuleType("pulumi.dynamic")

    class _ResourceProvider:
        pass

    class _Resource:
        def __init__(self, provider, resource_name, props, opts=None):
            self.resource_type = "pulumi:dynamic:Resource"
            self.resource_name = resource_name
            self.provider = provider
            self.props = props
            self.opts = opts
            recorder.resources.append(self)

    class _CreateResult:
        def __init__(self, id_=None, outs=None):
            self.id_ = id_
            self.outs = outs

    dynamic.ResourceProvider = _ResourceProvider
    dynamic.Resource = _Resource
    dynamic.CreateResult = _CreateResult
    return dynamic


def _make_certificate_class(recorder):
    class _Certificate:
        def __init__(self, resource_name, opts=None, **kwargs):
            self.resource_type = "aws:acm:Certificate"
            self.resource_name = resource_name
            self.opts = opts
            self.kwargs = kwargs
            self.arn = "arn:aws:acm:us-east-1:123456789012:certificate/new"
            self.domain_validation_options = _FakeOutput([
                types.SimpleNamespace(
                    resource_record_name="_api.example.com",
                    resource_record_type="CNAME",
                    resource_record_value="_api-validation.example.com",
                ),
                types.SimpleNamespace(
                    resource_record_name="_origin.example.com",
                    resource_record_type="CNAME",
                    resource_record_value="_origin-validation.example.com",
                ),
            ])
            recorder.resources.append(self)

    return _Certificate
