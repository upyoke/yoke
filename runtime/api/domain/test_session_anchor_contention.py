"""A contended session anchor heals when contention ends — never latches.

Exercises the tenancy decision (`yoke_contracts.session_anchor_contention`)
and its wiring through `session_identity.record_session_anchor`, entirely on
tmp registries with injected probes and process tables.
"""

from __future__ import annotations

import json

import pytest

from yoke_contracts import session_anchor_contention as contention
from yoke_contracts import session_identity
from yoke_contracts.process_ancestry import ProcessAnchor

_START = "Wed Jun 10 14:05:41 2026"


def _anchor(pid=200, start=_START, name="claude"):
    return ProcessAnchor(pid=pid, start_time=start, process_name=name)


@pytest.fixture()
def registry(tmp_path):
    return tmp_path / "session-anchors"


def _write(registry, session_id, *, probe=None, pid=200, start=_START):
    return session_identity.record_session_anchor(
        session_id,
        registry,
        anchor=_anchor(pid=pid, start=start),
        contender_is_live=probe,
    )


def _on_disk(registry, pid=200):
    return json.loads((registry / f"{pid}.json").read_text())


def _resolve(registry, pid=200):
    return session_identity.resolve_session_from_ancestry(
        registry,
        400,
        parents={400: pid, pid: 1},
        start_time_of=lambda _pid: _START,
    )


class TestTenancyDecision:
    def test_sole_candidate_is_clean_tenancy(self):
        decision = contention.resolve_tenancy(
            None, "sess-a",
            anchors_dir=None, this_pid=200,
            load_record=lambda _p: None, start_time_of=lambda _p: None,
        )
        assert not decision.contended
        assert decision.tenant_session_id == "sess-a"

    def test_writer_is_never_probed(self):
        probed: list[str] = []
        existing = {"session_id": "sess-b", "anchor_start_time": _START}

        def probe(session_id):
            probed.append(session_id)
            return True

        contention.resolve_tenancy(
            existing, "sess-a",
            anchors_dir=None, this_pid=200,
            load_record=lambda _p: None, start_time_of=lambda _p: None,
            contender_is_live=probe,
        )
        # The writer's hook event is live proof of the process; only the
        # recorded contender's session row is in question.
        assert probed == ["sess-b"]

    def test_probe_error_keeps_the_contender(self):
        existing = {"session_id": "sess-b", "anchor_start_time": _START}

        def probe(_session_id):
            raise RuntimeError("transport down")

        decision = contention.resolve_tenancy(
            existing, "sess-a",
            anchors_dir=None, this_pid=200,
            load_record=lambda _p: None, start_time_of=lambda _p: None,
            contender_is_live=probe,
        )
        assert decision.contended
        assert decision.contending_session_ids == ("sess-a", "sess-b")


class TestContentionHeals:
    def test_marker_heals_once_the_co_tenant_ends(self, registry):
        _write(registry, "sess-a")
        _write(registry, "sess-b")
        assert _on_disk(registry)["shared_by_multiple_sessions"]
        assert _resolve(registry) is None

        healed = _write(
            registry, "sess-a",
            probe=lambda sid: False if sid == "sess-b" else True,
        )
        assert healed["session_id"] == "sess-a"
        assert "shared_by_multiple_sessions" not in healed
        assert _resolve(registry) == "sess-a"

    def test_marker_persists_while_both_tenants_live(self, registry):
        _write(registry, "sess-a")
        _write(registry, "sess-b")
        still = _write(registry, "sess-a", probe=lambda _sid: True)
        assert still["shared_by_multiple_sessions"]
        assert still["contending_session_ids"] == ["sess-a", "sess-b"]
        assert _resolve(registry) is None

    def test_unknown_liveness_stays_contended(self, registry):
        _write(registry, "sess-a")
        _write(registry, "sess-b")
        still = _write(registry, "sess-a", probe=lambda _sid: None)
        assert still["shared_by_multiple_sessions"]

    def test_no_probe_stays_contended(self, registry):
        _write(registry, "sess-a")
        _write(registry, "sess-b")
        assert _write(registry, "sess-a")["shared_by_multiple_sessions"]

    def test_blank_marker_from_before_contender_recording_heals(self, registry):
        """The deployed latch shape: session_id blanked, no contender list."""
        directory = registry
        directory.mkdir(parents=True)
        (directory / "200.json").write_text(json.dumps({
            "session_id": "",
            "transcript_path": "",
            "anchor_pid": 200,
            "anchor_start_time": _START,
            "anchor_process_name": "claude",
            "registered_at": "2026-08-02T12:53:43+00:00",
            "shared_by_multiple_sessions": True,
        }))
        assert _resolve(registry) is None

        healed = _write(registry, "sess-a")
        assert healed["session_id"] == "sess-a"
        assert _resolve(registry) == "sess-a"

    def test_foreign_id_with_a_live_home_elsewhere_is_dropped(
        self, registry, monkeypatch,
    ):
        """The observed incident: another session's id written onto this pid.

        The foreign session's real per-conversation process holds its clean
        anchor; that live home is evidence the claim on this pid was written
        in error, so the rightful tenant heals the marker even while the
        foreign session is still live.
        """
        monkeypatch.setattr(
            session_identity, "process_start_time",
            {200: _START, 300: "s300"}.get,
        )
        _write(registry, "sess-b", pid=300, start="s300")
        _write(registry, "sess-a")
        contended = _write(registry, "sess-b")  # the foreign write
        assert contended["shared_by_multiple_sessions"]

        healed = _write(registry, "sess-a", probe=lambda _sid: True)
        assert healed["session_id"] == "sess-a"
        assert _resolve(registry) == "sess-a"
        # The foreign session's own anchor is untouched throughout.
        assert _on_disk(registry, pid=300)["session_id"] == "sess-b"

    def test_contended_record_elsewhere_is_not_a_live_home(self, registry):
        """Only a clean record counts as evidence of a session's real home."""
        _write(registry, "sess-a")
        _write(registry, "sess-b")
        (registry / "300.json").write_text(json.dumps({
            "session_id": "",
            "anchor_pid": 300,
            "anchor_start_time": "s300",
            "shared_by_multiple_sessions": True,
            "contending_session_ids": ["sess-b", "sess-c"],
        }))
        # sess-b's only other trace is itself a contention marker — that is
        # an ambiguity, not a home, so sess-a cannot reclaim the pid.
        still = _write(registry, "sess-a", probe=lambda _sid: True)
        assert still["shared_by_multiple_sessions"]


class TestHealedTenancyEndToEnd:
    def test_resolution_refuses_then_resolves_after_heal(self, registry):
        _write(registry, "sess-a")
        _write(registry, "sess-b")
        assert _resolve(registry) is None
        _write(
            registry, "sess-a",
            probe=lambda sid: False if sid == "sess-b" else True,
        )
        assert _resolve(registry) == "sess-a"
