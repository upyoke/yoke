"""Non-import contract companions survive bounded selection deferral."""

from __future__ import annotations

from pathlib import Path

from yoke_core.tools import _impacted_contract_tests as contracts
from yoke_core.tools import _impacted_contract_tests_path_claims as path_claims
from yoke_core.tools import impacted_tests
from yoke_core.tools.impacted_tests import build_import_index, select


def _write(root: Path, relative: str, body: str = "VALUE = 1\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)


def test_contract_companions_survive_bounded_shared_fixture_deferral(
    tmp_path: Path,
) -> None:
    shared_fixture = f"{impacted_tests.SHARED_TEST_FIXTURE_PATHS[1]}shared.py"
    changed = (
        shared_fixture,
        f"{contracts.MIGRATION_HISTORY_SOURCE_PREFIX}0099_example.py",
        contracts.EPIC_RESOLUTION_SOURCE_PATH,
        sorted(path_claims.PATH_CLAIM_SOURCE_PATHS)[0],
        *path_claims.SURVEY_ADVISORY_SOURCE_PATHS,
        *(f"{prefix}pack.json" for prefix in contracts.MACHINE_QA_PACK_SOURCE_PREFIXES),
    )
    for path in changed:
        _write(tmp_path, path, "{}\n" if path.endswith(".json") else "VALUE = 1\n")

    expected = {
        *contracts.MIGRATION_HISTORY_CONTRACT_TESTS,
        *contracts.MACHINE_QA_PACK_CONTRACT_TESTS,
        *contracts.EPIC_QA_READ_CONTRACT_TESTS,
        *path_claims.PATH_CLAIM_FEASIBILITY_TESTS,
        *path_claims.SURVEY_ADVISORY_TESTS,
    }
    for test_path in {*impacted_tests.ALWAYS_RUN_TESTS, *expected}:
        _write(tmp_path, test_path, "def test_contract(): pass\n")

    selection = select(changed, build_import_index(tmp_path), bounded=True)

    assert selection.bounded_deferral is True
    assert expected <= set(selection.files)
    assert any(
        token.startswith("migration_history_contract:")
        for token in selection.widening_triggers
    )
    assert any(
        token.startswith("machine_qa_pack_contract:")
        for token in selection.widening_triggers
    )
    assert any(
        token.startswith("epic_qa_read_contract:")
        for token in selection.widening_triggers
    )
    assert any(
        token.startswith("path_claim_feasibility_contract:")
        for token in selection.widening_triggers
    )
    assert any(
        token.startswith("survey_advisory_contract:")
        for token in selection.widening_triggers
    )
