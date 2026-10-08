"""Every glyph writer holds its value to the glyph contract before storage.

Project emoji, workflow stage glyphs, and level glyphs all render inside the
board's fixed-width columns, so each writer refuses a glyph the contract
refuses — naming the field and the offending code point — and stores a safe
one unchanged.
"""

from __future__ import annotations

from copy import deepcopy

import pytest

from yoke_contracts.levels import default_levels, levels_payload

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_schema
from yoke_contracts.glyph_contract import SAFE_GLYPH_EXAMPLES
from yoke_core.domain import db_backend
from yoke_core.domain.builtin_workflow_definitions import builtin_workflow_definition
from yoke_core.domain.projects_upsert import cmd_upsert
from yoke_core.domain.session_routing_validation import (
    validate_session_routing_settings,
)
from yoke_core.domain.workflow_definition_validation import (
    WorkflowDefinitionError,
    validate_workflow_definition,
)

_SAFE = "\U0001f680"
_UNSAFE = "\U0001f3d7️"  # building construction + VS16


@pytest.fixture
def project_db(monkeypatch):
    db_name = pg_testdb.create_test_database()
    try:
        conn = pg_testdb.connect_test_database(db_name)
        try:
            apply_fixture_schema(conn)
            conn.commit()
        finally:
            conn.close()
        monkeypatch.setenv(
            db_backend.PG_DSN_ENV,
            pg_testdb.dsn_for_test_database(db_name),
        )
        yield db_name
    finally:
        pg_testdb.drop_test_database(db_name)


class TestProjectEmoji:
    def test_create_refuses_an_unsafe_emoji_by_name(self, project_db) -> None:
        with pytest.raises(ValueError) as caught:
            cmd_upsert(
                slug="glyphs",
                name="Glyphs",
                public_item_prefix="GLY",
                emoji=_UNSAFE,
                mode="create",
            )
        message = str(caught.value)
        assert message.startswith("emoji ")
        assert "U+FE0F" in message
        assert SAFE_GLYPH_EXAMPLES[0] in message

    def test_create_and_update_store_a_safe_emoji(self, project_db) -> None:
        created = cmd_upsert(
            slug="glyphs",
            name="Glyphs",
            public_item_prefix="GLY",
            emoji=_SAFE,
            mode="create",
        )
        assert created["project"]["emoji"] == _SAFE
        updated = cmd_upsert(
            slug="glyphs",
            name="Glyphs",
            emoji="\U0001f40e",
            mode="update",
        )
        assert updated["project"]["emoji"] == "\U0001f40e"

    def test_update_refuses_an_unsafe_emoji(self, project_db) -> None:
        cmd_upsert(
            slug="glyphs",
            name="Glyphs",
            public_item_prefix="GLY",
            emoji=_SAFE,
            mode="create",
        )
        with pytest.raises(ValueError, match="skin-tone modifier"):
            cmd_upsert(
                slug="glyphs",
                name="Glyphs",
                emoji="\U0001f44d\U0001f3fb",
                mode="update",
            )

    def test_an_empty_emoji_clears_rather_than_refuses(self, project_db) -> None:
        cmd_upsert(
            slug="glyphs",
            name="Glyphs",
            public_item_prefix="GLY",
            emoji=_SAFE,
            mode="create",
        )
        updated = cmd_upsert(slug="glyphs", name="Glyphs", emoji="", mode="update")
        assert updated["project"]["emoji"] in ("", None)


class TestWorkflowStageGlyph:
    def _definition(self, glyph: str) -> dict:
        definition = deepcopy(builtin_workflow_definition("dash")["definition"])
        definition["stages"][0]["glyph"] = glyph
        return definition

    def test_an_unsafe_stage_glyph_is_refused_by_path(self) -> None:
        with pytest.raises(WorkflowDefinitionError) as caught:
            validate_workflow_definition(self._definition("▫"))
        message = str(caught.value)
        assert message.startswith("stages[0].glyph ")
        assert "text-default symbol" in message

    def test_a_safe_stage_glyph_validates(self) -> None:
        validate_workflow_definition(self._definition(_SAFE))


class TestLevelGlyph:
    def _settings(self, glyph: str) -> dict:
        levels = levels_payload(default_levels()[:1])
        levels[0]["glyph"] = glyph
        return {"levels": levels}

    def test_an_unsafe_level_glyph_is_refused(self) -> None:
        with pytest.raises(ValueError, match=r"levels\[0\]\.glyph"):
            validate_session_routing_settings(self._settings(_UNSAFE))

    def test_a_safe_level_glyph_validates(self) -> None:
        validate_session_routing_settings(self._settings(_SAFE))
