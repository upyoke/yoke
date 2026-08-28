"""The hosting bootstrap template emits the key pair as stack Outputs."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = REPO_ROOT / "packaging" / "aws" / "yoke-aws-admin.yaml"
ADMIN_LINK_ADAPTER = (
    REPO_ROOT / "packages" / "yoke-cli" / "src" / "yoke_cli" / "commands"
    / "adapters" / "aws.py"
)


def test_bootstrap_template_emits_both_values_as_outputs() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")

    assert "AWS::SecretsManager::Secret" not in text
    assert "CredentialConsoleUrl" not in text
    assert "Retrieve secret value" not in text
    assert "SecretAccessKey:" in text
    assert "!GetAtt YokeAwsAdminAccessKey.SecretAccessKey" in text
    assert "Delete the stack to revoke" in text
    assert "CloudFormation Output" in text
    assert "stack history" in text
    assert "read-only console" in text


def test_admin_link_help_names_outputs_not_secrets_manager() -> None:
    text = ADMIN_LINK_ADAPTER.read_text(encoding="utf-8")

    assert "Secrets Manager" not in text
    assert "stack Outputs" in text
