"""Step 8 done-transition GitHub sync fail-closed coverage.

Verifies that the Step 8 helper classifies ``sync_done_item`` outcomes
into ``8`` (clean), ``8-degraded`` (sync returned non-zero), and
``8-skipped`` (import failure) so the runner can record the right
``steps_completed`` marker and surface a structured warning instead of
silently stamping ``"8"`` on a failed GitHub closeout.
"""

from __future__ import annotations

import io

from yoke_core.engines.done_transition_github_sync import (
    Step8Result,
    run_step_8,
)


class _StubSyncModule:
    def __init__(self, returncode=0, raise_exc=None):
        self.returncode = returncode
        self.raise_exc = raise_exc
        self.called_with: list[tuple[str, str]] = []

    def sync_done_item(self, item_id, old_status, *, stdout=None, stderr=None):
        self.called_with.append((item_id, old_status))
        if self.raise_exc is not None:
            raise self.raise_exc
        return self.returncode


def _patch_backlog_github_sync(monkeypatch, module):
    """Replace ``yoke_core.domain.backlog_github_sync`` in ``sys.modules``
    so the ``from yoke_core.domain import backlog_github_sync`` inside
    ``run_step_8`` resolves to the stub.
    """
    import sys
    monkeypatch.setitem(sys.modules, "yoke_core.domain.backlog_github_sync", module)
    import yoke_core.domain as _dom
    monkeypatch.setattr(_dom, "backlog_github_sync", module, raising=False)


def test_run_step_8_records_step_marker_8_on_success(monkeypatch):
    stub = _StubSyncModule(returncode=0)
    _patch_backlog_github_sync(monkeypatch, stub)
    stderr = io.StringIO()

    result = run_step_8(1234, "release", stderr=stderr)

    assert isinstance(result, Step8Result)
    assert result.returncode == 0
    assert result.step_marker == "8"
    assert result.is_degraded is False
    assert stub.called_with == [("1234", "release")]


def test_run_step_8_records_step_marker_8_degraded_on_nonzero(monkeypatch):
    stub = _StubSyncModule(returncode=1)
    _patch_backlog_github_sync(monkeypatch, stub)
    stderr = io.StringIO()

    result = run_step_8(1704, "release", stderr=stderr)

    assert result.returncode == 1
    assert result.step_marker == "8-degraded"
    assert result.is_degraded is True
    err = stderr.getvalue()
    assert "YOK-1704" in err
    assert "degraded" in err
    assert "sync_done_item returned 1" in err


def test_run_step_8_treats_exception_as_degraded(monkeypatch):
    stub = _StubSyncModule(raise_exc=RuntimeError("transient gh failure"))
    _patch_backlog_github_sync(monkeypatch, stub)
    stderr = io.StringIO()

    result = run_step_8(1665, "release", stderr=stderr)

    assert result.returncode == 1
    assert result.step_marker == "8-degraded"
    assert "transient gh failure" in stderr.getvalue()


def test_run_step_8_skipped_on_import_failure(monkeypatch):
    """When ``backlog_github_sync`` cannot be imported (transient install
    issue, deleted module), Step 8 must record ``8-skipped`` so the
    runner does not stamp success on a sync that did not happen.
    """
    import builtins

    real_import = builtins.__import__

    def _failing_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "yoke_core.domain" and "backlog_github_sync" in (fromlist or ()):
            raise ImportError("simulated failure for backlog_github_sync")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _failing_import)
    stderr = io.StringIO()
    result = run_step_8(42, "release", stderr=stderr)

    assert result.returncode == 0
    assert result.step_marker == "8-skipped"
    assert "YOK-42" in stderr.getvalue()


def test_step_8_result_contract():
    ok = Step8Result(returncode=0, step_marker="8", message="ok")
    bad = Step8Result(returncode=1, step_marker="8-degraded", message="failed")
    skip = Step8Result(returncode=0, step_marker="8-skipped", message="skipped")

    assert ok.is_degraded is False
    assert bad.is_degraded is True
    assert skip.is_degraded is False
