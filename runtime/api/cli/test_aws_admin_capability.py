"""AWS bootstrap-link encoding at each CloudFormation decode boundary."""

from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from yoke_cli.commands.adapters import aws as aws_adapter
from yoke_cli.config import aws_admin_capability as hosting
from yoke_contracts import api_urls

_BASE_URL = api_urls.AWS_BOOTSTRAP_TEMPLATE_PROD_URL
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


def test_hosted_channels_select_their_supported_s3_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        api_urls.DISTRIBUTION_BASE_URL_ENV,
        f"{api_urls.DISTRIBUTION_STAGE_URL}/",
    )
    assert hosting.bootstrap_template_base_url() == (
        api_urls.AWS_BOOTSTRAP_TEMPLATE_STAGE_URL
    )

    monkeypatch.setenv(
        api_urls.DISTRIBUTION_BASE_URL_ENV,
        "https://packages.example.invalid",
    )
    assert hosting.bootstrap_template_base_url() is None


@pytest.mark.parametrize(
    "base_url",
    [
        api_urls.DISTRIBUTION_PROD_URL,
        "https://distribution.example.cloudfront.net",
        "https://bucket.s3-website-us-east-1.amazonaws.com",
        "https://other-bucket.s3.us-east-1.amazonaws.com",
    ],
)
def test_unapproved_template_hosts_never_generate_a_link(base_url: str) -> None:
    assert hosting.template_url(version=_PLUS_VERSION, base_url=base_url) is None
    assert hosting.quick_create_url(version=_PLUS_VERSION, base_url=base_url) is None


def test_admin_link_refusal_teaches_the_supported_recovery(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(hosting, "quick_create_url", lambda **_kwargs: None)

    assert aws_adapter.aws_admin_link([]) == 1

    output = capsys.readouterr()
    assert output.out == ""
    assert "no supported CloudFormation bootstrap link" in output.err
    assert "Reinstall from a hosted Yoke release" in output.err
    assert "existing AWS credentials" in output.err


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
