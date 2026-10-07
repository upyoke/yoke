"""Materialize the self-host compose bundle into an operator directory.

``yoke self-host init`` writes a runnable ``docker compose`` working
directory: the wheel-carried compose file, an ``.env`` with the image
reference and API publish spec, and generated database credentials as
owner-only secret files. The compose file itself is static package data;
every per-install knob — including the installer's name that first boot
gives the first admin — rides ``.env`` or ``secrets/``.

Secret handling: the Postgres password is generated hex-only and never
printed or returned — compose interpolates ``$`` inside ``.env`` values,
so credentials live in host-opened stdin handoffs to private runtime files, never in ``.env``.
"""

from __future__ import annotations

import secrets
from importlib import resources
from pathlib import Path
from typing import Any, Dict, Optional

from yoke_cli.self_host import first_boot_token
from yoke_cli.self_host import protection
from yoke_cli.self_host import release_target
from yoke_cli.self_host import secure_layout
from yoke_cli.self_host.secure_layout import SECRETS_DIR_NAME
from yoke_cli.self_host.env_template import env_text
from yoke_contracts.first_admin_name import AdminNameError, validate_admin_name
from yoke_contracts.self_host_handoff import HANDOFF_TIMEOUT_SECONDS

#: Default bundle directory, created under the invoking directory. The
#: bundle is an operator-managed working directory (``docker compose``
#: up/logs/pull all run from it), so it stays visible where the operator
#: ran init rather than hiding under the machine home, which holds
#: client-side config for this machine's CLI — not server deployments.
DEFAULT_BUNDLE_DIR = "yoke-server"
DEFAULT_API_PORT = 8765

COMPOSE_FILE_NAME = "docker-compose.yml"
ENV_FILE_NAME = ".env"
GITIGNORE_FILE_NAME = ".gitignore"
DB_PASSWORD_FILE_NAME = "db-password"
DSN_FILE_NAME = "dsn"

#: Operator-owned inputs and the token delivered back to the host command.
BUNDLE_SECRET_NAMES = (
    DB_PASSWORD_FILE_NAME,
    DSN_FILE_NAME,
    first_boot_token.FIRST_BOOT_TOKEN_FILE_NAME,
)

_DB_NAME = "yoke"
_DB_USER = "yoke"
_PASSWORD_ENTROPY_BYTES = 32


class SelfHostBundleError(RuntimeError):
    """The self-host bundle could not be materialized."""


def bundle_file_paths(target: Path) -> tuple[Path, ...]:
    """Every path the bundle writer owns inside ``target``."""
    secrets_dir = target / SECRETS_DIR_NAME
    return (
        target / COMPOSE_FILE_NAME,
        target / ENV_FILE_NAME,
        target / GITIGNORE_FILE_NAME,
        *(secrets_dir / name for name in BUNDLE_SECRET_NAMES),
    )


def _bundle_payload_paths(target: Path) -> tuple[Path, ...]:
    """Paths whose replacement can change a running bundle's identity."""
    return tuple(
        path for path in bundle_file_paths(target) if path.name != GITIGNORE_FILE_NAME
    )


def write_bundle(
    *,
    directory: Optional[str] = None,
    port: Optional[int] = None,
    image: Optional[str] = None,
    image_repository: str | None = None,
    admin_name: str | None = None,
    force: bool = False,
) -> Dict[str, Any]:
    """Write the compose bundle; refuse to clobber unless ``force``.

    Returns a report safe to print: paths, image, publish spec — never
    the generated password or DSN.
    """
    target = Path(directory or DEFAULT_BUNDLE_DIR).expanduser()
    try:
        selected_admin_name = validate_admin_name(admin_name)
    except AdminNameError as exc:
        raise SelfHostBundleError(
            f"{exc}. Pass --admin-name with your name; first boot creates "
            "this universe's first admin as that person"
        ) from None
    selected_port = int(port or DEFAULT_API_PORT)
    matched_release = None
    if image is None:
        try:
            matched_release = (
                release_target.current_release_target(image_repository=image_repository)
                if image_repository is not None
                else release_target.current_release_target()
            )
        except release_target.ReleaseTargetError as exc:
            raise SelfHostBundleError(
                "could not select the server image matched to this CLI: "
                f"{exc}. Restore distribution access and retry, or pass "
                "--image with an exact immutable image reference"
            ) from exc
    selected_image = str(image or matched_release.image)
    _prepare_layout(target, create=True)
    existing = [p for p in _bundle_payload_paths(target) if p.exists()]
    if existing and not force:
        listing = ", ".join(str(p) for p in existing)
        raise SelfHostBundleError(
            f"bundle files already exist ({listing}). Use "
            "--protect-existing to add or repair secret protection without "
            "rewriting configuration or regenerating database credentials. "
            "Use --force only to rewrite the bundle and regenerate database "
            "credentials; an initialized Postgres volume keeps its original "
            "password"
        )

    try:
        protection.assert_sensitive_paths_untracked(target)
    except protection.SelfHostProtectionError as exc:
        raise SelfHostBundleError(str(exc)) from exc

    publish_spec = f"127.0.0.1:{selected_port}"
    password = secrets.token_hex(_PASSWORD_ENTROPY_BYTES)
    dsn = f"host=db port=5432 dbname={_DB_NAME} user={_DB_USER} password={password}"

    try:
        gitignore_changed = protection.reconcile_gitignore(target / GITIGNORE_FILE_NAME)
    except protection.SelfHostProtectionError as exc:
        raise SelfHostBundleError(str(exc)) from exc

    secrets_dir = target / SECRETS_DIR_NAME
    try:
        _write_bundle_file(target / COMPOSE_FILE_NAME, _compose_text())
        _write_bundle_file(
            target / ENV_FILE_NAME,
            env_text(
                image=selected_image,
                publish_spec=publish_spec,
                admin_name=selected_admin_name,
            ),
        )
        _write_secret_file(secrets_dir / DB_PASSWORD_FILE_NAME, password)
        _write_secret_file(secrets_dir / DSN_FILE_NAME, dsn)
    except protection.SelfHostProtectionError as exc:
        raise SelfHostBundleError(str(exc)) from exc

    return {
        "ok": True,
        "directory": str(target.resolve()),
        "files": [str(p) for p in bundle_file_paths(target)],
        "image": selected_image,
        "matched_cli_version": matched_release.version if matched_release else None,
        "source_commit": matched_release.source_commit if matched_release else None,
        "publish": publish_spec,
        "port": selected_port,
        "admin_name": selected_admin_name,
        "forced": bool(existing),
        "mode": "init",
        "gitignore_changed": gitignore_changed,
        "credentials_regenerated": True,
    }


def protect_existing_bundle(
    *,
    directory: Optional[str] = None,
    github_app_private_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Protect an existing bundle without rewriting it or its DB secrets."""
    target = Path(directory or DEFAULT_BUNDLE_DIR).expanduser()
    _prepare_layout(target, create=False)
    try:
        secure_layout.validate_existing_bundle_files(
            target,
            public_names=(COMPOSE_FILE_NAME, ENV_FILE_NAME),
            secret_names=_existing_secret_names(target),
        )
        protection.assert_sensitive_paths_untracked(target)
    except (
        protection.SelfHostProtectionError,
        secure_layout.SecureLayoutError,
    ) as exc:
        raise SelfHostBundleError(str(exc)) from exc

    try:
        protection.assert_sensitive_paths_untracked(target)
        gitignore_changed = protection.reconcile_gitignore(target / GITIGNORE_FILE_NAME)
        if (target / COMPOSE_FILE_NAME).read_text(encoding="utf-8") != _compose_text():
            _write_bundle_file(target / COMPOSE_FILE_NAME, _compose_text())
        key_path = None
        if github_app_private_key is not None:
            key_path = protection.install_github_app_private_key(
                secrets_dir=target / SECRETS_DIR_NAME,
                source=Path(github_app_private_key),
            )
    except protection.SelfHostProtectionError as exc:
        raise SelfHostBundleError(str(exc)) from exc

    files = [str(target / GITIGNORE_FILE_NAME)]
    if key_path is not None:
        files.append(str(key_path))
    return {
        "ok": True,
        "directory": str(target.resolve()),
        "files": files,
        "mode": "protect-existing",
        "gitignore_changed": gitignore_changed,
        "credentials_regenerated": False,
        "github_app_private_key_installed": key_path is not None,
    }


def validate_existing_bundle(*, directory: Optional[str] = None) -> Path:
    """Return one safely validated existing compose working directory."""
    target = Path(directory or DEFAULT_BUNDLE_DIR).expanduser()
    _prepare_layout(target, create=False)
    try:
        secure_layout.validate_existing_bundle_files(
            target,
            public_names=(COMPOSE_FILE_NAME, ENV_FILE_NAME),
            secret_names=_existing_secret_names(target),
        )
        protection.assert_sensitive_paths_untracked(target)
    except (
        first_boot_token.FirstBootTokenError,
        protection.SelfHostProtectionError,
        secure_layout.SecureLayoutError,
    ) as exc:
        raise SelfHostBundleError(str(exc)) from exc
    return target.resolve()


def _existing_secret_names(target: Path) -> tuple[str, ...]:
    token = first_boot_token.token_drop_path(target)
    return (DB_PASSWORD_FILE_NAME, DSN_FILE_NAME) + (
        (token.name,) if token.exists() or token.is_symlink() else ()
    )


def _compose_text() -> str:
    return (
        resources.files("yoke_cli.self_host")
        .joinpath(COMPOSE_FILE_NAME)
        .read_text(encoding="utf-8")
        .replace("__HANDOFF_TIMEOUT_SECONDS__", str(HANDOFF_TIMEOUT_SECONDS))
    )


def _write_secret_file(target: Path, value: str) -> None:
    protection.atomic_replace_bytes(
        target,
        (value + "\n").encode("utf-8"),
        mode=0o600,
    )


def _write_bundle_file(target: Path, value: str) -> None:
    protection.atomic_replace_bytes(
        target,
        value.encode("utf-8"),
        mode=0o644,
    )


def _prepare_layout(target: Path, *, create: bool) -> None:
    try:
        protection.assert_bundle_path_safe(target)
        secure_layout.prepare_bundle_layout(target, create=create)
    except (
        protection.SelfHostProtectionError,
        secure_layout.SecureLayoutError,
    ) as exc:
        raise SelfHostBundleError(str(exc)) from exc


__all__ = [
    "BUNDLE_SECRET_NAMES",
    "COMPOSE_FILE_NAME",
    "DB_PASSWORD_FILE_NAME",
    "DEFAULT_API_PORT",
    "DEFAULT_BUNDLE_DIR",
    "DSN_FILE_NAME",
    "ENV_FILE_NAME",
    "GITIGNORE_FILE_NAME",
    "SECRETS_DIR_NAME",
    "SelfHostBundleError",
    "bundle_file_paths",
    "protect_existing_bundle",
    "validate_existing_bundle",
    "write_bundle",
]
