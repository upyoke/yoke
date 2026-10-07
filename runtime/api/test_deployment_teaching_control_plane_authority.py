"""Product teaching leaves database-admin recipes in the source-dev layer."""

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

# Steering's explicit source-dev guide is read only for Yoke source releases.
SOURCE_DEV_GUIDE = ".agents/skills/yoke/steer/source-dev-delivery.md"
DB_ADMIN_LABEL = DB_ADMIN_ENV_SUFFIX.lstrip("-")


def _shipped_texts() -> list[tuple[str, str]]:
    """Every shipped surface as (label, text), managed blocks extracted."""
    # The packaged rules are entirely product content, including their prefix.
    managed = {(REPO / "AGENTS.md").resolve()}
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


def test_product_surfaces_leave_admin_teaching_to_source_development() -> None:
    offenders = []
    for label, text in _shipped_texts():
        if label.endswith(SOURCE_DEV_GUIDE):
            continue
        for index, line in enumerate(text.splitlines(), start=1):
            if DB_ADMIN_LABEL in line.lower():
                offenders.append(f"{label}:{index}: {line.strip()[:160]}")
    assert offenders == [], (
        "Product installs do not provision database-admin connections. "
        "Teach registered commands and escalation; keep operator recipes "
        f"in the source-dev layer: {offenders}"
    )


def test_source_dev_rules_retain_operator_authority() -> None:
    doctrine = (REPO / "docs/source-dev-doctrine.md").read_text()
    guide = (REPO / SOURCE_DEV_GUIDE).read_text()
    for text in (doctrine, guide):
        assert "prod-db-admin" in text
        assert "yoke dev db-admin setup" in text
    assert "migration rehearse" in doctrine
    assert "db_router query" in doctrine
    assert "--dsn-var APP_DSN" in doctrine
    assert "release_lineage" in guide
    assert "yoke --env prod deployment-runs create" in guide


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


class TestProductDeploymentHelp:
    """Default deployment help keeps operator recovery reachable by escalation."""

    @pytest.mark.parametrize(
        "teaching",
        [CREATE_DESCRIPTION, WATCH_DEPLOY_DESCRIPTION, ITEMLESS_RELEASE_RECIPE],
        ids=["create", "watch-deploy", "itemless-recipe"],
    )
    def test_self_deploy_help_escalates_to_the_operator(self, teaching: str) -> None:
        lowered = teaching.lower()
        assert DB_ADMIN_LABEL not in lowered
        assert "operator" in lowered
        assert "refusal" in lowered or "refuses" in lowered

    def test_ordinary_delivery_is_taught_as_the_transport_it_uses(self) -> None:
        assert "HTTPS" in CREATE_DESCRIPTION
        assert "HTTPS" in ITEMLESS_RELEASE_RECIPE
