"""Pulumi child GitHub 401 classification."""

from io import StringIO

import pytest

from runtime.api.tools.pulumi_exec_support_test_support import (
    _Child,
    _execute,
    _file_project,
)
from yoke_core.tools.pulumi_exec import PulumiExecError
from yoke_core.tools.pulumi_exec_github_failure import (
    GITHUB_PROVIDER_UNAUTHORIZED,
    looks_like_github_provider_unauthorized,
    named_github_provider_failure,
)


def test_classifier_requires_github_401():
    assert looks_like_github_provider_unauthorized(
        "GET https://api.github.com/repos/acme/app/actions/variables/X: "
        "401 Bad credentials []: provider=github@6.14.0"
    )
    assert looks_like_github_provider_unauthorized(
        "refresh failed: 401 Bad credentials []: provider=github@6.14.0"
    )
    assert not looks_like_github_provider_unauthorized(
        "GET https://api.github.com/repos/acme/app/environments/prod: 403"
    )
    assert not looks_like_github_provider_unauthorized(
        "error: preview failed"
    )


def test_named_failure_omits_token_material_and_names_restore():
    message = named_github_provider_failure(
        "platform",
        "GET https://api.github.com/repos/upyoke/platform/actions/variables/"
        "YOKE_PROD_DISTRIBUTION_BUCKET: 401 Bad credentials []",
    )
    assert message is not None
    assert GITHUB_PROVIDER_UNAUTHORIZED in message
    assert "ghu_" not in message
    assert "yoke github status" in message
    assert "github-binding status --project platform" in message
    assert "GITHUB_TOKEN" in message
    assert named_github_provider_failure("platform", "preview failed") is None


def test_github_401_child_raises_named_provider_failure(tmp_path):
    err = StringIO()
    stderr = (
        b"GET https://api.github.com/repos/upyoke/platform/actions/variables/"
        b"YOKE_PROD_DISTRIBUTION_BUCKET: 401 Bad credentials []: "
        b"provider=github@6.14.0\n"
    )
    with pytest.raises(PulumiExecError, match=GITHUB_PROVIDER_UNAUTHORIZED) as raised:
        _execute(
            _file_project(tmp_path),
            ["preview"],
            child_factory=lambda command, **kwargs: _Child(
                stdout=b"",
                stderr=stderr,
                returncode=1,
            ),
            err=err,
        )
    assert "401 Bad credentials" in err.getvalue()
    assert "ghu_" not in str(raised.value)
    assert "github-binding status --project externalwebapp" in str(raised.value)


def test_non_github_child_failure_keeps_returncode(tmp_path):
    err = StringIO()
    code = _execute(
        _file_project(tmp_path),
        ["preview"],
        child_factory=lambda command, **kwargs: _Child(
            stdout=b"",
            stderr=b"error: preview failed\n",
            returncode=1,
        ),
        err=err,
    )
    assert code == 1
    assert "preview failed" in err.getvalue()
