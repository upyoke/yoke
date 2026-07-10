from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

SURFACES = (
    "README.md",
    "docs/installer-github-app-testing.md",
    "docs/local-setup.md",
    "docs/onboard-external-project.md",
    "docs/OVERVIEW.md",
    "packages/yoke-cli/src/yoke_cli/config/onboard_github_copy.py",
    "packages/yoke-cli/src/yoke_cli/config/onboard_wizard_flow_github.py",
    "packages/yoke-cli/src/yoke_cli/config/onboard_wizard_flow_publish.py",
    "packages/yoke-cli/src/yoke_cli/config/onboard_wizard.py",
    "packages/yoke-cli/src/yoke_cli/config/onboard_wizard_steps.py",
    "packages/yoke-cli/src/yoke_cli/config/onboard.py",
    "packages/yoke-cli/src/yoke_cli/config/onboard_bridge.py",
    "packages/yoke-cli/src/yoke_cli/config/onboard_project.py",
    "packages/yoke-cli/src/yoke_cli/config/project_github_adoption.py",
    "packages/yoke-cli/src/yoke_cli/config/project_onboard.py",
    "packages/yoke-cli/src/yoke_cli/config/project_onboard_support.py",
    "packages/yoke-cli/src/yoke_cli/commands/adapters/project_onboard.py",
)

FORBIDDEN_LEGACY_TOKEN_SETUP_COPY = (
    "--github-adoption store-token",
    "--github-adoption temporary-only",
    "--github-adoption different-token",
    "--github-adoption skip",
    "GitHub Personal " "Access Token",
    "personal " "access " "token",
    "Paste your GitHub " "token",
    "project `github.token`",
    "stores the provided token",
    "stored project GitHub " "tokens",
    "yoke github connect --token-stdin",
    "yoke github connect --token-file",
    "machine-pat",
    "connect_pat",
    "--github-token",
    "--github-token-file",
    "--github-token-stdin",
    "machine_github_token",
    "project_github_token",
    "GITHUB_ADOPTION_STORE_CHOICES",
    "MACHINE_TOKEN_",
    "PROJECT_TOKEN_",
)


def test_onboarding_copy_does_not_teach_legacy_token_setup() -> None:
    offenders: list[str] = []
    for relative in SURFACES:
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_LEGACY_TOKEN_SETUP_COPY:
            if forbidden in text:
                offenders.append(f"{relative}: {forbidden}")

    assert offenders == []
