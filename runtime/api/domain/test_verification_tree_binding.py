"""Coverage for :mod:`yoke_core.domain.verification_tree_binding`.

The module answers two questions for every verification entry point:
may this run execute against this tree, and which tree did it execute
against. The tests below cover the pure decision matrix, the
session/claim integration (with monkeypatched dependencies so the suite
never needs a live Yoke DB), the override notice, and git tree identity
resolution against real temporary repositories.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from yoke_core.domain import verification_tree_binding
from yoke_core.domain.verification_tree_binding import (
    ALLOW_TREE_MISMATCH_FLAG,
    TREE_BINDING_REFUSAL_TEMPLATE,
    ClaimLookup,
    TreeIdentity,
    evaluate_tree_binding,
    resolve_tree_identity,
)

SURFACE = "test_surface"


def _no_free_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mute the free-path allowlist.

    ``tmp_path`` resolves under ``/private/var/folders/...`` on macOS,
    which is on the write lint's free-path allowlist — so refusal-path
    tests must opt out to use tmp paths as conceptual repo roots.
    """
    monkeypatch.setattr(
        verification_tree_binding, "_tree_is_free", lambda _tree: False,
    )


def _claimed_lane(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> tuple[Path, Path]:
    """A session holding one claimed lane, plus a tree outside it."""
    worktree = tmp_path / ".worktrees" / "lane"
    worktree.mkdir(parents=True)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    monkeypatch.setattr(
        verification_tree_binding, "ambient_session_id", lambda: "sess-1",
    )
    monkeypatch.setattr(
        verification_tree_binding,
        "resolve_claim_worktrees",
        lambda _sid: ClaimLookup(worktrees=(str(worktree),)),
    )
    return worktree, outside


class TestEvaluateTreeBinding:
    """Pure-function decision matrix."""

    def test_empty_session_id_passes_through(self, tmp_path: Path) -> None:
        worktree = tmp_path / "wt"
        worktree.mkdir()
        assert evaluate_tree_binding(
            str(tmp_path), "", [str(worktree)], surface=SURFACE,
        ) is None

    def test_no_claim_worktrees_passes_through(self, tmp_path: Path) -> None:
        # A session running inline `/yoke` skills, or main-checkout
        # source-dev work, holds no worktree-bearing claims. Neither may
        # ever be blocked.
        assert evaluate_tree_binding(
            str(tmp_path), "abc", [], surface=SURFACE,
        ) is None

    def test_only_blank_claims_passes_through(self, tmp_path: Path) -> None:
        assert evaluate_tree_binding(
            str(tmp_path), "abc", ["", "  "], surface=SURFACE,
        ) is None

    def test_tree_inside_claim_worktree_passes_through(
        self, tmp_path: Path,
    ) -> None:
        worktree = tmp_path / ".worktrees" / "lane"
        nested = worktree / "sub" / "dir"
        nested.mkdir(parents=True)
        assert evaluate_tree_binding(
            str(nested), "abc", [str(worktree)], surface=SURFACE,
        ) is None

    def test_tree_inside_one_of_many_passes_through(
        self, tmp_path: Path,
    ) -> None:
        first = tmp_path / ".worktrees" / "one"
        second = tmp_path / ".worktrees" / "two"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        # Also covers the claim-root case: the tree IS ``second``.
        assert evaluate_tree_binding(
            str(second), "abc", [str(first), str(second)], surface=SURFACE,
        ) is None

    def test_free_path_tree_passes_through(self) -> None:
        # ``/tmp`` is on ``FREE_PATH_PREFIXES``; the backstop mirrors the
        # write lint's allowlist rather than keeping its own.
        assert evaluate_tree_binding(
            "/tmp", "abc", ["/Users/anyone/.worktrees/lane"], surface=SURFACE,
        ) is None

    def test_tree_outside_all_returns_refusal(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        _no_free_paths(monkeypatch)
        worktree = tmp_path / ".worktrees" / "lane"
        worktree.mkdir(parents=True)
        message = evaluate_tree_binding(
            str(tmp_path), "sess-1", [str(worktree)], surface=SURFACE,
        )
        assert message is not None
        assert "sess-1" in message
        assert str(worktree) in message
        assert str(tmp_path) in message
        assert SURFACE in message
        # The refusal teaches both ways out: move to the claimed tree, or
        # declare the cross-tree run deliberate.
        assert 'cd "' in message
        assert ALLOW_TREE_MISMATCH_FLAG in message

    def test_refusal_template_renders_named_fields(self) -> None:
        # Defends against refactors that drop one of the format fields.
        rendered = TREE_BINDING_REFUSAL_TEMPLATE.format(
            surface="S", sid="I", wt="W", tree="T",
        )
        for token in ("S", "I", "W", "T"):
            assert token in rendered


class TestEvaluateRun:
    """``evaluate_run`` composes identity, claims, and the evaluator."""

    def test_missing_session_id_passes_through(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            verification_tree_binding, "ambient_session_id", lambda: "",
        )
        verdict = verification_tree_binding.evaluate_run(surface=SURFACE)
        assert verdict.refusal is None and verdict.notice is None

    def test_no_claims_passes_through(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            verification_tree_binding, "ambient_session_id", lambda: "sess",
        )
        monkeypatch.setattr(
            verification_tree_binding,
            "resolve_claim_worktrees",
            lambda _sid: ClaimLookup(),
        )
        verdict = verification_tree_binding.evaluate_run(surface=SURFACE)
        assert verdict.refusal is None and verdict.notice is None

    def test_explicit_tree_outside_claims_refuses(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        _no_free_paths(monkeypatch)
        worktree, outside = _claimed_lane(monkeypatch, tmp_path)
        verdict = verification_tree_binding.evaluate_run(
            surface=SURFACE, tree=str(outside),
        )
        assert verdict.refusal is not None
        assert str(outside) in verdict.refusal
        assert str(worktree) in verdict.refusal
        assert verdict.notice is None

    def test_cwd_is_the_default_tree(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        _no_free_paths(monkeypatch)
        worktree, outside = _claimed_lane(monkeypatch, tmp_path)
        monkeypatch.chdir(outside)
        assert verification_tree_binding.evaluate_run(
            surface=SURFACE,
        ).refusal is not None
        monkeypatch.chdir(worktree)
        assert verification_tree_binding.evaluate_run(
            surface=SURFACE,
        ).refusal is None

    def test_override_converts_the_refusal_to_a_notice(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        _no_free_paths(monkeypatch)
        worktree, outside = _claimed_lane(monkeypatch, tmp_path)
        verdict = verification_tree_binding.evaluate_run(
            surface=SURFACE, tree=str(outside), allow_mismatch=True,
        )
        assert verdict.refusal is None
        assert verdict.notice is not None
        assert str(outside) in verdict.notice
        assert str(worktree) in verdict.notice

    def test_override_on_a_bound_run_stays_silent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        # An override that changes nothing says nothing, so the notice
        # only ever appears when a cross-tree run really happened.
        worktree, _outside = _claimed_lane(monkeypatch, tmp_path)
        verdict = verification_tree_binding.evaluate_run(
            surface=SURFACE, tree=str(worktree), allow_mismatch=True,
        )
        assert verdict.refusal is None and verdict.notice is None

    def test_unreachable_lookup_proceeds_but_says_so(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        # The case that let this guard sit inert: an unreachable control
        # plane must not ground the run, but it must never look like a
        # clean verdict either.
        _no_free_paths(monkeypatch)
        monkeypatch.setattr(
            verification_tree_binding, "ambient_session_id", lambda: "sess-1",
        )
        monkeypatch.setattr(
            verification_tree_binding,
            "resolve_claim_worktrees",
            lambda _sid: ClaimLookup(reachable=False, detail="no route"),
        )
        verdict = verification_tree_binding.evaluate_run(
            surface=SURFACE, tree=str(tmp_path),
        )
        assert verdict.refusal is None
        assert verdict.notice is not None
        assert "no route" in verdict.notice
        assert str(tmp_path) in verdict.notice

    def test_ambient_identity_reads_the_canonical_chain(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # A harness that publishes identity only through the process
        # anchor registry must still be seen. Resolving through the
        # canonical chain is what makes the backstop live rather than
        # permanently dormant.
        from yoke_core.domain import session_ambient_identity

        monkeypatch.setattr(
            session_ambient_identity,
            "resolve_ambient_session_id",
            lambda env=None: "anchor-session",
        )
        assert verification_tree_binding.ambient_session_id() == "anchor-session"

    def test_ambient_identity_failure_is_not_fatal(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from yoke_core.domain import session_ambient_identity

        def _boom(env=None):
            raise RuntimeError("simulated resolver failure")

        monkeypatch.setattr(
            session_ambient_identity, "resolve_ambient_session_id", _boom,
        )
        assert verification_tree_binding.ambient_session_id() == ""


def _init_repo(root: Path) -> str:
    """Create a one-commit git repository at *root*, returning its HEAD."""
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "verification@example.test"],
        cwd=root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Verification"], cwd=root, check=True,
    )
    (root / "tracked.txt").write_text("content\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "initial"], cwd=root, check=True,
    )
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


class TestResolveTreeIdentity:
    """Naming the tree a run executed against."""

    def test_identity_names_root_and_head(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        head = _init_repo(repo)
        identity = resolve_tree_identity(repo)
        assert identity is not None
        assert Path(identity.root).resolve() == repo.resolve()
        assert identity.head_sha == head

    def test_identity_resolves_from_a_subdirectory(
        self, tmp_path: Path,
    ) -> None:
        repo = tmp_path / "repo"
        head = _init_repo(repo)
        nested = repo / "packages" / "inner"
        nested.mkdir(parents=True)
        identity = resolve_tree_identity(nested)
        assert identity is not None
        # The root is the worktree, not the directory the caller stood in.
        assert Path(identity.root).resolve() == repo.resolve()
        assert identity.head_sha == head

    def test_two_trees_report_distinct_identities(
        self, tmp_path: Path,
    ) -> None:
        # The property the evidence record depends on: a run in the wrong
        # tree cannot record the same identity as a run in the right one.
        first = tmp_path / "first"
        second = tmp_path / "second"
        _init_repo(first)
        _init_repo(second)
        left = resolve_tree_identity(first)
        right = resolve_tree_identity(second)
        assert left is not None and right is not None
        assert left.root != right.root

    def test_missing_directory_returns_none(self, tmp_path: Path) -> None:
        assert resolve_tree_identity(tmp_path / "absent") is None

    def test_payload_shape(self) -> None:
        identity = TreeIdentity(root="/repo", head_sha="abc1234")
        assert identity.as_payload() == {
            "root": "/repo", "head_sha": "abc1234",
        }
