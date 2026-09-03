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

from yoke_cli.config import capability_secrets, install_binding
from yoke_contracts.api_urls import (
    AWS_BOOTSTRAP_TEMPLATE_PROD_URL,
    AWS_BOOTSTRAP_TEMPLATE_STAGE_URL,
    DISTRIBUTION_BASE_URL_ENV,
    DISTRIBUTION_PROD_URL,
    DISTRIBUTION_STAGE_URL,
)
from yoke_contracts.machine_config import capability_secrets as secret_contract
from yoke_contracts.machine_config import runtime as machine_runtime
from yoke_contracts.machine_config import schema as machine_schema

CAPABILITY_TYPE = secret_contract.AWS_ADMIN_CAPABILITY
ACCESS_KEY_ID_KEY = "access_key_id"
SECRET_ACCESS_KEY_KEY = "secret_access_key"
#: Both halves a deploy needs, in the order the credential resolver reads them.
REQUIRED_CREDENTIAL_KEYS = (ACCESS_KEY_ID_KEY, SECRET_ACCESS_KEY_KEY)

# CloudFormation stack the one-click link creates, and the region the console
# opens in when the shell names none.
BOOTSTRAP_STACK_NAME = "yoke-aws-admin"
BOOTSTRAP_TEMPLATE_FILENAME = "yoke-aws-admin.yaml"
DEFAULT_REGION = "us-east-1"
_REGION_ENV_VARS = ("AWS_REGION", "AWS_DEFAULT_REGION")
_BOOTSTRAP_TEMPLATE_URL_BY_DISTRIBUTION = {
    DISTRIBUTION_PROD_URL: AWS_BOOTSTRAP_TEMPLATE_PROD_URL,
    DISTRIBUTION_STAGE_URL: AWS_BOOTSTRAP_TEMPLATE_STAGE_URL,
}
_SUPPORTED_BOOTSTRAP_TEMPLATE_BASE_URLS = frozenset(
    _BOOTSTRAP_TEMPLATE_URL_BY_DISTRIBUTION.values()
)


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


def bootstrap_template_base_url() -> str | None:
    """CloudFormation-compatible S3 origin for the active hosted channel."""
    distribution_url = (
        os.environ.get(DISTRIBUTION_BASE_URL_ENV, "").strip().rstrip("/")
        or DISTRIBUTION_PROD_URL
    )
    return _BOOTSTRAP_TEMPLATE_URL_BY_DISTRIBUTION.get(distribution_url)


def _supported_template_base_url(base_url: str) -> str | None:
    """Return a known regional S3 origin, never an arbitrary template host."""
    normalized = str(base_url or "").strip().rstrip("/")
    if normalized in _SUPPORTED_BOOTSTRAP_TEMPLATE_BASE_URLS:
        return normalized
    return None


def build_version() -> str:
    """Version of the running build, or ``""`` when it owns no wheel metadata."""
    return install_binding.distribution_version()


def template_url(
    *, version: str | None = None, base_url: str | None = None
) -> str | None:
    """URL of the bootstrap template published with this exact build.

    ``None`` when the running code has no released version or its distribution
    channel has no allowlisted regional S3 origin. CloudFormation rejects
    custom distribution and S3 website hosts, so there is no honest one-click
    URL in either case.
    """
    resolved_version = (version if version is not None else build_version()).strip()
    if not resolved_version:
        return None
    candidate = base_url if base_url is not None else bootstrap_template_base_url()
    base = _supported_template_base_url(candidate or "")
    if base is None:
        return None
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
    # open. Everything else is still escaped -- including the ``%`` that already
    # encodes the release's ``+``, so a plus-bearing version reaches the console
    # as ``%252B``. That second layer is load-bearing, not redundant: the console
    # decodes this fragment parameter exactly once and hands S3 the ``%2B`` that
    # resolves to the ``+`` key. Emitting a single-encoded ``%2B`` leaves the
    # console a literal ``+``, which S3 reads as a space and answers NoSuchKey.
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


def present_credential_keys(project_slug: str) -> tuple[str, ...]:
    """Which halves of the pair this machine holds, resolver order.

    Presence is read through the same path function the credential resolver
    reads the value with, so "Yoke can find it" and "the file is there" can
    never disagree — the whole point of asking is to tell a missing row apart
    from missing secret material.
    """
    slug = str(project_slug or "").strip()
    if not slug:
        return ()
    present: list[str] = []
    for key in REQUIRED_CREDENTIAL_KEYS:
        try:
            path = capability_secrets.machine_capability_secret_path(
                slug, CAPABILITY_TYPE, key,
            )
        except (OSError, ValueError):
            continue
        if path.is_file():
            present.append(key)
    return tuple(present)


def missing_credential_keys(project_slug: str) -> tuple[str, ...]:
    """Which halves of the pair are absent from this machine."""
    present = set(present_credential_keys(project_slug))
    return tuple(key for key in REQUIRED_CREDENTIAL_KEYS if key not in present)


def credential_saved(project_slug: str) -> bool:
    """Whether both halves of the pair are already on this machine."""
    return not missing_credential_keys(project_slug)


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
    "REQUIRED_CREDENTIAL_KEYS",
    "SECRET_ACCESS_KEY_KEY",
    "build_version",
    "credential_dir",
    "credential_dir_display",
    "credential_saved",
    "default_region",
    "missing_credential_keys",
    "present_credential_keys",
    "bootstrap_template_base_url",
    "quick_create_url",
    "store_credential",
    "template_url",
    "verify_caller_identity",
]
