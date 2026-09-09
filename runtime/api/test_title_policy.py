"""One title limit, resolved per project, obeyed by every surface.

The point of these tests is propagation: each one moves the shared default
to a value nothing else in the tree carries, then asserts the surface under
test moved with it. A surface that kept its own number would pass at the
shipped value and fail here, which is exactly the regression the policy
exists to prevent.
"""

from __future__ import annotations

import pytest

from yoke_contracts import title_policy as policy
from yoke_contracts.title_policy import (
    DEFAULT_TITLE_MAX_LENGTH,
    title_length_error,
    title_max_length,
)

from yoke_core.domain import epic
from yoke_core.domain.mutation_fields import ItemState, validate_title
from yoke_core.domain.mutations import prepare_create, prepare_update
from yoke_core.domain.title_policy import item_project
from yoke_core.domain.workflow_runtime import builtin_workflow_runtime

from runtime.api.conftest import insert_item

#: A limit no shipped surface carries, so any survivor of the old literal
#: shows up as a failure rather than an accidental pass.
ALTERNATE_LIMIT = 17


@pytest.fixture()
def alternate_limit(monkeypatch):
    """Move the one default every resolver reads, for one test."""
    monkeypatch.setattr(policy, "DEFAULT_TITLE_MAX_LENGTH", ALTERNATE_LIMIT)
    return ALTERNATE_LIMIT


class TestSharedDefault:
    def test_shipped_value_is_unchanged(self):
        assert DEFAULT_TITLE_MAX_LENGTH == 100
        assert title_max_length() == 100

    def test_every_project_resolves_to_the_default(self):
        for project in (None, "yoke", 1, "some-other-project"):
            assert title_max_length(project) == DEFAULT_TITLE_MAX_LENGTH

    def test_resolver_follows_the_default(self, alternate_limit):
        assert title_max_length() == alternate_limit
        assert title_max_length("yoke") == alternate_limit


class TestLengthErrorSemantics:
    def test_at_the_limit_fits(self):
        assert title_length_error("x" * title_max_length()) is None

    def test_one_past_the_limit_names_both_numbers(self):
        over = title_max_length() + 1
        err = title_length_error("x" * over)
        assert err is not None
        assert str(title_max_length()) in err
        assert str(over) in err

    def test_subject_names_what_is_being_titled(self):
        err = title_length_error(
            "x" * (title_max_length() + 1), subject="Epic task title"
        )
        assert err is not None
        assert err.startswith("Epic task title exceeds")

    def test_counting_is_by_character_not_byte(self):
        """A title of N astral characters is N long, not its UTF-8 width."""
        title = "🌍" * title_max_length()
        assert len(title.encode("utf-8")) > title_max_length()
        assert title_length_error(title) is None
        assert title_length_error(title + "🌍") is not None

    def test_combining_marks_count_as_written(self):
        """Each code point counts once, so the count matches ``length()``."""
        title = "é" * title_max_length()
        assert title_length_error(title) is None


class TestItemValidationFollowsThePolicy:
    def test_validate_title_follows_the_default(self, alternate_limit):
        assert validate_title("x" * alternate_limit) is None
        err = validate_title("x" * (alternate_limit + 1))
        assert err is not None
        assert str(alternate_limit) in err

    def test_create_follows_the_default(self, alternate_limit):
        workflow = builtin_workflow_runtime("issue")
        assert (
            prepare_create(title="x" * alternate_limit, workflow=workflow).success
            is True
        )
        refused = prepare_create(title="x" * (alternate_limit + 1), workflow=workflow)
        assert refused.success is False
        assert refused.error_code == "VALIDATION_ERROR"

    def test_update_resolves_against_the_items_own_project(self, alternate_limit):
        item = ItemState(
            id=1,
            title="Original",
            status="idea",
            priority="medium",
            project="yoke",
            workflow=builtin_workflow_runtime("issue"),
        )
        assert (
            prepare_update(
                item=item, field_name="title", value="x" * alternate_limit
            ).success
            is True
        )
        assert (
            prepare_update(
                item=item, field_name="title", value="x" * (alternate_limit + 1)
            ).success
            is False
        )


class TestEpicTaskTitlesFollowThePolicy:
    """Both epic-task write paths resolve the parent item's project."""

    @pytest.fixture()
    def epic_db(self, test_db):
        insert_item(test_db, id=42, title="Parent epic", workflow_id="epic")
        return test_db

    def test_parent_project_is_resolved_from_the_item_row(self, epic_db):
        assert item_project(epic_db, 42) is not None

    def test_missing_item_resolves_to_no_project(self, epic_db):
        assert item_project(epic_db, 999999) is None

    def test_upsert_follows_the_default(self, epic_db, alternate_limit):
        epic.task_upsert(epic_db, "42", 1, "x" * alternate_limit)
        with pytest.raises(ValueError, match=f"{alternate_limit} characters"):
            epic.task_upsert(epic_db, "42", 2, "x" * (alternate_limit + 1))

    def test_field_update_refuses_an_over_long_title(self, epic_db, alternate_limit):
        """The metadata write path enforces the same limit as the upsert."""
        epic.task_upsert(epic_db, "42", 1, "Short")
        with pytest.raises(ValueError, match=f"{alternate_limit} characters"):
            epic.task_update_field(
                epic_db, "42", 1, "title", "x" * (alternate_limit + 1)
            )

    def test_field_update_accepts_a_title_at_the_limit(self, epic_db, alternate_limit):
        epic.task_upsert(epic_db, "42", 1, "Short")
        epic.task_update_field(epic_db, "42", 1, "title", "x" * alternate_limit)

    def test_metadata_amendment_enforces_the_limit(self, epic_db, alternate_limit):
        """Amending metadata is the path that used to skip validation."""
        from yoke_core.domain import epic_amend

        epic.task_upsert(epic_db, "42", 1, "Short")
        with pytest.raises(ValueError, match=f"{alternate_limit} characters"):
            epic_amend.task_metadata_update(
                epic_db, 42, 1, {"title": "x" * (alternate_limit + 1)}
            )
