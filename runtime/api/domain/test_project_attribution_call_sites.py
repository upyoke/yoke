"""No yoke_core path answers "which project?" with a compiled-in slug.

The pattern this pins used to read ``project = project or "yoke"``. On an
installation whose own project carries that slug it is invisible; on
every other project it files the work, the relay, or the event under a
project that never asked for it, in a row later readers cannot tell from
a deliberate write.

The scan is the test because the pattern is what regressed: one module
grew it back by copying a sibling, and the next ten copied that one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from yoke_core.domain import mutations_create
from yoke_core.domain.mutation_fields import CreateResult

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "packages/yoke-core/src/yoke_core"

PROJECT_NAME = r"(?:project|proj|gh_project|item_project|project_id|project_slug)"

#: A project-shaped value falling back to the literal slug.
FALLBACK_VALUE = re.compile(PROJECT_NAME + r'.*\b(?:or|else)\s+"yoke"')

#: A project-shaped name bound to it -- an assignment, or the default of
#: a parameter. Keyword arguments (``project="yoke"``, no spaces) are a
#: caller naming a project deliberately and are not this pattern.
FALLBACK_BINDING = re.compile(
    PROJECT_NAME + r"(?:\s*:\s*[\w\[\]\s|.]+)?" + r'\s=\s"yoke"'
)

#: The same default written without annotation or spaces, which only a
#: signature does.
FALLBACK_SIGNATURE = re.compile(r"def .*" + PROJECT_NAME + r'="yoke"')

#: Fixtures whose subject IS a project named yoke, so the literal there
#: is seeded data rather than an answer to "which project?".
EXEMPT_NAMES = frozenset({"_project_identity_test_helpers.py"})


def _offending_lines(path: Path) -> list[str]:
    offenders = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if "==" in line or "!=" in line:
            continue
        if any(
            pattern.search(line)
            for pattern in (FALLBACK_VALUE, FALLBACK_BINDING, FALLBACK_SIGNATURE)
        ):
            offenders.append(f"{path.name}:{number}: {line.strip()}")
    return offenders


def test_no_module_defaults_a_project_to_the_installations_own() -> None:
    offenders: list[str] = []
    for path in sorted(SOURCE_ROOT.rglob("*.py")):
        if path.name in EXEMPT_NAMES:
            continue
        offenders.extend(_offending_lines(path))

    assert offenders == [], (
        "these resolve a project by naming one: use "
        "yoke_core.domain.project_attribution.required_project (work that "
        "writes or relays) or resolved_project (telemetry)\n"
        + "\n".join(offenders)
    )


def test_the_scan_would_catch_the_pattern_it_exists_for(tmp_path) -> None:
    """A guard nobody has seen fail is a guard nobody can trust."""
    regressed = tmp_path / "regressed.py"
    regressed.write_text('gh_project = project or "yoke"\n', encoding="utf-8")

    assert _offending_lines(regressed)


@pytest.mark.parametrize("named", [None, "", "   "])
def test_a_create_naming_no_project_is_refused(named) -> None:
    """The sharpest case: filing work on a backlog nobody chose."""
    result = mutations_create.prepare_create(
        title="a title", workflow=object(), project=named
    )

    assert isinstance(result, CreateResult)
    assert result.success is False
    assert result.error_code == "PROJECT_REQUIRED"
