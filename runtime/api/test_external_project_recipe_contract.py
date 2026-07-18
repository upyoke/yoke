"""Clean-room contract for project-installed Yoke teaching."""

from __future__ import annotations

import json
import re
from pathlib import Path

from yoke_cli.commands import registry
from yoke_core.domain.deployment_flow_seed_data import SEED_FLOWS


REPO = Path(__file__).resolve().parents[2]
CHECKOUT_ONLY = re.compile(
    r"python3 -m (?:runtime\.api|yoke_core\.cli\.db_router|"
    r"yoke_core\.api\.service_client)"
)


def _teaching_files() -> list[Path]:
    roots = [
        REPO / ".agents" / "skills" / "yoke",
        REPO / "runtime" / "agents",
        REPO / "runtime" / "harness" / "claude" / "rules",
        REPO / "runtime" / "harness" / "claude" / "agents",
        REPO / "runtime" / "harness" / "codex" / "agents",
        REPO / "packages" / "yoke-core" / "src" / "yoke_core"
        / "install_bundle_tree",
    ]
    files: list[Path] = []
    for root in roots:
        files.extend(path for path in root.rglob("*") if path.is_file())
    files.extend(
        (REPO / "packages" / "yoke-core" / "src" / "yoke_core" / "domain")
        .glob("schema_api_context*.py")
    )
    return sorted(set(files))


def test_external_project_teaching_has_no_checkout_only_control_plane_recipe() -> None:
    residue = []
    for path in _teaching_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        if CHECKOUT_ONLY.search(text):
            residue.append(str(path.relative_to(REPO)))
    assert residue == []


def test_recipe_repairs_and_registered_surfaces_stay_taught() -> None:
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert "uv run --frozen ruff check <changed Python paths>" in agents
    assert "Use `-- -n 0`" in agents
    assert "Never pass an optional unmatched path glob" in agents
    assert "Never fabricate or expand a full commit hash" in agents
    assert "cat-file -e '<sha>^{commit}'" in agents
    assert "git diff --name-only --diff-filter=ACMR <base>...HEAD" in agents
    assert "Do not pipe NUL-delimited Git output through `rg -z`" in agents
    expected = {
        ("ephemeral-env", "create"),
        ("workflow-item", "epic-dispatch-chain", "advance"),
        ("deployment-runs", "start-for-item"),
        ("deployment-flows", "update-stages"),
        ("ouroboros", "wrapup", "save"),
        ("projects", "infrastructure", "list"),
    }
    assert expected <= set(registry.SUBCOMMAND_REGISTRY)


def test_buzz_seed_flows_include_explicit_smoke_completion() -> None:
    flows = {str(flow["id"]): flow for flow in SEED_FLOWS}
    release = json.loads(flows["buzz-production-release"]["stages"])
    hotfix = json.loads(flows["buzz-production-hotfix"]["stages"])
    assert [stage.get("name") or stage.get("kind") for stage in release] == [
        "migration_apply", "merged", "prod-deploy", "smoke", "complete",
    ]
    assert [stage.get("name") or stage.get("kind") for stage in hotfix] == [
        "migration_apply", "merged", "production-deploy", "smoke", "complete",
    ]


def test_atlas_names_real_pulumi_client_local_source_owners() -> None:
    owners = (
        "packages/yoke-cli/src/yoke_cli/commands/adapters/pulumi.py",
        "packages/yoke-core/src/yoke_core/tools/pulumi_exec.py",
    )
    atlas = (REPO / "docs" / "atlas.md").read_text(encoding="utf-8")
    for owner in owners:
        assert (REPO / owner).is_file()
        assert owner in atlas


def test_webapp_deploy_templates_use_capability_owned_pulumi_bootstrap() -> None:
    paths = (
        REPO / "templates" / "webapp" / "SETUP-DEPLOYMENT.md",
        REPO / "templates" / "webapp" / "ops" / "DEPLOY.md",
        REPO / "templates" / "webapp" / "ops" / "DEPLOY-CHECKLIST.md",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "yoke pulumi exec --project {{project_name}} --stack" in text
        assert "-- init --secrets-provider 'awskms://" in text
        assert "-- preview" in text
        assert "-- up --yes --non-interactive" in text
        assert "AWS_PROFILE=" not in text
    combined = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    assert "0700" in combined
    assert "typed operator-state" in combined
    assert "No repo-local infrastructure checkout" in combined
