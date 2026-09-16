"""Deployment teaching must not send an ordinary project after db-admin.

A `*-db-admin` connection is direct authority over the database behind a
control plane. Only whoever operates that control plane has one, so teaching
it as the way to run a deployment tells every managed project to go find
credentials that are not its own application database's and that it cannot
obtain. Ordinary delivery — create, start-for-item, execute, watch, retry,
close-out — runs over whichever connection holds the run row, HTTPS included.

The one true exception is a deploy that replaces the API serving its own
control plane: run state must stay writable while that API is replaced. The
executor detects exactly that case and names the connection when it refuses,
so the exception is taught at the moment it applies rather than up front. The
tests below check both halves — that the up-front teaching is gone from every
surface a project reads, and that the scoped exception survived the scrub.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_contracts.deployment_itemless_teaching import (
    CREATE_DESCRIPTION,
    ITEMLESS_RELEASE_RECIPE,
    WATCH_DEPLOY_DESCRIPTION,
)
from yoke_contracts.machine_config.schema import DB_ADMIN_ENV_SUFFIX
from yoke_contracts.project_contract.managed_block import extract_block_body
from yoke_core.domain.deploy_pipeline_environment import (
    CONTROL_PLANE_ENV_PLACEHOLDER,
    run_not_found_message,
    watch_deploy_command,
)

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "packages" / "yoke-core" / "src" / "yoke_core" / "install_bundle_tree"

# Every tree `yoke project install` copies into a target project, plus the
# packaged snapshot of that same tree, so the shipped bytes are checked and
# not only the canonical sources they are synced from.
SHIPPED_ROOTS = (
    REPO / ".agents" / "skills" / "yoke",
    REPO / ".yoke" / "docs",
    REPO / "runtime" / "agents",
    REPO / "runtime" / "harness" / "claude" / "rules",
    REPO / "runtime" / "harness" / "claude" / "agents",
    REPO / "runtime" / "harness" / "codex" / "agents",
    REPO / "runtime" / "harness" / "cursor" / "agents",
    BUNDLE,
)
SHIPPED_SUFFIXES = {".md", ".toml", ".json"}

# `AGENTS.md` is co-owned: only the marker-delimited block reaches a managed
# project, and this repo's own release shape lives below it.
MANAGED_BLOCK_FILES = (REPO / "AGENTS.md", BUNDLE / "AGENTS.md")

# Phrases that name a deployment operation rather than database authority.
DEPLOY_OPERATION_PHRASES = (
    "deployment-runs",
    "deployment run",
    "watch deploy",
    "deploy --",
    "deploy surface",
    "deployment flow",
    "start-for-item",
)
# Wording that scopes the admin connection to the self-deploy it is for.
SELF_DEPLOY_QUALIFIERS = ("serving api", "serving-api", "self-deploy")
# Prose wraps, so a qualifier one or two lines away still scopes the mention.
QUALIFIER_WINDOW = 2
# Prose names the connection family without the env-name hyphen, so the
# label is derived from the suffix rather than spelled a second time.
DB_ADMIN_LABEL = DB_ADMIN_ENV_SUFFIX.lstrip("-")


def _shipped_texts() -> list[tuple[str, str]]:
    """Every shipped surface as (label, text), managed blocks extracted."""
    managed = {path.resolve() for path in MANAGED_BLOCK_FILES}
    texts: list[tuple[str, str]] = []
    seen: set[Path] = set()
    for root in SHIPPED_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in SHIPPED_SUFFIXES:
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            raw = path.read_text(encoding="utf-8", errors="replace")
            if resolved in managed:
                raw = extract_block_body(raw) or ""
            texts.append((str(path.relative_to(REPO)), raw))
    for path in MANAGED_BLOCK_FILES:
        if path.resolve() in seen or not path.is_file():
            continue
        seen.add(path.resolve())
        body = extract_block_body(path.read_text(encoding="utf-8")) or ""
        texts.append((f"{path.relative_to(REPO)} (managed block)", body))
    return texts


def _unscoped_deploy_authority() -> list[str]:
    """Shipped lines naming db-admin as a deployment authority, unqualified."""
    offenders = []
    for label, text in _shipped_texts():
        lines = text.splitlines()
        for index, line in enumerate(lines):
            lowered = line.lower()
            if DB_ADMIN_LABEL not in lowered:
                continue
            if not any(phrase in lowered for phrase in DEPLOY_OPERATION_PHRASES):
                continue
            window = " ".join(
                lines[max(0, index - QUALIFIER_WINDOW) : index + QUALIFIER_WINDOW + 1]
            ).lower()
            if any(qualifier in window for qualifier in SELF_DEPLOY_QUALIFIERS):
                continue
            offenders.append(f"{label}:{index + 1}: {line.strip()[:160]}")
    return offenders


def test_shipped_surfaces_never_teach_db_admin_as_deployment_authority() -> None:
    """The defect this guards is silent: the copy reaches every project."""
    offenders = _unscoped_deploy_authority()
    assert offenders == [], (
        "installed surfaces name a *-db-admin connection as deployment "
        f"authority without scoping it to a serving-API self-deploy: {offenders}. "
        "Ordinary delivery drives over the connection holding the run row, "
        "HTTPS included; say so, and let the executor's refusal name the "
        "admin connection for the self-deploy case."
    )


def test_the_scan_sees_the_wording_it_exists_to_catch() -> None:
    """A guard that matches nothing would pass on a fully stale tree."""
    stale = (
        "The HTTPS environment is the normal relayed authority; a "
        "local-Postgres `*-db-admin` environment is write authority for "
        "break-glass SQL and command-shaped deploy surfaces."
    )
    lowered = stale.lower()
    assert DB_ADMIN_LABEL in lowered
    assert any(phrase in lowered for phrase in DEPLOY_OPERATION_PHRASES)
    assert not any(qualifier in lowered for qualifier in SELF_DEPLOY_QUALIFIERS)


class TestTheExecuteRecipeRuntimeTeaching:
    """The recipes the prepared-run hand-off and the Dash gate hand out."""

    def test_a_resolved_connection_is_named_as_selected(self) -> None:
        assert (
            watch_deploy_command("run-20260908-001", "prod")
            == "yoke --env prod watch deploy -- run-20260908-001"
        )

    def test_an_unresolved_connection_teaches_the_shape(self) -> None:
        recipe = watch_deploy_command("run-20260908-001")
        assert CONTROL_PLANE_ENV_PLACEHOLDER in recipe
        assert DB_ADMIN_LABEL not in recipe

    def test_an_admin_connection_selected_by_the_operator_is_preserved(self) -> None:
        """Naming it is wrong only as a default, never as the active choice."""
        recipe = watch_deploy_command("run-20260908-001", "prod-db-admin")
        assert recipe == "yoke --env prod-db-admin watch deploy -- run-20260908-001"

    def test_a_missing_run_is_not_redirected_to_database_authority(self) -> None:
        message = run_not_found_message("run-20260908-001")
        assert DB_ADMIN_LABEL not in message
        assert "`--env` selecting that control plane" in message


class TestTheAdministratorExceptionSurvives:
    """Scrubbing the default must not erase the case that is genuinely true."""

    @pytest.mark.parametrize(
        "teaching",
        [CREATE_DESCRIPTION, WATCH_DEPLOY_DESCRIPTION, ITEMLESS_RELEASE_RECIPE],
        ids=["create", "watch-deploy", "itemless-recipe"],
    )
    def test_the_self_deploy_case_still_names_its_admin_connection(
        self, teaching: str
    ) -> None:
        lowered = teaching.lower()
        assert DB_ADMIN_LABEL in lowered
        assert any(qualifier in lowered for qualifier in SELF_DEPLOY_QUALIFIERS)

    def test_ordinary_delivery_is_taught_as_the_transport_it_uses(self) -> None:
        assert "HTTPS" in CREATE_DESCRIPTION
        assert "HTTPS" in ITEMLESS_RELEASE_RECIPE
