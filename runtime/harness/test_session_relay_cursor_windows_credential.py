"""The Windows Cursor reader reads only the default DPAPI store, with named refusals."""

import base64
import json
from pathlib import Path

import pytest

from yoke_harness import session_relay_cursor_windows_credential as reader

SECRET = "fixture-bearer-token"
SEALED = b"sealed-by-fixture"


def _unprotect(blob: bytes) -> bytes | None:
    if blob != SEALED:
        return None
    return json.dumps({"accessToken": SECRET, "refreshToken": "r"}).encode()


def _profile(tmp_path: Path, marker, store) -> dict[str, str]:
    profile = tmp_path / "roaming" / "cursor"
    profile.mkdir(parents=True)
    if marker is not None:
        text = marker if isinstance(marker, str) else json.dumps(marker)
        (profile / "auth.json").write_text(text)
    if store is not None:
        text = store if isinstance(store, str) else json.dumps(store)
        (profile / "auth.dpapi").write_text(text)
    return {"APPDATA": str(tmp_path / "roaming")}


def _store(blob: bytes = SEALED, version=1) -> dict:
    return {"version": version, "dpapi": base64.b64encode(blob).decode()}


MARKER = {"storedIn": "os-secret-store"}


def test_default_store_yields_the_token(tmp_path):
    env = _profile(tmp_path, MARKER, _store())
    assert reader.cursor_windows_access_token(env, _unprotect) == (SECRET, "")


def test_profile_falls_back_to_the_roaming_home(tmp_path, monkeypatch):
    monkeypatch.setattr(reader.Path, "home", lambda: tmp_path)
    assert reader.cursor_profile_dir({}) == tmp_path / "AppData/Roaming/cursor"


@pytest.mark.parametrize(
    "marker",
    [None, "not-json", "[]", {}, {"signedOut": True}, {"accessToken": SECRET}],
)
def test_marker_without_store_is_stale_and_plaintext_is_ignored(tmp_path, marker):
    env = _profile(tmp_path, marker, _store())
    assert reader.cursor_windows_access_token(env, _unprotect) == (
        None,
        "stale_credential",
    )


@pytest.mark.parametrize(
    "store",
    [
        None,
        "not-json",
        "[]",
        {"version": 1},
        {"version": 1, "dpapi": "%%%"},
        _store(b"sealed-for-another-user"),
        _store(b"x" * 70000),
    ],
)
def test_absent_or_unusable_store_is_missing(tmp_path, store):
    env = _profile(tmp_path, MARKER, store)
    assert reader.cursor_windows_access_token(env, _unprotect) == (
        None,
        "cursor_secret_store_missing",
    )


@pytest.mark.parametrize(
    "plain", [b"not-json", b"[]", b"{}", b'{"accessToken": " "}', b"\xff"]
)
def test_unusable_decrypted_payload_is_missing(tmp_path, plain):
    env = _profile(tmp_path, MARKER, _store())
    result = reader.cursor_windows_access_token(env, lambda blob: plain)
    assert result == (None, "cursor_secret_store_missing")


@pytest.mark.parametrize(
    ("marker", "store", "extra_env"),
    [
        (MARKER, _store(), {"CURSOR_CLI_WINDOWS_CREDENTIAL_MANAGER": "1"}),
        ({"storedIn": "credential-locker"}, _store(), {}),
        (MARKER, _store(version=2), {}),
    ],
)
def test_unknown_store_configuration_is_unsupported(
    tmp_path, marker, store, extra_env
):
    env = {**_profile(tmp_path, marker, store), **extra_env}
    assert reader.cursor_windows_access_token(env, _unprotect) == (
        None,
        "cursor_secret_store_unsupported",
    )
