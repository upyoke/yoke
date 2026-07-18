"""Field rule and validation tests for yoke_core.domain.mutations —
covers validate_* functions, prepare_create field rules, and prepare_update
basic field validation.
"""

from __future__ import annotations

import os
import sys


# Ensure the repo root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from yoke_core.domain.mutations import (
    SUPPORTED_UPDATE_FIELDS,
    TITLE_MAX_LENGTH,
    VALID_PRIORITIES,
    VALID_TYPES,
    GateContext,
    ItemState,
    MutationEventKind,
    prepare_create,
    prepare_update,
    validate_frozen,
    validate_priority,
    validate_title,
    validate_type,
)

TEST_ITEM_ID = 42
TEST_ITEM_REF = f"YOK-{TEST_ITEM_ID}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_item(**overrides) -> ItemState:
    """Create a minimal ItemState with sensible defaults."""
    defaults = dict(
        id=42,
        title="Test item",
        item_type="issue",
        status="idea",
        priority="medium",
        rework_count=0,
        frozen=False,
        project="yoke",
    )
    defaults.update(overrides)
    return ItemState(**defaults)


def _make_gate(**overrides) -> GateContext:
    """Create a minimal GateContext with sensible defaults."""
    return GateContext(**overrides)


# ---------------------------------------------------------------------------
# Title validation
# ---------------------------------------------------------------------------


class TestValidateTitle:
    def test_valid_title(self):
        assert validate_title("A good title") is None

    def test_empty_title(self):
        assert validate_title("") is not None

    def test_whitespace_title(self):
        assert validate_title("   ") is not None

    def test_max_length_title(self):
        assert validate_title("x" * TITLE_MAX_LENGTH) is None

    def test_over_max_length_title(self):
        err = validate_title("x" * (TITLE_MAX_LENGTH + 1))
        assert err is not None
        assert str(TITLE_MAX_LENGTH) in err


# ---------------------------------------------------------------------------
# Type validation
# ---------------------------------------------------------------------------


class TestValidateType:
    def test_valid_types(self):
        for t in VALID_TYPES:
            assert validate_type(t) is None

    def test_invalid_type(self):
        err = validate_type("story")
        assert err is not None
        assert "story" in err


# ---------------------------------------------------------------------------
# Priority validation
# ---------------------------------------------------------------------------


class TestValidatePriority:
    def test_valid_priorities(self):
        for p in VALID_PRIORITIES:
            assert validate_priority(p) is None

    def test_invalid_priority(self):
        assert validate_priority("critical") is not None


# ---------------------------------------------------------------------------
# Frozen validation
# ---------------------------------------------------------------------------


class TestValidateFrozen:
    def test_bool_true(self):
        assert validate_frozen(True) is None

    def test_bool_false(self):
        assert validate_frozen(False) is None

    def test_string_true(self):
        assert validate_frozen("true") is None

    def test_string_false(self):
        assert validate_frozen("false") is None

    def test_invalid(self):
        assert validate_frozen("maybe") is not None


# ===========================================================================
# Create mutation
# ===========================================================================


class TestPrepareCreate:
    def test_successful_create(self):
        result = prepare_create(
            title="New issue",
            item_type="issue",
            priority="high",
            project="yoke",
        )
        assert result.success is True
        assert result.error is None
        assert result.field_writes["title"] == "New issue"
        assert result.field_writes["type"] == "issue"
        assert result.field_writes["priority"] == "high"
        assert result.field_writes["status"] == "idea"
        assert result.field_writes["project"] == "yoke"
        assert result.field_writes["rework_count"] == 0
        assert result.field_writes["frozen"] is False
        assert any(e.kind == MutationEventKind.CREATED for e in result.events)

    def test_default_priority(self):
        result = prepare_create(title="Test", item_type="issue")
        assert result.success is True
        assert result.field_writes["priority"] == "medium"

    def test_invalid_title_too_long(self):
        result = prepare_create(
            title="x" * (TITLE_MAX_LENGTH + 1),
            item_type="issue",
        )
        assert result.success is False
        assert result.error_code == "VALIDATION_ERROR"

    def test_empty_title(self):
        result = prepare_create(title="", item_type="issue")
        assert result.success is False

    def test_invalid_type(self):
        result = prepare_create(title="Test", item_type="story")
        assert result.success is False
        assert result.error_code == "VALIDATION_ERROR"

    def test_invalid_priority(self):
        result = prepare_create(
            title="Test", item_type="issue", priority="critical",
        )
        assert result.success is False

    def test_create_only_emits_created_event(self):
        """Create mutations should only emit the canonical created event."""
        result = prepare_create(
            title="My issue", item_type="issue", project="yoke",
        )
        assert result.success is True
        assert [e.kind for e in result.events] == [MutationEventKind.CREATED]

    def test_flow_project_mismatch(self):
        result = prepare_create(
            title="Test", item_type="issue",
            project="yoke",
            deployment_flow="externalwebapp-flow",
            flow_project="externalwebapp",
        )
        assert result.success is False
        assert "externalwebapp" in result.error

    def test_flow_project_match(self):
        result = prepare_create(
            title="Test", item_type="issue",
            project="yoke",
            deployment_flow="yoke-flow",
            flow_project="yoke",
        )
        assert result.success is True

    # Create-time status override validation

    def test_create_with_valid_issue_status_override(self):
        """valid issue status override sets status in field_writes."""
        result = prepare_create(
            title="Imported item", item_type="issue", status="implementing",
        )
        assert result.success is True
        assert result.field_writes["status"] == "implementing"

    def test_create_with_default_status(self):
        """omitting status defaults to idea."""
        result = prepare_create(
            title="Normal item", item_type="issue",
        )
        assert result.success is True
        assert result.field_writes["status"] == "idea"

    def test_create_with_invalid_issue_status_rejects(self):
        """invalid status for issue type is rejected."""
        result = prepare_create(
            title="Bad status", item_type="issue", status="planning",
        )
        assert result.success is False
        assert result.error_code == "VALIDATION_ERROR"
        assert "not a valid issue status" in result.error

    def test_create_with_valid_epic_status_override(self):
        """valid epic status override sets status in field_writes."""
        result = prepare_create(
            title="Planned epic", item_type="epic", status="planning",
        )
        assert result.success is True
        assert result.field_writes["status"] == "planning"

    def test_create_with_invalid_epic_status_rejects(self):
        """invalid status for epic type is rejected."""
        result = prepare_create(
            title="Bad epic", item_type="epic", status="bogus",
        )
        assert result.success is False
        assert result.error_code == "VALIDATION_ERROR"

    def test_create_with_idea_status_is_noop(self):
        """explicit status=idea behaves identically to default."""
        result = prepare_create(
            title="Explicit idea", item_type="issue", status="idea",
        )
        assert result.success is True
        assert result.field_writes["status"] == "idea"


# ===========================================================================
# Update mutation — basic field rules
# ===========================================================================


class TestPrepareUpdateBasic:
    def test_unsupported_field(self):
        item = _make_item()
        result = prepare_update(item=item, field_name="body", value="x")
        assert result.success is False
        assert result.error_code == "UNSUPPORTED_FIELD"

    def test_supported_fields_are_complete(self):
        """All listed fields are in the supported set."""
        expected = {
            "status", "frozen", "blocked", "blocked_reason",
            "priority", "project", "deployment_flow", "deployed_to", "title",
            "worktree",
        }
        assert SUPPORTED_UPDATE_FIELDS == expected

    def test_worktree_update_can_clear_pointer(self):
        item = _make_item(worktree="YOK-1215")
        result = prepare_update(item=item, field_name="worktree", value="")
        assert result.success is True
        assert result.field_writes["worktree"] == ""
        assert "updated_at" in result.field_writes

    def test_title_update_valid(self):
        item = _make_item()
        result = prepare_update(item=item, field_name="title", value="New title")
        assert result.success is True
        assert result.field_writes["title"] == "New title"
        assert "updated_at" in result.field_writes

    def test_title_update_too_long(self):
        item = _make_item()
        result = prepare_update(
            item=item, field_name="title",
            value="x" * (TITLE_MAX_LENGTH + 1),
        )
        assert result.success is False

    def test_priority_update(self):
        item = _make_item()
        result = prepare_update(item=item, field_name="priority", value="high")
        assert result.success is True

    def test_priority_update_invalid(self):
        item = _make_item()
        result = prepare_update(
            item=item, field_name="priority", value="critical",
        )
        assert result.success is False

    def test_frozen_update(self):
        item = _make_item()
        result = prepare_update(item=item, field_name="frozen", value=True)
        assert result.success is True

    def test_frozen_update_invalid(self):
        item = _make_item()
        result = prepare_update(item=item, field_name="frozen", value="maybe")
        assert result.success is False

    def test_project_update(self):
        item = _make_item()
        result = prepare_update(item=item, field_name="project", value="externalwebapp")
        assert result.success is True
