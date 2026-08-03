"""Exact immutable history for built-in workflow versions."""

from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_version_history,
)
from yoke_core.domain.workflow_definition_codec import definition_digest
from yoke_core.domain.workflow_definition_validation import (
    validate_workflow_definition,
)

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
