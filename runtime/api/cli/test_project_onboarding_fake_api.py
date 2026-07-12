"""Project-onboarding fake API request validation."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from runtime.api.cli.project_onboarding_test_helpers import ProjectOnboardApi


def test_fake_api_rejects_unknown_function_ids() -> None:
    with ProjectOnboardApi() as api:
        body = json.dumps(
            {
                "function": "project.create.run",
                "version": 1,
                "target": {"kind": "global"},
                "payload": {},
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{api.url}/v1/functions/call",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=5)  # noqa: S310

    assert exc.value.code == 404
