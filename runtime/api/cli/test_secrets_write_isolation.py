"""The machine-secret writer must never clobber real credentials under test.

Regression: an unisolated test wrote a stub token over the operator's live
``~/.yoke/secrets/prod.token``, 401-ing every prod call until re-minted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.config import secrets


def test_refuses_real_home_write_under_test() -> None:
    # Under pytest, a write targeting the real ~/.yoke is refused.
    real = Path.home() / ".yoke" / "secrets" / "prod.token"
    with pytest.raises(secrets.MachineSecretError, match="real machine home"):
        secrets._refuse_unisolated_test_write(real)


def test_allows_isolated_temp_write_under_test(tmp_path: Path) -> None:
    # A path outside the real home (an isolated temp dir) is allowed.
    secrets._refuse_unisolated_test_write(tmp_path / "secrets" / "prod.token")


def test_store_machine_secret_writes_under_isolated_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "home"))
    path = secrets.store_machine_secret("prod", "token", "yoke_v1_abc123")
    assert path.read_text(encoding="utf-8").strip() == "yoke_v1_abc123"
    assert str(tmp_path) in str(path)
