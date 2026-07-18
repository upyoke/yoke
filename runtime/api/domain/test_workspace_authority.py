# ruff: noqa: F401, F811
"""Regression coverage for ``workspace_authority``: matching-claim /
mismatched-target / no-worktree-claims / no-claims / free-path /
multi-claim / explicit-session-id / DB-unavailable resolution branches
+ seed-source coupling checks. Synthetic ``/opt/...`` paths avoid the
``/var/folders`` free-path allowlist that authorises pytest's ``tmp_path``
on macOS."""
from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.workspace_authority import (
    SESSION_ID_ENV_VAR,
    assert_seed_source_under_target_root,
    assert_target_under_session_work_authority,
)
from yoke_core.domain.workspace_authority_test_helpers import (
    SESSION_A,
    SESSION_B,
    _seed_claim,
    _seed_item,
    _seed_project,
    conn,
    patch_conn,
)


def test_matching_worktree_claim_passes(
    patch_conn, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_A)
    _seed_project(patch_conn, "/opt/yoke-test")
    _seed_item(patch_conn, item_id=42, branch="YOK-42")
    _seed_claim(patch_conn, SESSION_A, item_id=42)
    target = Path("/opt/yoke-test/.worktrees/YOK-42/runtime/x.py")
    assert_target_under_session_work_authority(target)


def test_main_cwd_target_with_worktree_claim_refuses(
    patch_conn, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_A)
    _seed_project(patch_conn, "/opt/yoke-test")
    _seed_item(patch_conn, item_id=42, branch="YOK-42")
    _seed_claim(patch_conn, SESSION_A, item_id=42)
    target = Path("/opt/yoke-test/runtime/x.py")
    with pytest.raises(RuntimeError) as exc:
        assert_target_under_session_work_authority(target)
    msg = str(exc.value)
    assert "refusing write" in msg
    assert SESSION_A in msg
    assert "/opt/yoke-test/.worktrees/YOK-42" in msg
    assert "/opt/yoke-test/runtime/x.py" in msg


def test_session_with_only_no_worktree_claims_is_no_op(
    patch_conn, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Item-without-worktree-branch claims contribute no row.

    ``claimed_worktrees`` deliberately filters items without a worktree
    branch (idea/refine-phase items). Without worktree claims the helper
    has no authority signal to enforce — fall through to no-op (same
    posture the per-tool-call lint takes for sessions with no claims).
    Authority for pre-implementation lifecycles is enforced by
    ``lint_session_cwd_pre_implementing``, not by this writer guard.
    """
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_A)
    _seed_project(patch_conn, "/opt/yoke-test")
    _seed_item(patch_conn, item_id=42, branch=None)
    _seed_claim(patch_conn, SESSION_A, item_id=42)
    assert_target_under_session_work_authority(
        Path("/opt/yoke-test/docs/atlas.md")
    )
    assert_target_under_session_work_authority(Path("/opt/other-repo/x.py"))


def test_env_var_unset_is_no_op(
    patch_conn, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``$YOKE_SESSION_ID`` → operator/maintenance mode, no-op."""
    monkeypatch.delenv(SESSION_ID_ENV_VAR, raising=False)
    _seed_project(patch_conn, "/opt/yoke-test")
    _seed_item(patch_conn, item_id=42, branch="YOK-42")
    _seed_claim(patch_conn, SESSION_A, item_id=42)
    target = Path("/opt/yoke-test/runtime/x.py")
    assert_target_under_session_work_authority(target)


def test_session_with_no_claims_passes(
    patch_conn, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Orchestrator session shape — no claims, no enforcement."""
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_B)
    _seed_project(patch_conn, "/opt/yoke-test")
    _seed_item(patch_conn, item_id=42, branch="YOK-42")
    _seed_claim(patch_conn, SESSION_A, item_id=42)
    target = Path("/opt/yoke-test/runtime/x.py")
    assert_target_under_session_work_authority(target)


def test_free_path_allowlist_passes(
    patch_conn, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_A)
    _seed_project(patch_conn, "/opt/yoke-test")
    _seed_item(patch_conn, item_id=42, branch="YOK-42")
    _seed_claim(patch_conn, SESSION_A, item_id=42)
    assert_target_under_session_work_authority(Path("/tmp/scratch.txt"))


def test_multiple_active_claims_first_covering_match_passes(
    patch_conn, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_A)
    _seed_project(patch_conn, "/opt/yoke-test")
    _seed_item(patch_conn, item_id=42, branch="YOK-42")
    _seed_item(patch_conn, item_id=43, branch="YOK-43")
    _seed_claim(patch_conn, SESSION_A, item_id=42)
    _seed_claim(patch_conn, SESSION_A, item_id=43)
    assert_target_under_session_work_authority(
        Path("/opt/yoke-test/.worktrees/YOK-42/x.py")
    )
    assert_target_under_session_work_authority(
        Path("/opt/yoke-test/.worktrees/YOK-43/x.py")
    )
    with pytest.raises(RuntimeError):
        assert_target_under_session_work_authority(
            Path("/opt/yoke-test/runtime/x.py")
        )


def test_explicit_session_id_overrides_env(
    patch_conn, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_A)
    _seed_project(patch_conn, "/opt/yoke-test")
    _seed_item(patch_conn, item_id=42, branch="YOK-42")
    _seed_claim(patch_conn, SESSION_B, item_id=42)
    target = Path("/opt/yoke-test/runtime/x.py")
    assert_target_under_session_work_authority(target, session_id=SESSION_A)
    with pytest.raises(RuntimeError):
        assert_target_under_session_work_authority(target, session_id=SESSION_B)


def test_db_unavailable_fails_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """DB lookup failure must not block the writer — fall open."""
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_A)
    from yoke_core.domain import db_helpers

    def _raise(*a, **k):
        raise RuntimeError("connect failed")

    monkeypatch.setattr(db_helpers, "connect", _raise)
    assert_target_under_session_work_authority(Path("/opt/anywhere"))


def test_seed_source_under_target_root_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_A)
    target_root = tmp_path / "target"
    target_root.mkdir()
    seed = target_root / "runtime" / "api" / "domain" / "fake_seed.py"
    seed.parent.mkdir(parents=True)
    seed.write_text("# fake\n")
    assert_seed_source_under_target_root(
        str(seed), target_root, seed_module_name="fake_seed",
    )


def test_seed_source_outside_target_root_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use a synthetic non-tmp target_root so the free-path skip doesn't apply."""
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_A)
    target_root = Path("/opt/synthetic-target")
    seed = tmp_path / "other" / "fake_seed.py"
    seed.parent.mkdir(parents=True)
    seed.write_text("# fake\n")
    with pytest.raises(RuntimeError) as exc:
        assert_seed_source_under_target_root(
            str(seed), target_root, seed_module_name="fake_seed",
        )
    assert "seed loaded from" in str(exc.value)
    assert "fake_seed" in str(exc.value)


def test_seed_source_under_target_root_passes_with_synthetic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When target_root is a free path, seed mismatch is no-op (test posture)."""
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_A)
    target_root = tmp_path / "target"
    target_root.mkdir()
    seed_outside = tmp_path / "other" / "fake_seed.py"
    seed_outside.parent.mkdir(parents=True)
    seed_outside.write_text("# fake\n")
    assert_seed_source_under_target_root(
        str(seed_outside), target_root, seed_module_name="fake_seed",
    )


def test_seed_source_check_handles_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A built-in/dynamic module with no __file__ is a no-op."""
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_A)
    target_root = tmp_path / "target"
    target_root.mkdir()
    assert_seed_source_under_target_root(
        None, target_root, seed_module_name="dynamic",
    )


def test_seed_source_check_no_op_without_session_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test fixtures with no $YOKE_SESSION_ID skip the seed check."""
    monkeypatch.delenv(SESSION_ID_ENV_VAR, raising=False)
    target_root = tmp_path / "target"
    target_root.mkdir()
    other_root = tmp_path / "other"
    other_root.mkdir()
    seed = other_root / "runtime" / "api" / "domain" / "fake_seed.py"
    seed.parent.mkdir(parents=True)
    seed.write_text("# fake\n")
    assert_seed_source_under_target_root(
        str(seed), target_root, seed_module_name="fake_seed",
    )


YOKE_CORE_SOURCE_SEED_REL = Path(
    "packages/yoke-core/src/yoke_core/domain/schema.py"
)
SITE_PACKAGES_SEED_REL = Path(
    "lib/python3.12/site-packages/yoke_core/domain/schema.py"
)


def test_seed_source_external_project_target_is_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An external project target (no Yoke source under it — e.g. board
    rebuild for ExternalWebapp over the installed CLI) legitimately loads the seed
    from the CLI's Yoke source checkout. Not a worktree-dev hazard."""
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_A)
    monkeypatch.setattr(
        "yoke_core.domain.workspace_authority._is_free_path",
        lambda p: False,
    )
    cli_seed = tmp_path / "yoke-main" / YOKE_CORE_SOURCE_SEED_REL
    cli_seed.parent.mkdir(parents=True)
    cli_seed.write_text("# seed\n")
    external_target = tmp_path / "externalwebapp"  # no yoke_core source tree under it
    external_target.mkdir()
    assert_seed_source_under_target_root(
        str(cli_seed), external_target, seed_module_name="schema",
    )


def test_seed_source_from_site_packages_external_target_is_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wheel-installed CLI loads the seed from site-packages; an external
    project target carries no copy, so the write is allowed."""
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_A)
    monkeypatch.setattr(
        "yoke_core.domain.workspace_authority._is_free_path",
        lambda p: False,
    )
    cli_seed = tmp_path / "cli-venv" / SITE_PACKAGES_SEED_REL
    cli_seed.parent.mkdir(parents=True)
    cli_seed.write_text("# seed\n")
    external_target = tmp_path / "externalwebapp"
    external_target.mkdir()
    assert_seed_source_under_target_root(
        str(cli_seed), external_target, seed_module_name="schema",
    )


def test_seed_source_yoke_checkout_target_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The worktree-dev hazard still refuses: target_root IS a Yoke
    checkout (carries its own copy of the seed module) but the seed
    loaded from a different tree."""
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_A)
    monkeypatch.setattr(
        "yoke_core.domain.workspace_authority._is_free_path",
        lambda p: False,
    )
    main_seed = tmp_path / "main" / YOKE_CORE_SOURCE_SEED_REL
    main_seed.parent.mkdir(parents=True)
    main_seed.write_text("# main seed\n")
    worktree = tmp_path / "worktree"
    wt_seed = worktree / YOKE_CORE_SOURCE_SEED_REL
    wt_seed.parent.mkdir(parents=True)
    wt_seed.write_text("# wt\n")
    with pytest.raises(RuntimeError) as exc:
        assert_seed_source_under_target_root(
            str(main_seed), worktree, seed_module_name="schema",
        )
    assert "seed-source mismatch" in str(exc.value)


def test_seed_source_from_site_packages_yoke_checkout_target_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wheel-installed seed targeting a Yoke checkout that carries its
    own copy of the module is the same wrong-tree hazard."""
    monkeypatch.setenv(SESSION_ID_ENV_VAR, SESSION_A)
    monkeypatch.setattr(
        "yoke_core.domain.workspace_authority._is_free_path",
        lambda p: False,
    )
    installed_seed = tmp_path / "cli-venv" / SITE_PACKAGES_SEED_REL
    installed_seed.parent.mkdir(parents=True)
    installed_seed.write_text("# installed seed\n")
    checkout = tmp_path / "yoke-checkout"
    checkout_seed = checkout / YOKE_CORE_SOURCE_SEED_REL
    checkout_seed.parent.mkdir(parents=True)
    checkout_seed.write_text("# checkout\n")
    with pytest.raises(RuntimeError) as exc:
        assert_seed_source_under_target_root(
            str(installed_seed), checkout, seed_module_name="schema",
        )
    assert "seed-source mismatch" in str(exc.value)
