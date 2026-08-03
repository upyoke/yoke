"""Exact immutable history for built-in workflow versions."""

from copy import deepcopy

from yoke_core.domain.builtin_workflow_definitions import (
    BUILTIN_WORKFLOW_IDS,
    builtin_workflow_definition,
    builtin_workflow_version_history,
)
from yoke_core.domain.workflow_definition_codec import (
    canonical_definition_json,
    definition_digest,
)
from yoke_core.domain.workflow_definition_validation import (
    validate_workflow_definition,
)
from yoke_core.domain.workflow_registry import converge_builtin_workflows

_LEGACY_TS = "2026-07-28T00:00:00Z"

VERSION_DIGESTS = {
    1: {
        "issue": "2f1f8c3ebc131a88ca7ef02fd650a0341f8e5491ba69bbbee92372b243fc873b",
        "epic": "82f83cbb03bc8c8f4a935de53f1d21ad1904d5533a921d5b1b85f82e75578a5a",
        "blitz": "4360357c38629f4c48fe8c0ae03a0894580f9a00eea487dda281a9e43a631f4f",
        "dash": "f436fac4790ec9ed6fce7c3b329f2b71998bc7e805690a567bf90049e34ccfe7",
    },
    2: {
        "issue": "810389bdc314104a1c9fd3dbe63fa4dc116c1ff67e617bb1981c75661791713b",
        "epic": "1bc61f9abec9a60158b247b3d4244cd391f7eec203cf857ea01521cd8065d684",
        "blitz": "e4a58b157ab528de3f34d991dbaf7038641433d7949176cbfd1437a953d604b0",
        "dash": "727e1a058b0f1169dc1e916a8d6286e47e8f3b7f4209f95233038ec2893a039a",
    },
}


def test_immutable_history_digests_and_schema_shapes_are_exact():
    history = builtin_workflow_version_history()
    for version, expected in VERSION_DIGESTS.items():
        assert {
            row["workflow"]["id"]: definition_digest(row["definition"])
            for row in history
            if row["version"] == version
        } == expected
    assert all(
        "approval_defaults" not in row["definition"]["policies"]
        for row in history if row["version"] == 1
    )
    assert all(
        row["definition"]["policies"]["approval_defaults"] == {}
        for row in history if row["version"] == 2
    )
    for row in history:
        validate_workflow_definition(row["definition"])


def _schema_two_version_three_definition(workflow_id: str) -> dict:
    definition = deepcopy(
        builtin_workflow_definition(workflow_id)["definition"]
    )
    definition["schema_version"] = 2
    for stage in definition["stages"]:
        stage.pop("glyph", None)
        stage.pop("board_bucket", None)
    policies = definition["policies"]
    policies.pop("path_survey", None)
    policies["item_posture_allowlist"] = [
        value
        for value in policies["item_posture_allowlist"]
        if value != "path_survey"
    ]
    definition["executor_bindings"] = [
        {
            ("executor_id" if key == "skill_id" else key): value
            for key, value in binding.items()
        }
        for binding in definition.pop("skill_bindings")
    ]
    return definition


def _reset_to_version_one(conn, history: list[dict]) -> None:
    conn.execute("TRUNCATE workflows, workflow_versions RESTART IDENTITY CASCADE")
    for fixture in history:
        if fixture["version"] != 1:
            continue
        workflow = fixture["workflow"]
        definition = fixture["definition"]
        conn.execute(
            "INSERT INTO workflows "
            "(id, name, description, source, status, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, 'active', %s, %s)",
            (
                workflow["id"],
                workflow["name"],
                workflow["description"],
                workflow["source"],
                _LEGACY_TS,
                _LEGACY_TS,
            ),
        )
        version_id = conn.execute(
            "INSERT INTO workflow_versions "
            "(workflow_id, version, definition_schema_version, "
            "definition_json, definition_digest, published_at, immutable_at) "
            "VALUES (%s, 1, 1, %s, %s, %s, %s) RETURNING id",
            (
                workflow["id"],
                canonical_definition_json(definition),
                definition_digest(definition),
                _LEGACY_TS,
                _LEGACY_TS,
            ),
        ).fetchone()[0]
        conn.execute(
            "UPDATE workflows SET current_version_id = %s WHERE id = %s",
            (version_id, workflow["id"]),
        )
    conn.commit()


def test_schema_two_version_three_history_converges_without_rewriting(test_db):
    history = builtin_workflow_version_history()
    _reset_to_version_one(test_db, history)
    version_two = {
        fixture["workflow"]["id"]: fixture["definition"]
        for fixture in history
        if fixture["version"] == 2
    }
    legacy_rows = {}
    for workflow_id in BUILTIN_WORKFLOW_IDS:
        for version, definition in (
            (2, version_two[workflow_id]),
            (3, _schema_two_version_three_definition(workflow_id)),
        ):
            payload = canonical_definition_json(definition)
            digest = definition_digest(definition)
            test_db.execute(
                "INSERT INTO workflow_versions "
                "(workflow_id, version, definition_schema_version, "
                "definition_json, definition_digest, published_at, immutable_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    workflow_id,
                    version,
                    definition["schema_version"],
                    payload,
                    digest,
                    _LEGACY_TS,
                    _LEGACY_TS,
                ),
            )
            if version == 3:
                legacy_rows[workflow_id] = (payload, digest)
    test_db.commit()

    converge_builtin_workflows(test_db)

    for workflow_id in BUILTIN_WORKFLOW_IDS:
        stored = test_db.execute(
            "SELECT definition_json, definition_digest "
            "FROM workflow_versions WHERE workflow_id = %s AND version = 3",
            (workflow_id,),
        ).fetchone()
        assert tuple(stored) == legacy_rows[workflow_id]
        current = test_db.execute(
            "SELECT definition_digest FROM workflow_versions "
            "WHERE workflow_id = %s AND version = 4",
            (workflow_id,),
        ).fetchone()
        definition = builtin_workflow_definition(workflow_id)["definition"]
        assert current[0] == definition_digest(definition)
