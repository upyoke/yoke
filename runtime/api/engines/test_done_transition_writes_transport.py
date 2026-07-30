"""Transport-aware routing regression tests for the done-transition writes.

The done-transition finalize writes must route through the transport-aware
``call_dispatcher`` facade so the merge finalize works over an https
control plane, not only a local Postgres connection. These tests
monkeypatch ``call_dispatcher`` and assert:

* the collapsed local finalization relays as ONE atomic
  ``done_transition.finalize_local_side_effects`` write (never split), and
  degrades — never raises — on failure, matching the inline behavior;
* ``merged_at`` population relays ``done_transition.populate_merged_at``
  and fail-closes (raises) on an unresolved write, matching the inline
  ``connect()`` the engine never swallowed;
* the snapshot pre-warm relays the project read + ``project.snapshot.ensure_at``
  and stays advisory on failure;

with no bare ``_connect()`` on any write path.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.engines import done_transition as dt
from yoke_core.engines import done_transition_finalize as finalize
from yoke_core.engines import done_transition_snapshot as snapshot
from yoke_core.engines import done_transition_status as status


def _resp(function_id, result=None, *, success=True):
    return FunctionCallResponse(
        success=success, function=function_id, version="v1", result=result or {}
    )


def _install(monkeypatch, fake, modules):
    """Route every relay through *fake* and fail on any bare write connect."""
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher", fake
    )
    for module in modules:
        if hasattr(module, "call_dispatcher"):
            monkeypatch.setattr(module, "call_dispatcher", fake)
    monkeypatch.setattr(
        dt, "_connect",
        lambda *a, **k: pytest.fail("must not open a bare _connect() on a write path"),
    )


class TestFinalizeRelay:
    def test_relays_once_atomically(self, monkeypatch, capsys):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return _resp(
                "done_transition.finalize_local_side_effects",
                {"deployed_to": "stage", "release_note": True},
            )

        _install(monkeypatch, fake, [finalize])
        finalize._finalize_done_local_side_effects(
            7100, "internal", "Title", "yoke", "stage"
        )
        # A single relay keeps the deployed_to + release-note write atomic.
        assert len(calls) == 1
        assert calls[0]["function_id"] == "done_transition.finalize_local_side_effects"
        assert calls[0]["payload"] == {
            "release_category": "internal",
            "env_name": "stage",
            "title": "Title",
            "item_project": "yoke",
        }
        out = capsys.readouterr().out
        assert "deployed_to=stage" in out
        assert "release note upserted" in out

    def test_degrades_on_non_success_without_raising(self, monkeypatch, capsys):
        def fake(**kwargs):
            return _resp(
                "done_transition.finalize_local_side_effects",
                success=False,
            )

        _install(monkeypatch, fake, [finalize])
        # Advisory: must not raise; the item still reaches done.
        finalize._finalize_done_local_side_effects(7101, "internal", "T", "yoke", "")
        assert "partly skipped" in capsys.readouterr().out

    def test_degrades_on_raised_exception_without_raising(self, monkeypatch, capsys):
        def boom(**kwargs):
            raise RuntimeError("transport down")

        _install(monkeypatch, boom, [finalize])
        finalize._finalize_done_local_side_effects(7102, "internal", "T", "yoke", "")
        assert "failed" in capsys.readouterr().out


class TestMergedAtRelay:
    def test_relays_write_when_not_already_set(self, monkeypatch, capsys):
        seen = []

        def fake(**kwargs):
            fid = kwargs["function_id"]
            seen.append(fid)
            if fid == "done_transition.item_field":
                return _resp(fid, {"value": ""})
            return _resp(fid, {"item_id": 7110, "merged_at": "x"})

        _install(monkeypatch, fake, [status])
        status._populate_merged_at(7110)
        assert "done_transition.populate_merged_at" in seen
        assert "merged_at set to" in capsys.readouterr().out

    def test_short_circuits_when_already_set(self, monkeypatch, capsys):
        seen = []

        def fake(**kwargs):
            fid = kwargs["function_id"]
            seen.append(fid)
            return _resp(fid, {"value": "2026-01-01T00:00:00Z"})

        _install(monkeypatch, fake, [status])
        status._populate_merged_at(7111)
        # Only the already-set read relays; no write relay is issued.
        assert seen == ["done_transition.item_field"]
        assert "already set" in capsys.readouterr().out

    def test_fail_closed_on_unresolved_write(self, monkeypatch):
        def fake(**kwargs):
            fid = kwargs["function_id"]
            if fid == "done_transition.item_field":
                return _resp(fid, {"value": ""})
            return _resp(fid, success=False)

        _install(monkeypatch, fake, [status])
        with pytest.raises(RuntimeError, match="merged_at write failed"):
            status._populate_merged_at(7112)


class TestSnapshotRelay:
    def test_relays_project_read_and_snapshot_write(self, monkeypatch, capsys):
        seen = []

        def fake(**kwargs):
            fid = kwargs["function_id"]
            seen.append((fid, kwargs.get("payload")))
            if fid == "done_transition.item_field":
                return _resp(fid, {"value": "yoke"})
            return _resp(fid, {"project": "1", "commit_sha": "abc", "snapshot_id": 5})

        monkeypatch.setattr(
            "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
            lambda *a, **k: Path("/tmp/checkout"),
        )
        monkeypatch.setattr(
            snapshot.subprocess, "run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout="abc123\n"),
        )
        _install(monkeypatch, fake, [snapshot])
        snapshot.ensure_snapshot_for_item(7120)

        fids = [fid for fid, _ in seen]
        assert "done_transition.item_field" in fids
        assert "project.snapshot.ensure_at" in fids
        ensure_payload = dict(seen[-1][1])
        assert ensure_payload["project"] == "yoke"
        assert ensure_payload["commit_sha"] == "abc123"

    def test_advisory_on_snapshot_write_failure(self, monkeypatch, capsys):
        def fake(**kwargs):
            fid = kwargs["function_id"]
            if fid == "done_transition.item_field":
                return _resp(fid, {"value": "yoke"})
            return _resp(fid, success=False)

        monkeypatch.setattr(
            "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
            lambda *a, **k: Path("/tmp/checkout"),
        )
        monkeypatch.setattr(
            snapshot.subprocess, "run",
            lambda *a, **k: SimpleNamespace(returncode=0, stdout="abc123\n"),
        )
        _install(monkeypatch, fake, [snapshot])
        # Advisory: must not raise.
        snapshot.ensure_snapshot_for_item(7121)
        assert "advisory" in capsys.readouterr().out

    def test_skips_when_no_checkout(self, monkeypatch):
        def fake(**kwargs):
            return _resp(kwargs["function_id"], {"value": "yoke"})

        monkeypatch.setattr(
            "yoke_core.domain.project_checkout_locations.checkout_for_project_slug",
            lambda *a, **k: None,
        )
        monkeypatch.setattr(
            snapshot.subprocess, "run",
            lambda *a, **k: pytest.fail("must not resolve HEAD without a checkout"),
        )
        _install(monkeypatch, fake, [snapshot])
        snapshot.ensure_snapshot_for_item(7122)
