"""A registered verification command must name something that can run."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain.qa_command_argv_presence import (
    REFUSING_REASON_CODES,
    check_argv_presence,
    require_argv_present,
)


def test_a_repo_relative_script_that_exists_resolves(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "test.sh").write_text("#!/bin/sh\n")

    presence = check_argv_presence("./scripts/test.sh --fast", checkout=tmp_path)

    assert presence.verified
    assert presence.reason_code == "resolved_in_checkout"


def test_a_repo_relative_script_the_repo_lacks_is_refused(tmp_path: Path) -> None:
    presence = check_argv_presence(
        "vendor/bin/phpunit --testsuite unit", checkout=tmp_path
    )

    assert not presence.verified
    assert presence.reason_code == "argv_absent_from_repo"
    # The refusal names the token, the tree it looked in, and the honest
    # alternative — an operator who has no suite should attest, not invent.
    assert "vendor/bin/phpunit" in presence.message
    assert str(tmp_path) in presence.message
    assert "no-tests attest" in presence.message


def test_a_program_on_path_resolves(tmp_path: Path) -> None:
    presence = check_argv_presence("python3 -m pytest", checkout=tmp_path)

    assert presence.verified
    assert presence.reason_code == "resolved_on_path"


def test_a_program_this_machine_lacks_is_reported_not_refused(
    tmp_path: Path,
) -> None:
    # An operator on a laptop binding `mvn verify` for a repository whose CI
    # has Maven is doing the right thing. Refusing that would make the honest
    # case impossible, so this outcome is named rather than blocked.
    presence = check_argv_presence("mvn -q -DskipITs test", checkout=tmp_path)

    if presence.reason_code == "resolved_on_path":  # Maven installed here
        assert presence.verified
        return
    assert not presence.verified
    assert presence.reason_code == "program_not_on_this_machine"
    assert presence.reason_code not in REFUSING_REASON_CODES


def test_an_unmapped_checkout_reports_that_rather_than_guessing() -> None:
    # The control plane serving a repository it does not hold cannot look.
    # Reporting that is the point: a silent pass is how the invented command
    # gets registered in the first place.
    presence = check_argv_presence("vendor/bin/phpunit", checkout=None)

    assert not presence.verified
    assert presence.reason_code == "checkout_unmapped"
    assert "yoke project register" in presence.message


def test_an_empty_command_is_refused() -> None:
    assert check_argv_presence("   ", checkout=None).reason_code == "empty_command"


def test_unbalanced_quoting_is_refused_by_name(tmp_path: Path) -> None:
    presence = check_argv_presence('pytest -k "unclosed', checkout=tmp_path)

    assert presence.reason_code == "unparsable_command"


def test_require_raises_on_absence_and_passes_an_unmapped_checkout(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="cannot register 'quick'"):
        require_argv_present(
            "vendor/bin/phpunit",
            checkout=tmp_path,
            project="acme",
            scope="quick",
        )

    unmapped = require_argv_present(
        "vendor/bin/phpunit", checkout=None, project="acme", scope="quick"
    )
    assert unmapped.reason_code == "checkout_unmapped"

    # A program name never refuses, whichever machine is registering.
    require_argv_present(
        "mvn -q -DskipITs test",
        checkout=tmp_path,
        project="acme",
        scope="quick",
    )
