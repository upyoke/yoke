"""Every taught ``yoke`` recipe resolves and its argument shape parses.

An agent copies a command out of the surface that taught it. A recipe
naming a route the registry does not carry, or a flag or value the
adapter no longer accepts, costs that reader a failed call and a
recovery detour — so the contract is checked here rather than left to a
field note.

The audit resolves each spelling; ``taught_recipe_parse_probe``
substitutes documentation placeholders and asks the resolved adapter's
parser about the rest, stopping before dispatch. Literal browser steps and
marked mission capabilities also pass their pure product contracts; dynamic
configuration remains explicitly unverifiable.
"""

from __future__ import annotations

from pathlib import Path

from yoke_cli.product_boundary_teaching import (
    DRIFT_STALE_ARGUMENT_SHAPE,
    DRIFT_UNRESOLVED_YOKE,
    generate_teaching_audit,
)
from yoke_core.tools.taught_recipe_parse_probe import normalize, parse_probe
from yoke_core.tools.taught_recipe_semantic_probe import (
    capability_example_errors,
    probe_recipe,
)
from yoke_cli.product_boundary_teaching_extract import _teaching_files
from yoke_cli.product_boundary_teaching_sources import TEACHING_GLOBS


REPO_ROOT = Path(__file__).resolve().parents[3]
_COMMAND_DRIFT = (DRIFT_UNRESOLVED_YOKE, DRIFT_STALE_ARGUMENT_SHAPE)


def test_every_taught_yoke_recipe_resolves_and_parses() -> None:
    audit = generate_teaching_audit(
        repo_root=REPO_ROOT,
        smoke_yoke=parse_probe,
        include_help=True,
    )
    offenders = [
        f"{row.source}:{row.line_number} {row.drift_type}: {row.recipe}"
        + (f" -> {row.smoke_error}" if row.smoke_error else "")
        for row in audit.surfaces
        if row.drift_type in _COMMAND_DRIFT
    ]
    assert not offenders, (
        "taught yoke recipes that the registered command set does not "
        "carry as written:\n" + "\n".join(offenders)
    )
    for row in audit.surfaces:
        semantic = probe_recipe(row.recipe, normalize)
        if semantic.status == "unverifiable":
            print(
                f"{row.source}:{row.line_number} semantic_unverifiable: {semantic.detail}"
            )
    for relative, count in (
        ("docs/public/reference/exploratory-qa.md", 3),
        ("docs/public/reference/qa-platform/case-attachment.md", 1),
    ):
        text = (REPO_ROOT / relative).read_text()
        assert text.count("<!-- qa:test-machine-capability -->") == count
        assert not capability_example_errors(text, normalize), relative


def test_audit_reads_the_surfaces_that_teach_commands() -> None:
    """The corpus covers every tree a reader is taught from.

    A glob quietly dropped would leave the contract above passing while
    the surface it was meant to cover drifted, so the breadth is asserted
    rather than assumed.
    """
    audit = generate_teaching_audit(repo_root=REPO_ROOT, include_help=True)
    sources = {row.source for row in audit.surfaces}
    for expected in (
        "AGENTS.md",
        "CLAUDE.md",
        "CODEX.md",
        "runtime/harness/claude/rules/session.md",
    ):
        assert expected in sources, f"{expected} teaches commands but is unread"
    assert any(s.startswith(".agents/skills/yoke/") for s in sources)
    assert any(s.startswith("docs/") for s in sources)


def test_taught_manifest_and_router_paths_resolve():
    """An executor id and a home directory are not checkout path roots."""
    import re

    for path in _teaching_files(REPO_ROOT, TEACHING_GLOBS):
        text = path.read_text()
        assert "runtime/harness/<harness_id>/manifest.json" not in text, path
        assert "~/.agents/skills/yoke/SKILL.md" not in text, path
        for match in re.finditer(r"runtime/harness/([\w-]+)/manifest\.json", text):
            assert (REPO_ROOT / match[0]).is_file(), (path, match[0])
    assert (REPO_ROOT / ".agents/skills/yoke/SKILL.md").is_file()
    entry = (REPO_ROOT / ".agents/skills/yoke/strategize/entry.md").read_text()
    assert "not `--process`" not in entry
