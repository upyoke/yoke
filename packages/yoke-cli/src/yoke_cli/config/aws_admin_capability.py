"""Client-side surface for a project's ``aws-admin`` hosting capability.

Three concerns, one place because they are one story: where the operator gets
the credential (the CloudFormation quick-create link), where its two values
live once pasted (machine-local, owner-only), and how Yoke proves they work
(a redacted ``sts get-caller-identity`` probe).

Custody: the pair is a broad, operator-attended bootstrap credential. It stays
on this machine under ``~/.yoke/secrets/capability-secrets/<slug>/aws-admin/``
and is never echoed back. CI never receives it — deploys federate through
short-lived OIDC roles Yoke provisions from it later.

The store and probe live in the engine (``yoke_core.domain``), which ships
beside the client but only runs when the caller reaches for it, so both are
imported dynamically at the call site (see the classified roster in
``runtime.api.dynamic_authority_import_allowlist``).
"""

from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from yoke_cli.config import install_binding
from yoke_contracts.api_urls import DISTRIBUTION_BASE_URL_ENV, DISTRIBUTION_PROD_URL
from yoke_contracts.machine_config import capability_secrets as secret_contract
from yoke_contracts.machine_config import runtime as machine_runtime
from yoke_contracts.machine_config import schema as machine_schema

CAPABILITY_TYPE = secret_contract.AWS_ADMIN_CAPABILITY
ACCESS_KEY_ID_KEY = "access_key_id"
SECRET_ACCESS_KEY_KEY = "secret_access_key"

# CloudFormation stack the one-click link creates, and the region the console
# opens in when the shell names none.
BOOTSTRAP_STACK_NAME = "yoke-aws-admin"
BOOTSTRAP_TEMPLATE_FILENAME = "yoke-aws-admin.yaml"
DEFAULT_REGION = "us-east-1"
_REGION_ENV_VARS = ("AWS_REGION", "AWS_DEFAULT_REGION")

class HostingCredentialError(RuntimeError):
    """Storing the pasted hosting credential failed."""


class HostingVerificationError(RuntimeError):
    """The stored hosting credential did not pass the caller-identity check."""


@dataclass(frozen=True)
class CallerIdentity:
    """The redacted evidence a caller-identity check returns."""

    account: str
    identity: str


def default_region() -> str:
    """Region for the bootstrap link and the identity probe.

    The ambient AWS region wins when the shell names one, so an operator who
    already works in a region does not get a us-east-1 stack by surprise.
    """
    for name in _REGION_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return DEFAULT_REGION


def distribution_base_url() -> str:
    """Distribution host serving this build's published artifacts."""
    return (
        os.environ.get(DISTRIBUTION_BASE_URL_ENV, "").strip().rstrip("/")
        or DISTRIBUTION_PROD_URL
    )


def build_version() -> str:
    """Version of the running build, or ``""`` when it owns no wheel metadata."""
    return install_binding.distribution_version()


def template_url(*, version: str | None = None, base_url: str | None = None) -> str | None:
    """URL of the bootstrap template published with this exact build.

    ``None`` when the running code has no released version (a source checkout):
    nothing is published for it, so there is no honest URL to hand AWS.
    """
    resolved_version = (version if version is not None else build_version()).strip()
    if not resolved_version:
        return None
    base = (base_url or distribution_base_url()).rstrip("/")
    return (
        f"{base}/dist/releases/{quote(resolved_version, safe='%')}"
        f"/{BOOTSTRAP_TEMPLATE_FILENAME}"
    )


def quick_create_url(
    *,
    region: str | None = None,
    version: str | None = None,
    base_url: str | None = None,
) -> str | None:
    """CloudFormation quick-create URL for the bootstrap stack, or ``None``.

    ``None`` propagates from :func:`template_url` — a build with no published
    template cannot offer a one-click link.
    """
    template = template_url(version=version, base_url=base_url)
    if template is None:
        return None
    resolved_region = (region or default_region()).strip() or DEFAULT_REGION
    # The nested template URL keeps its ``:`` and ``/`` literal: they are legal
    # fragment characters, it carries no ``&`` or ``#`` to confuse the console's
    # parser, and an operator has to be able to read the link Yoke asks them to
    # open. Everything else is still escaped.
    return (
        f"https://console.aws.amazon.com/cloudformation/home?region={resolved_region}"
        f"#/stacks/quickcreate?stackName={BOOTSTRAP_STACK_NAME}"
        f"&templateURL={quote(template, safe=':/')}"
    )


def credential_dir(project_slug: str) -> Path:
    """Machine-local directory holding the project's aws-admin secret files."""
    return (
        machine_runtime.yoke_home()
        / machine_schema.SECRETS_DIR_NAME
        / secret_contract.capability_secret_directory_relative_path(
            project_slug, CAPABILITY_TYPE,
        )
    )


def credential_dir_display(project_slug: str) -> str:
    """The credential directory as an operator reads it: ``~``-relative, trailing ``/``.

    Custody copy names this path on screen, so it must read the same on every
    machine rather than leaking whoever's home directory the wizard runs in.
    """
    slug = str(project_slug or "").strip()
    if not slug:
        return ""
    directory = credential_dir(slug)
    try:
        return f"~/{directory.relative_to(Path.home())}/"
    except (OSError, ValueError):
        return f"{directory}/"


def credential_saved(project_slug: str) -> bool:
    """Whether both halves of the pair are already on this machine."""
    slug = str(project_slug or "").strip()
    if not slug:
        return False
    try:
        directory = credential_dir(slug)
    except (OSError, ValueError):
        return False
    return all(
        (directory / key).is_file()
        for key in (ACCESS_KEY_ID_KEY, SECRET_ACCESS_KEY_KEY)
    )


def store_credential(
    project_slug: str,
    *,
    access_key_id: str,
    secret_access_key: str,
) -> list[Path]:
    """Write both values owner-only under the machine secrets root."""
    try:
        machine_secrets = importlib.import_module(
            "yoke_core.domain.capability_machine_secrets"
        )
        return [
            machine_secrets.store_machine_capability_secret(
                project_slug, CAPABILITY_TYPE, key, value,
            )
            for key, value in (
                (ACCESS_KEY_ID_KEY, access_key_id),
                (SECRET_ACCESS_KEY_KEY, secret_access_key),
            )
        ]
    except Exception as exc:  # noqa: BLE001 - surfaced as a wizard error screen
        raise HostingCredentialError(
            f"Yoke could not store the AWS credential ({type(exc).__name__})."
        ) from exc


def verify_caller_identity(project_slug: str, region: str) -> CallerIdentity:
    """Prove the stored pair works through boto3, returning redacted facts."""
    verifier = None
    try:
        verifier = importlib.import_module(
            "yoke_core.domain.aws_machine_caller_identity"
        )
        identity = verifier.verify_machine_caller_identity(project_slug, region)
    except Exception as exc:  # noqa: BLE001 - surfaced as a wizard error screen
        expected = getattr(verifier, "CallerIdentityVerificationError", ())
        detail = str(exc) if expected and isinstance(exc, expected) else (
            f"Yoke could not verify the AWS credential ({type(exc).__name__})."
        )
        raise HostingVerificationError(detail) from exc
    return CallerIdentity(account=identity.account, identity=identity.identity)


__all__ = [
    "ACCESS_KEY_ID_KEY",
    "BOOTSTRAP_STACK_NAME",
    "BOOTSTRAP_TEMPLATE_FILENAME",
    "CAPABILITY_TYPE",
    "CallerIdentity",
    "DEFAULT_REGION",
    "HostingCredentialError",
    "HostingVerificationError",
    "SECRET_ACCESS_KEY_KEY",
    "build_version",
    "credential_dir",
    "credential_dir_display",
    "credential_saved",
    "default_region",
    "distribution_base_url",
    "quick_create_url",
    "store_credential",
    "template_url",
    "verify_caller_identity",
]
