"""Tests for the sanctioned cross-worktree --module-path-override contract."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

import pytest

from yoke_core.domain.migration_apply import live_apply, rehearse
from yoke_core.domain.migration_apply_audit import (
    DESCRIPTION_BASE, assert_live_apply_override_consistent,
    describe_override, parse_override_description,
)
from yoke_core.domain.migration_apply_contract import (
    ModuleOverrideError, STATE_COMPLETED, STATE_REHEARSED,
)
from yoke_core.domain.migration_apply_resolve import (
    ModuleOverrideResolution, resolve_module_override,
)
from yoke_core.domain.migration_apply_test_helpers import (  # noqa: F401 — fixtures
    _audit_row, _seed_apply_item, apply_env,
)
from runtime.api.test_backlog import _conn, tmp_db  # noqa: F401 — reused fixtures


_OVERRIDE_BODY = '''"""Override migration body sourced from active feature worktree."""
from yoke_core.domain.schema_common import _table_exists

def apply(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS widgets (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
def invariants(conn):
    assert _table_exists(conn, "widgets"), "widgets table missing after apply"
'''


@pytest.fixture
def feature_worktree(tmp_path: Path) -> Dict[str, Path]:
    """Stand-in feature worktree with a declared migration module file."""
    feature = tmp_path / "feature-worktree"
    modules_dir = feature / "runtime" / "api" / "domain" / "migrations"
    modules_dir.mkdir(parents=True, exist_ok=True)
    module_path = modules_dir / "sample_migration.py"
    module_path.write_text(_OVERRIDE_BODY, encoding="utf-8")
    return {"worktree": feature, "module_path": module_path}


def _resolve(
    *, requested: Path, item_id: int, worktree: Path,
    declared=("sample_migration",),
) -> ModuleOverrideResolution:
    return resolve_module_override(
        requested_path=str(requested),
        item_id=item_id,
        declared_modules=declared,
        worktree_path=str(worktree.resolve()),
    )


# AC-1/AC-2/AC-7/AC-8 — resolver happy path & denied shapes ---------------


def test_resolver_accepts_declared_slug_under_worktree(feature_worktree) -> None:
    resolution = _resolve(
        requested=feature_worktree["module_path"],
        item_id=42,
        worktree=feature_worktree["worktree"],
    )
    assert resolution.slug == "sample_migration"
    assert resolution.module_path == feature_worktree["module_path"].resolve()
    assert resolution.worktree_path == feature_worktree["worktree"].resolve()
    assert resolution.item_id == 42


def test_empty_path_refused(feature_worktree) -> None:
    with pytest.raises(ModuleOverrideError, match="non-empty"):
        resolve_module_override(
            requested_path="", item_id=42,
            declared_modules=("sample_migration",),
            worktree_path=str(feature_worktree["worktree"].resolve()),
        )


def test_missing_on_disk_refused(feature_worktree) -> None:
    ghost = feature_worktree["worktree"] / "ghost.py"
    with pytest.raises(ModuleOverrideError, match="does not exist"):
        _resolve(requested=ghost, item_id=42,
                 worktree=feature_worktree["worktree"])


def test_directory_refused(feature_worktree) -> None:
    with pytest.raises(ModuleOverrideError, match="not a regular file"):
        _resolve(
            requested=feature_worktree["module_path"].parent,
            item_id=42, worktree=feature_worktree["worktree"],
        )


def test_outside_worktree_refused(feature_worktree, tmp_path) -> None:
    outside = tmp_path / "elsewhere" / "sample_migration.py"
    outside.parent.mkdir(parents=True)
    outside.write_text(_OVERRIDE_BODY, encoding="utf-8")
    with pytest.raises(
        ModuleOverrideError, match="not under the active item worktree",
    ):
        _resolve(requested=outside, item_id=42,
                 worktree=feature_worktree["worktree"])


def test_symlink_escape_refused(feature_worktree, tmp_path) -> None:
    outside = tmp_path / "outside.py"
    outside.write_text(_OVERRIDE_BODY, encoding="utf-8")
    link = feature_worktree["module_path"].parent / "linked.py"
    os.symlink(str(outside), str(link))
    with pytest.raises(ModuleOverrideError, match="symlink escape"):
        _resolve(requested=link, item_id=42,
                 worktree=feature_worktree["worktree"])


def test_non_py_basename_refused(feature_worktree) -> None:
    wrong = feature_worktree["module_path"].parent / "sample_migration.txt"
    wrong.write_text("nope", encoding="utf-8")
    with pytest.raises(ModuleOverrideError, match=r"<declared_slug>\.py"):
        _resolve(requested=wrong, item_id=42,
                 worktree=feature_worktree["worktree"])


def test_undeclared_slug_refused(feature_worktree) -> None:
    rogue = feature_worktree["module_path"].parent / "rogue_migration.py"
    rogue.write_text(_OVERRIDE_BODY, encoding="utf-8")
    with pytest.raises(ModuleOverrideError, match="not declared"):
        _resolve(requested=rogue, item_id=42,
                 worktree=feature_worktree["worktree"])


def test_missing_worktree_path_refused(feature_worktree) -> None:
    # Caller forgot to pass worktree_path — under the new contract the
    # validator has no fall-back; refusal is structural.
    with pytest.raises(ModuleOverrideError, match="active item worktree"):
        resolve_module_override(
            requested_path=str(feature_worktree["module_path"]),
            item_id=42, declared_modules=("sample_migration",),
        )


def test_empty_worktree_path_refused(feature_worktree) -> None:
    with pytest.raises(ModuleOverrideError, match="active item worktree"):
        resolve_module_override(
            requested_path=str(feature_worktree["module_path"]),
            item_id=42, declared_modules=("sample_migration",),
            worktree_path="",
        )


# AC-4/AC-10 — audit description marker round trip ----------------------


def test_describe_then_parse_roundtrips(feature_worktree) -> None:
    resolution = _resolve(
        requested=feature_worktree["module_path"], item_id=42,
        worktree=feature_worktree["worktree"],
    )
    description = describe_override(resolution)
    parsed = parse_override_description(description)
    assert parsed is not None
    assert parsed["source_path"] == str(resolution.source_path)
    assert parsed["worktree_path"] == str(resolution.worktree_path)
    assert description.startswith(DESCRIPTION_BASE)


def test_parse_returns_none_when_no_marker() -> None:
    assert parse_override_description(None) is None
    assert parse_override_description("") is None
    assert parse_override_description(DESCRIPTION_BASE) is None


# AC-7/AC-9 — rehearse + live-apply share override; live refuses on mismatch


def test_rehearse_then_live_apply_via_override_records_evidence(
    apply_env, feature_worktree,
) -> None:
    _seed_apply_item(apply_env["control_db"], item_id=6001)
    resolution = _resolve(
        requested=feature_worktree["module_path"], item_id=6001,
        worktree=feature_worktree["worktree"],
    )
    rehearse_result = rehearse(
        6001, session_id="cross-worktree-test",
        control_db_path=apply_env["control_db"],
        worktree_path=apply_env["worktree"], module_override=resolution,
    )
    assert rehearse_result.all_succeeded
    attempt = rehearse_result.modules[0]
    assert attempt.state == STATE_REHEARSED
    assert attempt.detail["override_source"] == str(resolution.source_path)
    assert attempt.detail["override_worktree"] == str(resolution.worktree_path)

    row = _audit_row(apply_env["authoritative_db"], attempt.audit_id)
    assert row is not None
    assert row["description"] == describe_override(resolution)

    live_result = live_apply(
        6001, session_id="cross-worktree-test",
        control_db_path=apply_env["control_db"],
        worktree_path=apply_env["worktree"], module_override=resolution,
    )
    assert live_result.all_succeeded
    assert live_result.modules[0].state == STATE_COMPLETED


def test_live_apply_without_override_after_override_rehearse_refuses(
    apply_env, feature_worktree,
) -> None:
    _seed_apply_item(apply_env["control_db"], item_id=6002)
    resolution = _resolve(
        requested=feature_worktree["module_path"], item_id=6002,
        worktree=feature_worktree["worktree"],
    )
    rehearse(
        6002, session_id="t", control_db_path=apply_env["control_db"],
        worktree_path=apply_env["worktree"], module_override=resolution,
    )
    with pytest.raises(ModuleOverrideError, match="must pass the same"):
        live_apply(
            6002, session_id="t",
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"], module_override=None,
        )


def test_live_apply_with_override_after_default_rehearse_refuses(
    apply_env, feature_worktree,
) -> None:
    _seed_apply_item(apply_env["control_db"], item_id=6003)
    rehearse(
        6003, session_id="t", control_db_path=apply_env["control_db"],
        worktree_path=apply_env["worktree"],
    )
    resolution = _resolve(
        requested=feature_worktree["module_path"], item_id=6003,
        worktree=feature_worktree["worktree"],
    )
    with pytest.raises(
        ModuleOverrideError, match="rehearsed audit row has no override marker",
    ):
        live_apply(
            6003, session_id="t",
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"], module_override=resolution,
        )


def test_live_apply_with_mismatched_override_refuses(
    apply_env, feature_worktree, tmp_path,
) -> None:
    _seed_apply_item(apply_env["control_db"], item_id=6004)
    first = _resolve(
        requested=feature_worktree["module_path"], item_id=6004,
        worktree=feature_worktree["worktree"],
    )
    rehearse(
        6004, session_id="t", control_db_path=apply_env["control_db"],
        worktree_path=apply_env["worktree"], module_override=first,
    )
    second_root = tmp_path / "feature-two"
    second_modules = second_root / "runtime" / "api" / "domain" / "migrations"
    second_modules.mkdir(parents=True)
    second_path = second_modules / "sample_migration.py"
    second_path.write_text(_OVERRIDE_BODY, encoding="utf-8")
    second = _resolve(
        requested=second_path, item_id=6004, worktree=second_root,
    )
    with pytest.raises(ModuleOverrideError, match="does not match rehearsed"):
        live_apply(
            6004, session_id="t",
            control_db_path=apply_env["control_db"],
            worktree_path=apply_env["worktree"], module_override=second,
        )


# AC-9 helper — direct exercise of the consistency check ----------------


def test_consistency_silent_when_neither_side_used_override() -> None:
    assert_live_apply_override_consistent(
        identifier="sample_migration",
        audit_description=DESCRIPTION_BASE, override=None,
    )


def test_consistency_raises_when_only_override_provided(feature_worktree) -> None:
    resolution = _resolve(
        requested=feature_worktree["module_path"], item_id=42,
        worktree=feature_worktree["worktree"])
    with pytest.raises(ModuleOverrideError, match="rehearsed audit row has no override"):
        assert_live_apply_override_consistent(
            identifier="sample_migration",
            audit_description=DESCRIPTION_BASE, override=resolution)


def test_consistency_raises_when_only_audit_marker_present(feature_worktree) -> None:
    resolution = _resolve(
        requested=feature_worktree["module_path"], item_id=42,
        worktree=feature_worktree["worktree"])
    with pytest.raises(ModuleOverrideError, match="must pass the same"):
        assert_live_apply_override_consistent(
            identifier="sample_migration",
            audit_description=describe_override(resolution),
            override=None)


def test_consistency_silent_when_slug_differs(feature_worktree) -> None:
    # Override with non-matching slug is a no-op for sibling modules.
    resolution = _resolve(
        requested=feature_worktree["module_path"], item_id=42,
        worktree=feature_worktree["worktree"])
    assert_live_apply_override_consistent(
        identifier="other_slug",
        audit_description=DESCRIPTION_BASE, override=resolution)
