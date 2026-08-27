"""AWS bootstrap-link encoding at each CloudFormation decode boundary."""

from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from yoke_cli.config import aws_admin_capability as hosting

_BASE_URL = "https://api.upyoke.com"
_PLUS_VERSION = "0.1.1+launch.302"
_SECRET = "never-echo-this-secret"


def test_plus_bearing_release_survives_the_cloudformation_decode_chain() -> None:
    template = hosting.template_url(
        version=_PLUS_VERSION,
        base_url=_BASE_URL,
    )
    quick_create = hosting.quick_create_url(
        region="us-east-1",
        version=_PLUS_VERSION,
        base_url=_BASE_URL,
    )

    assert template is not None
    assert quick_create is not None
    assert "/0.1.1%2Blaunch.302/" in template
    assert "/0.1.1%252Blaunch.302/" in quick_create

    fragment_query = urlsplit(quick_create).fragment.split("?", 1)[1]
    decoded = parse_qs(fragment_query, keep_blank_values=True)
    assert decoded["templateURL"] == [template]


def test_existing_key_copy_does_not_need_a_bootstrap_link() -> None:
    """A source build may lack a link without blocking brought credentials."""
    assert hosting.template_url(version="", base_url=_BASE_URL) is None
    assert hosting.quick_create_url(version="", base_url=_BASE_URL) is None


def test_store_failure_never_echoes_the_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_args, **_kwargs):
        raise PermissionError(f"write rejected for {_SECRET}")

    monkeypatch.setattr(
        hosting.importlib,
        "import_module",
        lambda _name: SimpleNamespace(store_machine_capability_secret=refuse),
    )

    with pytest.raises(hosting.HostingCredentialError) as failure:
        hosting.store_credential(
            "acme-app",
            access_key_id="AKIAEXAMPLEEXAMPLE12",
            secret_access_key=_SECRET,
        )

    assert "PermissionError" in str(failure.value)
    assert _SECRET not in str(failure.value)


def test_unexpected_verifier_failure_never_echoes_request_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_args, **_kwargs):
        raise RuntimeError(f"unexpected request state {_SECRET}")

    monkeypatch.setattr(
        hosting.importlib,
        "import_module",
        lambda _name: SimpleNamespace(verify_machine_caller_identity=refuse),
    )

    with pytest.raises(hosting.HostingVerificationError) as failure:
        hosting.verify_caller_identity("acme-app", "us-east-1")

    assert "RuntimeError" in str(failure.value)
    assert _SECRET not in str(failure.value)
