"""Creating a local universe needs the installer's name; verifying one does not."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.first_admin_name import ADMIN_NAME_MISSING
from yoke_core.domain import environment_bootstrap
from yoke_core.domain import local_universe as lu


def _stub_cluster(monkeypatch, *, already_born: bool) -> list[str]:
    calls: list[str] = []
    monkeypatch.setattr(lu, "ensure_engine_binaries", lambda emit=None: Path("/bin"))
    monkeypatch.setattr(lu, "start", lambda spec, emit: {"running": True})
    monkeypatch.setattr(lu, "is_born", lambda spec: already_born)
    monkeypatch.setattr(
        environment_bootstrap,
        "run_bootstrap",
        lambda emit: calls.append("bootstrap") or {},
    )
    monkeypatch.setattr(
        environment_bootstrap, "verify_bootstrap", lambda emit: calls.append("verify")
    )
    monkeypatch.setattr(lu, "_ensure_org_card", lambda org_name, emit: {})
    monkeypatch.setattr(
        lu,
        "_ensure_human_actor",
        lambda emit, admin_name: calls.append(("human", admin_name)) or 7,
    )
    return calls


def test_creating_a_universe_without_a_name_refuses_before_bootstrap(monkeypatch):
    calls = _stub_cluster(monkeypatch, already_born=False)
    with pytest.raises(RuntimeError) as refused:
        lu.birth(org_name=None)
    assert str(refused.value).startswith(f"{ADMIN_NAME_MISSING}:")
    assert "--admin-name" in str(refused.value)
    assert calls == []


def test_verifying_a_live_universe_asks_for_no_name(monkeypatch):
    calls = _stub_cluster(monkeypatch, already_born=True)
    report = lu.birth(org_name=None)
    assert report["human_actor_id"] == 7
    assert calls == ["verify", ("human", None)]
