"""https-shaped control-plane seams must not bare-connect.

Actor identity lookup and function-call ledger own-connection paths must
route through ``local_connection_or_none``. When that reports no local
authority they degrade — never call bare ``db_helpers.connect()`` (the
client-context guard raises under https).
"""

from __future__ import annotations

from yoke_core.domain import function_call_ledger as ledger
from yoke_core.domain import yoke_function_actor_identity as actor_identity
from yoke_core.domain.yoke_function_actor_identity import ActorLookup


def test_actor_resolver_uses_local_connection_or_none(monkeypatch) -> None:
    seen: list[object] = []

    def fake_local(connect):  # noqa: ANN001
        seen.append(connect)
        return None

    monkeypatch.setattr(
        "yoke_core.domain.control_plane_transport.local_connection_or_none",
        fake_local,
    )
    result = actor_identity._default_actor_id_resolver("https-seam-session")
    assert result == ActorLookup()
    assert len(seen) == 1


def test_ledger_lookup_uses_local_connection_or_none(monkeypatch) -> None:
    seen: list[object] = []

    def fake_local(connect):  # noqa: ANN001
        seen.append(connect)
        return None

    monkeypatch.setattr(
        "yoke_core.domain.control_plane_transport.local_connection_or_none",
        fake_local,
    )
    assert ledger.lookup_call("https-seam-request-id") is None
    assert len(seen) == 1


def test_ledger_record_skips_when_no_local_authority(monkeypatch) -> None:
    monkeypatch.setattr(
        "yoke_core.domain.control_plane_transport.local_connection_or_none",
        lambda connect: None,
    )
    written = ledger.record_call(
        "https-seam-request-id",
        "example.fn",
        {"ok": True},
        actor_id="actor-1",
        authorization_scope="scope",
        payload_checksum="checksum",
    )
    assert written is False
