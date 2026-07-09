from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]

SURFACES = (
    "README.md",
    "docs/local-setup.md",
    "docs/onboard-external-project.md",
    "docs/OVERVIEW.md",
    "packages/yoke-cli/src/yoke_cli/config/onboard_github_copy.py",
    "packages/yoke-cli/src/yoke_cli/config/onboard_wizard_flow_github.py",
    "packages/yoke-cli/src/yoke_cli/config/onboard_wizard_flow_publish.py",
    "packages/yoke-cli/src/yoke_cli/config/onboard_wizard_steps.py",
)

FORBIDDEN_LEGACY_TOKEN_SETUP_COPY = (
    "--github-adoption store-token",
    "--github-adoption temporary-only",
    "--github-adoption different-token",
    "GitHub Personal " "Access Token",
    "personal " "access " "token",
    "Paste your GitHub " "token",
    "project `github.token`",
    "stores the provided token",
    "stored project GitHub " "tokens",
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
