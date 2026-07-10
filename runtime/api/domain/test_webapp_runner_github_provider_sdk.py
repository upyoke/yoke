"""Pinned pulumi-github constructor contract for process-only runner auth."""

from importlib import metadata, util
from pathlib import Path

import pytest


_SDK_DISTRIBUTION = "pulumi-github"
_SDK_VERSION = "6.14.0"


def test_runner_template_pins_audited_pulumi_github_sdk():
    root = Path(__file__).resolve().parents[3]
    requirements = (
        root / "templates" / "webapp" / "infra" / "requirements.txt"
    ).read_text()

    assert f"{_SDK_DISTRIBUTION}=={_SDK_VERSION}" in requirements.splitlines()


def test_installed_pulumi_github_sdk_reads_token_during_constructor():
    spec = util.find_spec("pulumi_github")
    if spec is None or not spec.submodule_search_locations:
        pytest.skip("pinned template-only pulumi-github SDK is not installed")
    package = Path(next(iter(spec.submodule_search_locations)))
    source = (package / "provider.py").read_text()

    assert metadata.version(_SDK_DISTRIBUTION) == _SDK_VERSION
    assert source.count(
        "token = _utilities.get_env('GITHUB_TOKEN')"
    ) >= 2
    assert (
        '__props__.__dict__["token"] = None if token is None else '
        "pulumi.Output.secret(token)"
    ) in source
