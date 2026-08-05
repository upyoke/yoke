"""Cut workflow and deployment stages over to their domain vocabulary."""

from __future__ import annotations

import copy
import json
from typing import Any

from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.flow_validation import validate_stages
from yoke_core.domain.workflow_definition_codec import (
    canonical_definition_json,
    definition_digest,
)
from yoke_core.domain.workflow_schema import (
    WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER,
    _ensure_immutable_version_triggers,
)


WORKFLOW_SCHEMA_VERSION = 3

#: Every column pointing at a workflow version. Folding one row into another
#: has to carry these across before the redundant row can go.
_VERSION_REFERENCES = (
    ("items", "workflow_version_id"),
    ("decision_requests", "consumed_workflow_version_id"),
    ("workflows", "current_version_id"),
)


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _object(raw: Any, *, subject: str) -> dict[str, Any]:
    try:
        value = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise AssertionError(f"{subject} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise AssertionError(f"{subject} must be a JSON object")
    return value


def _array(raw: Any, *, subject: str) -> list[Any]:
    try:
        value = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise AssertionError(f"{subject} is not valid JSON") from exc
    if not isinstance(value, list):
        raise AssertionError(f"{subject} must be a JSON array")
    return value


def _rewrite_workflow(definition: dict[str, Any]) -> dict[str, Any]:
    rewritten = dict(definition)
    old_bindings = rewritten.pop("executor_bindings", None)
    if old_bindings is not None and "skill_bindings" in rewritten:
        raise AssertionError("workflow definition carries both binding vocabularies")
    bindings = old_bindings if old_bindings is not None else rewritten.get(
        "skill_bindings"
    )
    if not isinstance(bindings, list):
        raise AssertionError("workflow definition has no skill bindings")

    normalized: list[dict[str, Any]] = []
    for index, raw_binding in enumerate(bindings):
        if not isinstance(raw_binding, dict):
            raise AssertionError(f"workflow binding {index} is not an object")
        binding = dict(raw_binding)
        old_skill = binding.pop("executor_id", None)
        if old_skill is not None and "skill_id" in binding:
            raise AssertionError(
                f"workflow binding {index} carries both skill id vocabularies"
            )
        if old_skill is not None:
            binding["skill_id"] = old_skill
        if not str(binding.get("skill_id") or ""):
            raise AssertionError(f"workflow binding {index} has no skill id")
        normalized.append(binding)

    rewritten["skill_bindings"] = normalized
    for stage in rewritten.get("stages") or []:
        if not isinstance(stage, dict) or not isinstance(stage.get("description"), str):
            continue
        stage["description"] = (
            stage["description"]
            .replace("Executors", "Skills")
            .replace("Executor", "Skill")
            .replace("executors", "skills")
            .replace("executor", "skill")
        )
    schema_version = rewritten.get("schema_version")
    if schema_version == 2:
        rewritten["schema_version"] = WORKFLOW_SCHEMA_VERSION
    elif not _schema_version_at_or_past_this_entry(schema_version):
        raise AssertionError(
            f"workflow definition has unsupported schema version {schema_version!r}"
        )
    return rewritten


def _schema_version_at_or_past_this_entry(schema_version: object) -> bool:
    """Whether a definition is already at or beyond what this entry produces.

    A permanent history entry outlives the shape it was written against. This
    one moved definitions from version 2 to 3; the codec has since gone past 3,
    and every later version already satisfies what this entry exists to
    establish. Treating "newer than my target" as an error would make an entry
    that ran cleanly a year ago start failing boots the moment the schema moved
    on — the entry has not become wrong, it has become finished.

    Version 1 predates the versioned definition entirely and is left alone
    exactly as it was before.
    """
    return schema_version == 1 or (
        isinstance(schema_version, int)
        and not isinstance(schema_version, bool)
        and schema_version >= WORKFLOW_SCHEMA_VERSION
    )


def _rewrite_stages(stages: list[Any]) -> list[Any]:
    rewritten: list[Any] = []
    for index, raw_stage in enumerate(stages):
        if not isinstance(raw_stage, dict):
            raise AssertionError(f"deployment stage {index} is not an object")
        stage = dict(raw_stage)
        old_runner = stage.pop("executor", None)
        if old_runner is not None and "step_runner" in stage:
            raise AssertionError(
                f"deployment stage {index} carries both runner vocabularies"
            )
        if old_runner is not None:
            stage["step_runner"] = old_runner
        rewritten.append(stage)
    validate_stages(json_helper.dumps_compact(rewritten))
    return rewritten


def _allow_workflow_version_rewrite(conn: Any, *, allowed: bool) -> None:
    """Temporarily cross the registry's immutability guard for this cutover."""
    if db_backend.connection_is_postgres(conn):
        action = "DISABLE" if allowed else "ENABLE"
        conn.execute(
            f"ALTER TABLE workflow_versions {action} TRIGGER "
            f"{WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}"
        )
        return
    if allowed:
        conn.execute(
            f"DROP TRIGGER IF EXISTS {WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}_update"
        )
        conn.execute(
            f"DROP TRIGGER IF EXISTS {WORKFLOW_VERSIONS_IMMUTABLE_TRIGGER}_delete"
        )
        return
    _ensure_immutable_version_triggers(conn)


def _final_forms(rows: list[Any]) -> list[tuple[int, str, int, Any, str]]:
    """What each row will hold once this entry has run.

    Computed for every row before anything is written, because the choice a
    row needs -- rewrite in place, or fold away as a duplicate -- depends on
    what the OTHER rows will hold, not on what they hold now.
    """
    forms: list[tuple[int, str, int, Any, str]] = []
    for row_id, workflow_id, version, raw, digest in rows:
        original = _object(raw, subject=f"workflow version {row_id}")
        # Deep copy: _rewrite_workflow edits stage descriptions in place, so a
        # shallow copy would mutate the baseline it is compared against and
        # every row would look unchanged.
        definition = _rewrite_workflow(copy.deepcopy(original))
        changed = definition != original
        forms.append(
            (
                int(row_id),
                str(workflow_id),
                int(version),
                definition if changed else None,
                definition_digest(definition) if changed else str(digest),
            )
        )
    return forms


def _partition(
    forms: list[tuple[int, str, int, Any, str]],
) -> tuple[list[tuple[int, int]], list[tuple[int, dict[str, Any]]]]:
    """Split the rows into folds and rewrites.

    Two rows of one workflow that end up holding identical content are the
    same published definition wearing two vocabularies, and a workflow may
    not carry one digest twice, so one of them has to go. The higher version
    survives: a workflow's newest version is what new work pins, and removing
    it would change which definition the registry considers current.
    """
    survivor: dict[tuple[str, str], tuple[int, int]] = {}
    for row_id, workflow_id, version, _definition, digest in forms:
        held = survivor.get((workflow_id, digest))
        if held is None or version > held[1]:
            survivor[(workflow_id, digest)] = (row_id, version)

    folds: list[tuple[int, int]] = []
    rewrites: list[tuple[int, dict[str, Any]]] = []
    for row_id, workflow_id, _version, definition, digest in forms:
        keeper = survivor[(workflow_id, digest)][0]
        if keeper != row_id:
            folds.append((row_id, keeper))
        elif definition is not None:
            rewrites.append((row_id, definition))
    return folds, rewrites


def _fold_redundant_version(
    conn: Any, *, redundant: int, survivor: int, marker: str
) -> None:
    """Carry every reference onto the surviving row, then drop the duplicate."""
    from yoke_core.domain.schema_common import _table_exists

    for table, column in _VERSION_REFERENCES:
        if not _table_exists(conn, table):
            continue
        conn.execute(
            f"UPDATE {table} SET {column}={marker} WHERE {column}={marker}",
            (survivor, redundant),
        )
    conn.execute(f"DELETE FROM workflow_versions WHERE id={marker}", (redundant,))


def apply(conn: Any) -> None:
    """Rewrite storage keys without changing stage behavior or row identity.

    Writes only rows that actually change. That is not an optimization: these
    rows are published immutable definitions, and this entry has to disable
    their immutability trigger to touch any of them. Rewriting a row that
    already carries the new vocabulary would re-serialize it and recompute its
    digest for no reason — and a published definition whose digest no longer
    matches the code-owned one is a startup abort, not a cosmetic difference.
    An entry that is already done must therefore write nothing at all.

    A row whose rewritten content already exists on another version of the
    same workflow is folded into that row rather than rewritten. The registry
    publishes a new version whenever the code-owned definition changes, so
    while this entry sat unapplied the running code could publish the very row
    it would produce; rewriting then recreates an existing row and collides on
    the per-workflow digest. Folds run first so a freed digest is available to
    whichever row is meant to hold it.
    """
    marker = _marker(conn)
    rows = conn.execute(
        "SELECT id, workflow_id, version, definition_json, definition_digest "
        "FROM workflow_versions ORDER BY workflow_id, version"
    ).fetchall()
    folds, rewrites = _partition(_final_forms(rows))

    if folds or rewrites:
        _allow_workflow_version_rewrite(conn, allowed=True)
        try:
            for redundant, survivor in folds:
                _fold_redundant_version(
                    conn, redundant=redundant, survivor=survivor, marker=marker
                )
            for row_id, definition in rewrites:
                conn.execute(
                    "UPDATE workflow_versions SET definition_json="
                    f"{marker}, definition_digest={marker}, "
                    f"definition_schema_version={marker} WHERE id={marker}",
                    (
                        # The canonical form the registry's own writer uses --
                        # sorted keys, non-ASCII left literal. Serializing a
                        # digest-guarded row any other way stores bytes no
                        # other writer would produce, and that drift is
                        # indistinguishable from corruption to a reader.
                        canonical_definition_json(definition),
                        definition_digest(definition),
                        definition["schema_version"],
                        row_id,
                    ),
                )
        finally:
            _allow_workflow_version_rewrite(conn, allowed=False)

    flow_rows = conn.execute(
        "SELECT id, stages FROM deployment_flows ORDER BY id"
    ).fetchall()
    for row in flow_rows:
        original = _array(row[1], subject=f"deployment flow {row[0]}")
        stages = _rewrite_stages(copy.deepcopy(original))
        if stages == original:
            continue
        conn.execute(
            f"UPDATE deployment_flows SET stages={marker} WHERE id={marker}",
            (json_helper.dumps_compact(stages), row[0]),
        )


def invariants(conn: Any) -> None:
    """Prove all live definitions use only the new vocabulary."""
    for row in conn.execute(
        "SELECT id, definition_schema_version, definition_json, definition_digest "
        "FROM workflow_versions ORDER BY id"
    ).fetchall():
        definition = _object(row[2], subject=f"workflow version {row[0]}")
        if not _schema_version_at_or_past_this_entry(
            definition.get("schema_version")
        ):
            raise AssertionError(
                f"workflow version {row[0]} has stale schema version"
            )
        if "executor_bindings" in definition:
            raise AssertionError(
                f"workflow version {row[0]} retains executor_bindings"
            )
        bindings = definition.get("skill_bindings")
        if not isinstance(bindings, list):
            raise AssertionError(f"workflow version {row[0]} has no skill bindings")
        for binding in bindings:
            if "executor_id" in binding or not str(binding.get("skill_id") or ""):
                raise AssertionError(
                    f"workflow version {row[0]} has stale skill binding vocabulary"
                )
        for stage in definition.get("stages") or []:
            description = str(stage.get("description") or "").lower()
            if "executor" in description:
                raise AssertionError(
                    f"workflow version {row[0]} retains executor stage prose"
                )
        if int(row[1]) != int(definition["schema_version"]):
            raise AssertionError(
                f"workflow version {row[0]} schema versions disagree"
            )
        if definition_digest(definition) != str(row[3]):
            raise AssertionError(f"workflow version {row[0]} digest is stale")

    for row in conn.execute(
        "SELECT id, stages FROM deployment_flows ORDER BY id"
    ).fetchall():
        stages = _array(row[1], subject=f"deployment flow {row[0]}")
        validate_stages(json_helper.dumps_compact(stages))
        for stage in stages:
            if "executor" in stage:
                raise AssertionError(
                    f"deployment flow {row[0]} retains executor stage vocabulary"
                )


__all__ = ["apply", "invariants"]
