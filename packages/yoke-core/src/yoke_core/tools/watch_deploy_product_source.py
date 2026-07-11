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
    """Validate product authority and inject its canonical tag and path."""
    args = list(deploy_args)
    image_tag = _single_option(args, "--image-tag", required=False)
    source = validate_product_source(product_root, image_tag or "")
    args = _replace_or_append_option(args, "--image-tag", source.image_tag)
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


def _replace_or_append_option(
    args: Sequence[str],
    name: str,
    value: str,
) -> list[str]:
    """Replace one validated option in place, or append it when absent."""
    result: list[str] = []
    prefix = f"{name}="
    replaced = False
    index = 0
    while index < len(args):
        token = args[index]
        if token.startswith(prefix):
            result.append(f"{name}={value}")
            replaced = True
            index += 1
            continue
        if token == name:
            result.extend([name, value])
            replaced = True
            index += 2
            continue
        result.append(token)
        index += 1
    if not replaced:
        result.extend([name, value])
    return result


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
