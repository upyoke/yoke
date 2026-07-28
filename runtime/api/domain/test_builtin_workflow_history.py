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
        "issue": "a663bad503664557c9990a9f3ea281c123864f4f8c13e4573dc1996181c64fa8",
        "epic": "e122cee5d947bf2e822fb66ad0fda0aaab218281e48731ae32fec0647785dfaf",
        "blitz": "d14b977565f7580cc43cee2c27b9b3eaf1a425514314903bf86bc274ab394571",
        "dash": "6222fc5bb143909574ae5c305b2ef35849f5d4598a73a6d4b28c8bcf4d414931",
    },
    2: {
        "issue": "3daf973869d819ad3efee5869c9be1f4a71bd28711c919f7fda9c3a7c6d523ad",
        "epic": "7e15484395d46766c933e27ccc29a6d8af2a6a5cf44f85e9b8e0067cdf03ed36",
        "blitz": "dd75d375706225bc131120fe1839179477ae492d8c16f284d8d1c44cd0c6dcce",
        "dash": "30ec3957c785b7748ba2a76ab8f34c4a5d73a166bf6c7fa34d1cca2cb594d369",
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
