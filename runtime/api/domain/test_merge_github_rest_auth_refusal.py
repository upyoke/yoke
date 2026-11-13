"""A refused relay read of project GitHub state names its cause during merge.

With no local database, project GitHub auth is read through the control-plane
relay. A refused relay (timeout, version skew, transport misconfiguration)
must surface as ``AuthResolutionFailed`` with its serving code and a retry
hint, never as a traceback out of ``yoke merge item``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import merge_github_rest
from yoke_core.domain.control_plane_transport import ControlPlaneRefused
from yoke_core.domain.merge_github_authority import classify_merge_authority
from yoke_core.domain.merge_github_rest import (
    AuthResolutionFailed,
    resolve_auth,
    validate_github_auth_for_merge,
)


def _refuse(code: str, message: str):
    def _raise(*_args, **_kwargs):
        raise ControlPlaneRefused(message, code=code)

    return _raise


@pytest.fixture
def ctx():
    return SimpleNamespace(project="yoke")


def test_relay_timeout_names_failure_and_retry(monkeypatch, ctx):
    monkeypatch.setattr(
        merge_github_rest,
        "resolve_project_github_auth",
        _refuse("", "relay timed out after 30s"),
    )
    with pytest.raises(AuthResolutionFailed) as caught:
        resolve_auth(ctx, required_permissions={})
    message = str(caught.value)
    assert message.startswith("control_plane_refused: could not read project GitHub state")
    assert "relay timed out after 30s" in message
    assert "retry `yoke merge item`" in caught.value.hint
    assert "yoke env list" in caught.value.hint


def test_refusal_code_stays_in_message(monkeypatch, ctx):
    monkeypatch.setattr(
        merge_github_rest,
        "resolve_project_github_auth",
        _refuse("serving_version_too_old", "server below floor"),
    )
    with pytest.raises(AuthResolutionFailed) as caught:
        resolve_auth(ctx, required_permissions={})
    assert str(caught.value).startswith("serving_version_too_old: ")
    assert "server below floor" in str(caught.value)


def test_merge_admission_reports_refusal_without_traceback(monkeypatch, ctx):
    monkeypatch.setattr(
        merge_github_rest,
        "resolve_project_github_auth",
        _refuse("relay_timeout", "relay timed out"),
    )
    authority = classify_merge_authority(local_merge=True)
    ok, message = validate_github_auth_for_merge(ctx, authority)
    assert ok is False
    assert "relay_timeout: could not read project GitHub state" in message
    assert "Repair: check `yoke env list`, then retry `yoke merge item`" in message
