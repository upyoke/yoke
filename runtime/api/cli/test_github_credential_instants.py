"""Credential-owned clocks are native internally and canonical in portable files."""

import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import timedelta

import pytest

from yoke_contracts import timestamps
from yoke_cli.config import github_git_credential_access_cache as cache
from yoke_cli.config import github_git_credential_bundle as bundle
from yoke_cli.config import github_git_credential_document as document
from yoke_cli.config import github_git_credential_launcher as launcher
from yoke_cli.config import github_user_tokens as tokens


MOMENT = timestamps.parse_instant("2026-11-01T05:29:59.123456+05:45")


def _state():
    return document.token_state_from_response(
        {
            "access_token": "test-access",
            "expires_in": 3600,
            "refresh_token": "test-refresh",
            "refresh_token_expires_in": 7200,
        },
        now=MOMENT,
        error_type=RuntimeError,
    )


def test_credential_state_is_native_and_file_clocks_are_finite_fixed_six(tmp_path):
    state = _state()
    assert state["expires_at"] == MOMENT + timedelta(hours=1)
    assert state["refresh_expires_at"] == MOMENT + timedelta(hours=2)
    native = tokens._local_token(state)
    assert native.expires_at == state["expires_at"]
    stored = cache.persisted_document(state, schema_version=2, error_type=RuntimeError)
    assert stored["refresh_expires_at"] == timestamps.format_instant(
        state["refresh_expires_at"]
    )
    assert stored["cached_access"]["expires_at"] == timestamps.format_instant(
        state["expires_at"]
    )
    stored["evidence"] = {"expires_at": "opaque-clock-text"}
    path = tmp_path / "credentials" / "credential.json"
    document.write_document(path, stored, error_type=RuntimeError)
    before = path.read_bytes()
    reread = document.read_document(path, schema_version=2, error_type=RuntimeError)
    assert reread["refresh_expires_at"] == state["refresh_expires_at"]
    assert reread["cached_access"]["expires_at"] == state["expires_at"]
    assert reread["evidence"] == stored["evidence"]
    assert path.read_bytes() == before
    edge = state["expires_at"] - timedelta(seconds=cache.REFRESH_MARGIN_SECONDS)
    usable = cache.usable_token_state(
        reread, now=edge - timedelta(microseconds=1), error_type=RuntimeError
    )
    assert usable["expires_at"] == state["expires_at"]
    assert usable["refresh_expires_at"] == state["refresh_expires_at"]
    assert cache.usable_token_state(reread, now=edge, error_type=RuntimeError) is None
    assert json.loads(before)["evidence"] == stored["evidence"]


@pytest.mark.parametrize(
    "clock", [None, "", "2026-11-01T00:00:00", "2026-02-30T00:00:00Z", 0]
)
def test_credential_clock_parser_refuses_missing_or_invalid_required_instants(clock):
    with pytest.raises(RuntimeError, match="must be an ISO timestamp"):
        document.parse_timestamp(clock, "expiry", RuntimeError)


def test_credential_current_clock_refuses_naive_datetime():
    with pytest.raises(timestamps.InvalidInstant):
        document.ensure_utc(MOMENT.replace(tzinfo=None))


def test_standalone_helper_bundles_exact_shared_kernel_without_product_imports(
    tmp_path,
):
    directory = tmp_path / "helper"
    bundle.install(directory)
    selected = launcher.selected_bundle(directory)
    kernel = selected / launcher.BUNDLE_TIMESTAMPS_NAME
    assert kernel.read_bytes() == Path(timestamps.__file__).read_bytes()
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    code = """import sys
sys.path.insert(0, sys.argv[1])
import _yoke_github_git_credential_document as document
instant = document.parse_timestamp('2026-11-01T05:29:59.123456+05:45', 'clock', RuntimeError)
print(document.clock_contract.format_instant(instant))
try:
    document.parse_timestamp('2026-02-30T00:00:00Z', 'clock', RuntimeError)
except RuntimeError:
    pass
else:
    raise AssertionError('invalid calendar accepted')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(selected)],
        env=environment,
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.strip() == timestamps.format_instant(MOMENT)
