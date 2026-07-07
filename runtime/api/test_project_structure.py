"""Constitution invariants, schema init, and envelope validation for ``yoke_core.domain.project_structure``.

Family-specific tests (replacement rejection, command_definitions, write/read
round-trip, atomicity, stale-base-version) live in
``test_project_structure_families.py``. Seed recipe and CLI tests live in
``test_project_structure_seed_cli.py``.

Uses ``tmp_path`` so every test starts from a clean DB with no coupling
to the live ``yoke.db``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from yoke_core.domain import project_structure as ps
from yoke_core.domain.schema_common import _table_exists


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    """Return a fresh, isolated on-disk DB path."""
    return str(tmp_path / "test_project_structure.db")


@pytest.fixture
def initialized_db(db_path: str) -> str:
    """Return a db_path after ``cmd_init`` has created the tables."""
    ps.cmd_init(db_path=db_path)
    from yoke_core.domain.db_helpers import connect
    conn = connect(db_path)
    try:
        conn.execute(
            "INSERT INTO projects "
            "(id, slug, name, created_at) "
            "VALUES (10, 'test', 'Test', '2026-01-01') "
            "ON CONFLICT(id) DO NOTHING"
        )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _put(family, attachment, payload, *, entry_key="", attachment_kind=""):
    op = {"op": "put", "family": family, "attachment": attachment, "payload": payload}
    if entry_key:
        op["entry_key"] = entry_key
    if attachment_kind:
        op["attachment_kind"] = attachment_kind
    return op


# ---------------------------------------------------------------------------
# Constitution invariants (path registry constitution clauses)
# ---------------------------------------------------------------------------


class TestConstitutionInvariants:
    def test_net_new_families_exist(self):
        """All path-registry-frozen families are fully defined. With the
        ``context_routing`` cutover landed, every concretized family lives
        under :data:`NET_NEW_FAMILIES` and the replacement-slot machinery
        is gone."""
        expected = {
            "areas",
            "mappings",
            "test_roots",
            "verification_profiles",
            "ownership_defaults",
            "integration_targets",
            "command_definitions",
            "deploy_defaults",
            "merge_verification",
            "context_routing",
            "architecture_model",
        }
        assert set(ps.NET_NEW_FAMILIES) == expected

    def test_attachment_branches_are_closed(self):
        assert set(ps.ATTACHMENT_BRANCHES) == {"project", "path_selector"}

    def test_path_selector_kinds_are_closed(self):
        assert set(ps.PATH_SELECTOR_KINDS) == {"exact", "glob", "tree"}

    def test_multiplicities_are_closed(self):
        assert set(ps.MULTIPLICITIES) == {"singleton", "keyed_set"}

    def test_every_net_new_envelope_has_required_fields(self):
        for name, env in ps.NET_NEW_FAMILIES.items():
            assert env["attachment"] in ps.ATTACHMENT_BRANCHES, name
            assert env["multiplicity"] in ps.MULTIPLICITIES, name
            locked = env["locked_kind"]
            if locked is not None:
                assert locked in ps.PATH_SELECTOR_KINDS, name
                assert env["attachment"] == "path_selector", name


class TestSchemaInit:
    def test_creates_three_tables(self, db_path: str):
        ps.cmd_init(db_path=db_path)
        from yoke_core.domain.db_helpers import connect
        conn = connect(db_path)
        try:
            exists = _table_exists(conn, "project_structure")
        finally:
            conn.close()
        assert exists

    def test_init_is_idempotent(self, db_path: str):
        ps.cmd_init(db_path=db_path)
        ps.cmd_init(db_path=db_path)  # second call must not error


class TestEnvelopeValidation:
    def test_unknown_family_rejected(self, initialized_db: str):
        with pytest.raises(ps.ValidationError, match="Unknown family"):
            ps.apply_patch(
                "test",
                ops=[_put("not_a_family", "project", {"x": 1}, entry_key="y")],
                db_path=initialized_db,
            )

    def test_project_branch_requires_literal_token(self, initialized_db: str):
        """project-branch families must use attachment='project'."""
        with pytest.raises(ps.ValidationError, match="literal token 'project'"):
            ps.apply_patch(
                "test",
                ops=[_put("areas", "some/path", {"description": "x"}, entry_key="k")],
                db_path=initialized_db,
            )

    def test_path_selector_rejects_project_token(self, initialized_db: str):
        """path_selector families cannot use 'project' as attachment."""
        with pytest.raises(ps.ValidationError, match="non-empty path/glob/subtree"):
            ps.apply_patch(
                "test",
                ops=[_put("mappings", "project", {"area_name": "core"})],
                db_path=initialized_db,
            )

    def test_path_selector_requires_kind(self, initialized_db: str):
        """path_selector families must declare an attachment_kind in
        the closed PATH_SELECTOR_KINDS vocabulary. Locked families
        auto-fill from the caller's omission, so this test exercises
        the rejection of an explicit invalid value."""
        with pytest.raises(ps.ValidationError, match="attachment_kind must be one of"):
            ps.apply_patch(
                "test",
                ops=[_put(
                    "mappings",
                    "src/**",
                    {"area_name": "core"},
                    attachment_kind="weird",
                )],
                db_path=initialized_db,
            )

    def test_locked_kind_family_accepts_derived_kind(self, initialized_db: str):
        """test_roots is locked to 'tree' — attachment_kind may be omitted."""
        result = ps.apply_patch(
            "test",
            ops=[_put("test_roots", "tests/", {"purpose": "x"}, entry_key="root")],
            db_path=initialized_db,
        )
        structure = ps.read_structure("test", family="test_roots", db_path=initialized_db)
        assert structure["entries"][0]["attachment_kind"] == "tree"

    def test_locked_kind_family_rejects_wrong_kind(self, initialized_db: str):
        """test_roots is locked to 'tree'; 'exact' must be rejected."""
        with pytest.raises(ps.ValidationError, match="locked to attachment_kind 'tree'"):
            ps.apply_patch(
                "test",
                ops=[_put(
                    "test_roots",
                    "tests/file.py",
                    {"purpose": "x"},
                    entry_key="root",
                    attachment_kind="exact",
                )],
                db_path=initialized_db,
            )

    def test_keyed_set_requires_entry_key(self, initialized_db: str):
        """keyed_set families require non-empty entry_key."""
        with pytest.raises(ps.ValidationError, match="entry_key is required"):
            ps.apply_patch(
                "test",
                ops=[_put("areas", "project", {"description": "x"})],
                db_path=initialized_db,
            )

    def test_singleton_rejects_entry_key(self, initialized_db: str):
        """singleton families must not carry entry_key."""
        with pytest.raises(ps.ValidationError, match="singleton; entry_key must be omitted"):
            ps.apply_patch(
                "test",
                ops=[_put(
                    "ownership_defaults",
                    "runtime/",
                    {"owner": "core"},
                    entry_key="extra",
                )],
                db_path=initialized_db,
            )

    def test_mappings_requires_area_name(self, initialized_db: str):
        """mappings payload must carry area_name per constitution."""
        with pytest.raises(ps.ValidationError, match="area_name"):
            ps.apply_patch(
                "test",
                ops=[_put("mappings", "runtime/**", {"description": "x"})],
                db_path=initialized_db,
            )

    def test_payload_must_be_dict(self, initialized_db: str):
        with pytest.raises(ps.ValidationError, match="must be a JSON object"):
            ps.apply_patch(
                "test",
                ops=[{
                    "op": "put",
                    "family": "areas",
                    "attachment": "project",
                    "entry_key": "x",
                    "payload": "not a dict",
                }],
                db_path=initialized_db,
            )
