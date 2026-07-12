"""Hard startup boundary for GitHub App runtime identity attestation."""

from __future__ import annotations

import asyncio
import logging
import threading
import time

import pytest
from fastapi.testclient import TestClient

from runtime.api.fixtures import pg_testdb
from runtime.api.domain.github_app_public_profile_test_support import (
    complete_github_app_env,
    matching_github_app_identity,
)
from yoke_contracts.github_app_public import (
    GITHUB_APP_CLIENT_ID_ENV,
    GITHUB_APP_ID_ENV,
    GITHUB_APP_SLUG_ENV,
    GITHUB_APP_WEB_URL_ENV,
)
import yoke_core.api.main  # noqa: F401 - app-factory import anchor
from yoke_core.api import app_factory
from yoke_core.domain import github_app_public_runtime
from yoke_core.domain.github_app_public_runtime import (
    GITHUB_APP_STARTUP_ATTESTATION_TIMEOUT_SECONDS,
    attest_github_app_runtime_identity_with_hard_deadline,
    current_github_app_public_advertisement,
    reset_github_app_public_attestation_for_tests,
)


@pytest.fixture(autouse=True)
def _reset_attestation():
    reset_github_app_public_attestation_for_tests()
    yield
    reset_github_app_public_attestation_for_tests()


def test_hard_startup_deadline_cannot_publish_a_late_network_result(
    tmp_path,
    caplog: pytest.LogCaptureFixture,
):
    env, _key = complete_github_app_env(tmp_path)
    release = threading.Event()
    finished = threading.Event()
    identity = matching_github_app_identity()

    def stalled_network(*args, **kwargs):
        release.wait()
        finished.set()
        return identity

    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="yoke.api.startup"):
        attested = asyncio.run(
            attest_github_app_runtime_identity_with_hard_deadline(
                env,
                identity_fetcher=stalled_network,
                timeout_seconds=0.03,
            )
        )
    elapsed = time.monotonic() - started

    assert attested is False
    assert elapsed < 0.5
    assert "hard startup deadline" in caplog.text
    assert current_github_app_public_advertisement(env).model_dump() == {
        "available": False,
    }

    release.set()
    assert finished.wait(timeout=1.0)
    assert current_github_app_public_advertisement(env).model_dump() == {
        "available": False,
    }


@pytest.mark.parametrize(
    ("profile_mode", "expected_available", "expect_warning"),
    [
        ("complete", True, False),
        ("private-only", False, False),
        ("partial", False, True),
        ("invalid", False, True),
    ],
)
def test_testclient_lifespan_attests_each_runtime_profile_shape(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    profile_mode: str,
    expected_available: bool,
    expect_warning: bool,
):
    env, _key = complete_github_app_env(tmp_path)
    if profile_mode == "private-only":
        for name in (
            GITHUB_APP_CLIENT_ID_ENV,
            GITHUB_APP_ID_ENV,
            GITHUB_APP_SLUG_ENV,
            GITHUB_APP_WEB_URL_ENV,
        ):
            env.pop(name)
    elif profile_mode == "partial":
        env.pop(GITHUB_APP_SLUG_ENV)
    elif profile_mode == "invalid":
        env[GITHUB_APP_WEB_URL_ENV] = "https://unrelated.example"
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    for name in (
        GITHUB_APP_CLIENT_ID_ENV,
        GITHUB_APP_ID_ENV,
        GITHUB_APP_SLUG_ENV,
        GITHUB_APP_WEB_URL_ENV,
    ):
        if name not in env:
            monkeypatch.delenv(name, raising=False)
    calls = []

    def identity_fetcher(config, *, opener, timeout_seconds):
        calls.append((config.issuer, opener, timeout_seconds))
        return matching_github_app_identity()

    monkeypatch.setattr(
        github_app_public_runtime,
        "fetch_authenticated_app_identity",
        identity_fetcher,
    )
    with caplog.at_level(logging.WARNING, logger="yoke.api.startup"):
        with pg_testdb.test_database(), TestClient(app_factory.create_app()) as client:
            payload = client.get("/v1/health").json()

    assert payload["github_app"]["available"] is expected_available
    assert calls and calls[0][2] == GITHUB_APP_STARTUP_ATTESTATION_TIMEOUT_SECONDS
    warning = "set every public profile field"
    assert (warning in caplog.text) is expect_warning
    assert "Iv23public" not in caplog.text
    assert "unrelated.example" not in caplog.text
    assert "test-private-key" not in caplog.text
