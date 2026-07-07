"""The env-token writer refuses to let a stub overwrite a valid token.

Regression: an accidental stub overwrote a live ~/.yoke/secrets/prod.token,
401-ing every prod call. A short value may still be written to a *fresh* env
(no valid token to lose); only a downgrade over an existing plausible token is
refused.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.config import writer_credentials as wc


def _inputs(token: str) -> dict:
    return dict(
        token=token, token_file=None, token_stdin=False,
        dsn=None, dsn_file=None, dsn_stdin=False, require_one=True,
    )


def test_refuses_stub_overwriting_valid_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    wc.credential_from_inputs("prod", **_inputs("yoke_v1_" + "a" * 43))
    with pytest.raises(wc.CredentialWriteError, match="implausibly short"):
        wc.credential_from_inputs("prod", **_inputs("stub"))


def test_allows_short_token_on_fresh_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No existing token -> a short write is allowed (general credential-set).
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    result = wc.credential_from_inputs("staging", **_inputs("short-fake"))
    assert "staging.token" in result["path"]


def test_accepts_full_length_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    result = wc.credential_from_inputs("prod", **_inputs("yoke_v1_" + "a" * 43))
    assert (
        Path(result["path"]).read_text(encoding="utf-8").strip().startswith("yoke_v1_")
    )
