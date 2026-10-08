"""Dry-run refusals distinguish an unpublished release from an unverified origin."""

from __future__ import annotations

import urllib.error
from urllib.parse import urlsplit

import pytest

from public_installer_helpers import PUBLISHED_RELEASE_RECORD, load_installer
from public_installer_publication import dry_run_installer, http_error


def test_version_published_only_at_another_origin_refuses() -> None:
    module = load_installer()
    requested: list[str] = []

    def fetch(url: str) -> bytes:
        requested.append(url)
        if "other.example" in url:
            return PUBLISHED_RELEASE_RECORD
        raise http_error(url, 404)

    installer, runner, output = dry_run_installer(
        module,
        fetcher=fetch,
        version="1.2.3",
        base_url="https://chosen.example",
    )

    with pytest.raises(module.InstallError, match="installer_release_unpublished"):
        installer.run()

    rendered = output.getvalue()
    assert "Resolved Yoke" not in rendered
    assert "Install command" not in rendered
    assert runner.commands == []
    assert requested
    assert all(urlsplit(url).hostname == "chosen.example" for url in requested)


@pytest.mark.parametrize(
    ("body", "reason", "recovery"),
    [
        (b"[]", "installer_release_unpublished", "publish Yoke 1.2.3"),
        (b"{", "installer_release_unverified", "restore access"),
        (b'{"version":"1.2.3"}', "installer_release_unverified", "restore access"),
    ],
)
def test_empty_or_malformed_release_record_refuses(body, reason, recovery) -> None:
    module = load_installer()
    installer, runner, output = dry_run_installer(
        module,
        fetcher=lambda _url: body,
        version="1.2.3",
        base_url="https://origin.example",
    )

    with pytest.raises(module.InstallError, match=reason) as raised:
        installer.run()

    assert recovery in str(raised.value)
    assert "Resolved Yoke" not in output.getvalue()
    assert runner.commands == []


def test_unreachable_origin_reports_unverified() -> None:
    module = load_installer()

    def fetch(url: str) -> bytes:
        raise urllib.error.URLError("nodename nor servname")

    installer, _runner, output = dry_run_installer(
        module,
        fetcher=fetch,
        version="1.2.3",
        base_url="https://installer-check.invalid",
    )

    with pytest.raises(
        module.InstallError, match="installer_release_unverified"
    ) as raised:
        installer.run()

    assert "restore access" in str(raised.value)
    assert "installer-check.invalid" in str(raised.value)
    assert "Resolved Yoke" not in output.getvalue()


def test_tls_failure_reports_unverified() -> None:
    module = load_installer()

    class SSLError(Exception):
        pass

    def fetch(url: str) -> bytes:
        raise urllib.error.URLError(SSLError("certificate verify failed"))

    installer, _runner, _output = dry_run_installer(
        module, fetcher=fetch, version="1.2.3", base_url="https://origin.example"
    )

    with pytest.raises(
        module.InstallError, match="installer_release_unverified"
    ) as raised:
        installer.run()

    message = str(raised.value)
    assert "TLS error" in message
    assert "restore access" in message


def test_access_failure_reports_unverified() -> None:
    module = load_installer()

    def fetch(url: str) -> bytes:
        raise http_error(url, 403)

    installer, _runner, _output = dry_run_installer(
        module, fetcher=fetch, version="1.2.3", base_url="https://origin.example"
    )

    with pytest.raises(
        module.InstallError, match="installer_release_unverified"
    ) as raised:
        installer.run()

    message = str(raised.value)
    assert "HTTP 403" in message
    assert "restore access" in message
    assert "installer_release_unpublished" not in message


def test_credentials_stay_redacted() -> None:
    module = load_installer()
    secret = "s3cret-token"
    requested: list[str] = []

    def fetch(url: str) -> bytes:
        requested.append(url)
        raise urllib.error.URLError(f"failed to open {url}")

    installer, _runner, _output = dry_run_installer(
        module,
        fetcher=fetch,
        version="1.2.3",
        base_url=f"https://operator:{secret}@origin.example",
    )

    with pytest.raises(module.InstallError) as raised:
        installer.run()

    message = str(raised.value)
    assert secret not in message
    assert "operator:" not in message
    assert "origin.example" in message
    assert requested and secret in requested[0]
