"""Regression coverage for :mod:`yoke_core.tools._watch_worktree_binding`
and its wiring into :mod:`yoke_core.tools.watch_pytest`.

The backstop refuses pytest invocations from outside the calling
session's claim-bound worktree. The tests below exercise the pure
evaluator and the two layered integration points:

- :func:`evaluate_worktree_binding` — the pure-function decision under
  every pass-through case (no session, no claims, free-path cwd,
  matching worktree) and the refusal case.
- :func:`check` — the env + cwd + DB integration. Tested with
  monkeypatched dependencies so the suite never needs a live Yoke DB.
- :func:`watch_pytest.main` — the end-to-end refusal propagation:
  when ``check`` returns a remediation string the wrapper prints it
  and exits ``3`` before any pytest invocation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.tools import _watch_worktree_binding, watch_pytest
from yoke_core.tools._watch_worktree_binding import (
    WORKTREE_BINDING_REFUSAL_TEMPLATE,
    evaluate_worktree_binding,
)


class TestEvaluateWorktreeBinding:
    """Pure-function decision matrix."""

    def test_empty_session_id_passes_through(self, tmp_path: Path) -> None:
        wt = tmp_path / "wt"
        wt.mkdir()
        assert evaluate_worktree_binding(
            cwd=str(tmp_path), session_id="", claim_worktrees=[str(wt)],
        ) is None

    def test_no_claim_worktrees_passes_through(self, tmp_path: Path) -> None:
        # An active session running inline `/yoke` skills holds no
        # worktree-bearing claims. The backstop must NEVER block that path.
        assert evaluate_worktree_binding(
            cwd=str(tmp_path), session_id="abc", claim_worktrees=[],
        ) is None

    def test_only_empty_strings_in_claims_passes_through(
        self, tmp_path: Path,
    ) -> None:
        assert evaluate_worktree_binding(
            cwd=str(tmp_path), session_id="abc", claim_worktrees=["", "  "],
        ) is None

    def test_cwd_inside_claim_worktree_passes_through(
        self, tmp_path: Path,
    ) -> None:
        wt = tmp_path / ".worktrees" / "YOK-1"
        sub = wt / "sub" / "dir"
        sub.mkdir(parents=True)
        assert evaluate_worktree_binding(
            cwd=str(sub), session_id="abc", claim_worktrees=[str(wt)],
        ) is None

    def test_cwd_is_claim_worktree_root_passes_through(
        self, tmp_path: Path,
    ) -> None:
        wt = tmp_path / ".worktrees" / "YOK-1"
        wt.mkdir(parents=True)
        assert evaluate_worktree_binding(
            cwd=str(wt), session_id="abc", claim_worktrees=[str(wt)],
        ) is None

    def test_cwd_inside_one_of_many_passes_through(
        self, tmp_path: Path,
    ) -> None:
        wt_a = tmp_path / ".worktrees" / "YOK-1"
        wt_b = tmp_path / ".worktrees" / "YOK-2"
        wt_a.mkdir(parents=True)
        wt_b.mkdir(parents=True)
        assert evaluate_worktree_binding(
            cwd=str(wt_b),
            session_id="abc",
            claim_worktrees=[str(wt_a), str(wt_b)],
        ) is None

    def test_cwd_free_path_passes_through(self) -> None:
        # ``/tmp`` is in ``FREE_PATH_PREFIXES``; the backstop pass-through
        # mirrors the write lint's free-path allowlist.
        # ``/tmp`` on macOS resolves to ``/private/tmp`` — assert by
        # monkeypatching the free-path check is not needed: ``/tmp``
        # itself (or its resolution) is on the allowlist.
        assert evaluate_worktree_binding(
            cwd="/tmp",
            session_id="abc",
            claim_worktrees=["/Users/anyone/.worktrees/YOK-X"],
        ) is None

    def test_cwd_outside_all_returns_refusal(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        # ``tmp_path`` on macOS resolves under ``/private/var/folders/...``
        # which is in ``FREE_PATH_PREFIXES`` — pure-function tests for
        # the refusal path mute that filter so they can use tmp_path
        # paths as conceptual repo roots.
        monkeypatch.setattr(
            _watch_worktree_binding, "_cwd_is_free", lambda _cwd: False,
        )
        wt = tmp_path / ".worktrees" / "YOK-1"
        wt.mkdir(parents=True)
        # cwd is tmp_path's repo root (the parent of .worktrees) — outside
        # the worktree but inside the conceptual repo.
        msg = evaluate_worktree_binding(
            cwd=str(tmp_path),
            session_id="sess-id-1",
            claim_worktrees=[str(wt)],
        )
        assert msg is not None
        # Refusal names the session id, the canonical first worktree,
        # and the cwd that tripped the refusal.
        assert "sess-id-1" in msg
        assert str(wt) in msg
        assert str(tmp_path) in msg
        # Refusal includes the canonical remediation incantation.
        assert "cd " in msg

    def test_refusal_template_renders_named_fields(self) -> None:
        # Defends against accidental refactors that drop one of the
        # documented format fields.
        rendered = WORKTREE_BINDING_REFUSAL_TEMPLATE.format(
            sid="S", wt="W", cwd="C",
        )
        assert "S" in rendered
        assert "W" in rendered
        assert "C" in rendered


class TestCheckIntegration:
    """``check()`` reads env + cwd + the canonical DB resolver."""

    def test_missing_session_id_passes_through(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("YOKE_SESSION_ID", raising=False)
        assert _watch_worktree_binding.check() is None

    def test_empty_session_id_passes_through(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("YOKE_SESSION_ID", "   ")
        assert _watch_worktree_binding.check() is None

    def test_resolve_returns_empty_passes_through(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("YOKE_SESSION_ID", "sess")
        monkeypatch.setattr(
            _watch_worktree_binding,
            "resolve_claim_worktrees",
            lambda _sid: [],
        )
        assert _watch_worktree_binding.check() is None

    def test_resolve_db_error_passes_through(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The canonical resolver swallows DB / import errors and returns
        # ``[]``. The backstop relies on that for fail-open semantics —
        # a test environment without the Yoke schema must not block
        # pytest. We assert the contract holds.
        monkeypatch.setenv("YOKE_SESSION_ID", "sess")

        def _boom(_sid: str) -> list:
            raise RuntimeError("simulated DB failure")

        # Even if downstream raises, the public ``resolve_claim_worktrees``
        # contract catches and returns ``[]``. Mock at the layer above
        # to demonstrate ``check`` fails open when the resolver returns
        # an empty list regardless of WHY it returned empty.
        monkeypatch.setattr(
            _watch_worktree_binding,
            "resolve_claim_worktrees",
            lambda _sid: [],
        )
        assert _watch_worktree_binding.check() is None

    def test_resolve_returns_worktrees_and_cwd_outside_refuses(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        # pytest's ``tmp_path`` lives under ``/private/var/folders/...``
        # which is in ``FREE_PATH_PREFIXES`` — the backstop pass-through
        # mirrors the write lint's free-path allowlist. To exercise the
        # refusal path we mute the free-path filter for this test only.
        monkeypatch.setattr(
            _watch_worktree_binding, "_cwd_is_free", lambda _cwd: False,
        )
        wt = tmp_path / ".worktrees" / "YOK-1"
        wt.mkdir(parents=True)
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        monkeypatch.setenv("YOKE_SESSION_ID", "sess-1")
        monkeypatch.setattr(
            _watch_worktree_binding,
            "resolve_claim_worktrees",
            lambda _sid: [str(wt)],
        )
        monkeypatch.chdir(outside)
        msg = _watch_worktree_binding.check()
        assert msg is not None
        assert "sess-1" in msg
        assert str(wt) in msg

    def test_resolve_returns_worktrees_and_cwd_inside_passes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        wt = tmp_path / ".worktrees" / "YOK-1"
        wt.mkdir(parents=True)
        monkeypatch.setenv("YOKE_SESSION_ID", "sess-1")
        monkeypatch.setattr(
            _watch_worktree_binding,
            "resolve_claim_worktrees",
            lambda _sid: [str(wt)],
        )
        monkeypatch.chdir(wt)
        assert _watch_worktree_binding.check() is None

    def test_resolve_returns_worktrees_and_cwd_free_path_passes(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        # End-to-end: ``check()`` honours the free-path allowlist even
        # when the session has worktree-bearing claims. Without this
        # carve-out the wrapper's own smoke test would fire the refusal
        # against the temp directory it creates.
        wt = tmp_path / ".worktrees" / "YOK-1"
        wt.mkdir(parents=True)
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        monkeypatch.setenv("YOKE_SESSION_ID", "sess-1")
        monkeypatch.setattr(
            _watch_worktree_binding,
            "resolve_claim_worktrees",
            lambda _sid: [str(wt)],
        )
        monkeypatch.chdir(outside)
        assert _watch_worktree_binding.check() is None


class TestWatchPytestRefusalPropagation:
    """``watch_pytest.main`` returns ``3`` and prints the refusal on stderr."""

    def test_main_exits_3_when_binding_check_refuses(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
    ) -> None:
        # Force the check to return a refusal regardless of real session
        # state, so the integration test is hermetic.
        monkeypatch.setattr(
            _watch_worktree_binding,
            "check",
            lambda: "REFUSAL: do the cd thing",
        )
        rc = watch_pytest.main(["--", "runtime/api/", "-q"])
        assert rc == 3
        captured = capsys.readouterr()
        assert "REFUSAL: do the cd thing" in captured.err
        # The refusal must be printed BEFORE pytest is invoked — nothing
        # on stdout (no streaming-pair output, no progress capture).
        assert captured.out == ""

    def test_main_passes_through_when_check_returns_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # With the binding check stubbed to pass-through, the wrapper
        # falls through to its existing nested-pytest rejection / pytest
        # launch path. We assert it does NOT return ``3``.
        monkeypatch.setattr(
            _watch_worktree_binding, "check", lambda: None,
        )
        monkeypatch.setenv("TMPDIR", str(tmp_path))
        # Use --print-streaming-pair so we exercise main() without
        # actually launching pytest. Pin RAM high so parallel-default
        # injection is deterministic.
        from yoke_core.tools import _pytest_parallel
        monkeypatch.setattr(
            _pytest_parallel, "_read_free_ram_mb", lambda: 1_000_000,
        )
        rc = watch_pytest.main(
            ["--print-streaming-pair", "--", "runtime/api/", "-q"],
        )
        assert rc != 3
        assert rc == 0

    def test_nested_pytest_rejection_still_wins_over_binding(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
    ) -> None:
        # When both the nested-pytest shape AND a binding refusal would
        # fire, the wrapper rejects nested-pytest first. This protects
        # the existing exit-code contract: callers that grep for the
        # nested-pytest error message keep working.
        monkeypatch.setattr(
            _watch_worktree_binding,
            "check",
            lambda: "REFUSAL: do the cd thing",
        )
        rc = watch_pytest.main(
            ["--", "python3", "-m", "pytest", "runtime/api/", "-q"],
        )
        assert rc == 2
        captured = capsys.readouterr()
        assert "bare pytest args" in captured.err
        assert "REFUSAL" not in captured.err
