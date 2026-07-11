"""Product-source argument validation for the deploy watcher."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from yoke_core.domain.deploy_product_source import validate_product_source


class WatchDeployProductSourceError(ValueError):
    """Pinned watcher arguments are missing, duplicated, or contradictory."""


def prepare_product_deploy_args(
    deploy_args: Sequence[str],
    product_root: Path,
) -> list[str]:
    """Validate the pin and add its product build-context argument once."""
    args = list(deploy_args)
    image_tag = _single_option(args, "--image-tag")
    source = validate_product_source(product_root, image_tag)
    explicit_path = _single_option(
        args,
        "--product-repo-path",
        required=False,
    )
    if explicit_path is None:
        return [*args, "--product-repo-path", source.repo_path]
    if Path(explicit_path).expanduser().resolve() != Path(source.repo_path):
        raise WatchDeployProductSourceError(
            "--product-src conflicts with explicit --product-repo-path"
        )
    return args


def itemless_deploy_requires_product_source(
    deploy_args: Sequence[str],
) -> bool:
    """Return whether deploy arguments select the pinned item-less path."""
    return (
        _single_option(
            deploy_args,
            "--image-tag",
            required=False,
        )
        is not None
    )


def _single_option(
    args: Sequence[str],
    name: str,
    *,
    required: bool = True,
) -> str | None:
    values: list[str] = []
    prefix = f"{name}="
    for index, token in enumerate(args):
        if token.startswith(prefix):
            values.append(token[len(prefix) :])
        elif token == name:
            if index + 1 >= len(args) or args[index + 1].startswith("--"):
                raise WatchDeployProductSourceError(f"{name} requires a value")
            values.append(args[index + 1])
    if len(values) > 1:
        raise WatchDeployProductSourceError(f"{name} may be supplied only once")
    if not values:
        if required:
            raise WatchDeployProductSourceError(
                f"--product-src requires an explicit {name}"
            )
        return None
    value = values[0].strip()
    if not value:
        raise WatchDeployProductSourceError(f"{name} requires a value")
    return value


__all__ = [
    "WatchDeployProductSourceError",
    "itemless_deploy_requires_product_source",
    "prepare_product_deploy_args",
]
