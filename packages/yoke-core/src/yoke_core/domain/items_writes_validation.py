"""Validation/guard helpers extracted from :mod:`items_writes`.

These helpers run inside :func:`yoke_core.domain.items_writes.update_structured_field`
to keep the writer body small. Each helper is a pure function over its
arguments plus (where needed) an open database connection; none of them
own connection lifecycle. JSON validators and freeze-immutability checks
are imported lazily to preserve the existing import ordering behaviour of
the parent writer.

Nothing here is part of the public ``items`` facade — :mod:`items_writes`
calls these directly.
"""

from __future__ import annotations

import textwrap

from yoke_core.domain.db_helpers import query_scalar


def apply_field_validators(field: str, content: str) -> str:
    """Apply per-field content normalization and JSON validation.

    Returns the (possibly transformed) content. Raises whatever the
    underlying validator raises for malformed JSON-shape fields.

    - ``spec``: ``textwrap.dedent`` strips a common leading prefix only,
      so heredoc-authored specs that intentionally contain column-0 code
      blocks are untouched. Other structured fields keep byte-exact
      round-trip.
    - ``browser_qa_metadata`` / ``db_mutation_profile`` /
      ``db_compatibility_attestation``: route through their validators
      and store canonical JSON so round-trip reads are stable.
    - ``architecture_impact``: validate enum value.
    """
    if field == "spec" and content:
        content = textwrap.dedent(content)

    if not (content and content.strip()):
        return content

    if field == "browser_qa_metadata":
        from yoke_core.domain.browser_qa_metadata import validate_json_string
        return validate_json_string(content)
    if field == "db_mutation_profile":
        from yoke_core.domain.db_mutation_profile import validate_json_string
        return validate_json_string(content)
    if field == "db_compatibility_attestation":
        from yoke_core.domain.db_compatibility_attestation import validate_json_string
        return validate_json_string(content)
    if field == "architecture_impact":
        from yoke_core.domain.architecture_impact import validate_value
        return validate_value(content)
    return content


def check_empty_content_guard(
    conn, field: str, item_id: int, has_content: bool
) -> None:
    """Refuse to overwrite a non-empty structured field with empty content.

    Raises ``ValueError`` when the field currently has content and the
    incoming write is empty/whitespace-only.
    """
    if has_content:
        return
    sql_existing = f"SELECT COALESCE({field}, '') FROM items WHERE id = %s"
    existing = query_scalar(conn, sql_existing, (item_id,))
    if existing and existing.strip():
        raise ValueError(
            f"Refusing to overwrite non-empty {field} with empty content "
            f"for YOK-{item_id}"
        )


def check_shrinkage_guard(
    conn, field: str, item_id: int, content: str, force: bool, has_content: bool
) -> None:
    """Refuse writes where new content is <50% of existing line count.

    Triggers only when:
    - ``force`` is False,
    - the incoming write is non-empty,
    - the existing field has 10+ lines.

    Raises ``ValueError`` describing the shrinkage when triggered.
    """
    if force or not has_content:
        return
    sql_existing = f"SELECT COALESCE({field}, '') FROM items WHERE id = %s"
    existing = query_scalar(conn, sql_existing, (item_id,))
    if not existing:
        return
    old_lines = existing.count("\n") + (
        1 if existing and not existing.endswith("\n") else 0
    )
    new_lines = content.count("\n") + (1 if not content.endswith("\n") else 0)
    if old_lines >= 10 and new_lines < (old_lines // 2):
        raise ValueError(
            f"Refusing {field} write for YOK-{item_id}: "
            f"new content ({new_lines} lines) is less than 50% of "
            f"existing {field} ({old_lines} lines). "
            f"This may indicate content loss. Use --force to override."
        )


def check_freeze_guards(
    conn, field: str, item_id: int, content: str, has_content: bool
) -> None:
    """Defend freeze locks on governed DB-mutation fields.

    Joint gate owns ``frozen_at`` mutation; the write path only defends
    the lock against drift. Raises ``ValueError`` with the freeze-check
    message when the incoming write violates the lock.
    """
    if not has_content:
        return
    sql_existing = f"SELECT COALESCE({field}, '') FROM items WHERE id = %s"

    if field == "db_mutation_profile":
        from yoke_core.domain.db_mutation_profile import check_model_name_frozen

        current_attestation = query_scalar(
            conn,
            "SELECT COALESCE(db_compatibility_attestation, '') FROM items WHERE id = %s",
            (item_id,),
        )
        current_profile = query_scalar(conn, sql_existing, (item_id,))
        freeze_err = check_model_name_frozen(
            current_attestation, current_profile, content
        )
        if freeze_err:
            raise ValueError(freeze_err)

    elif field == "db_compatibility_attestation":
        from yoke_core.domain.db_compatibility_attestation import (
            check_authored_fields_frozen,
        )

        current_attestation = query_scalar(conn, sql_existing, (item_id,))
        freeze_err = check_authored_fields_frozen(current_attestation, content)
        if freeze_err:
            raise ValueError(freeze_err)


__all__ = [
    "apply_field_validators",
    "check_empty_content_guard",
    "check_shrinkage_guard",
    "check_freeze_guards",
]
