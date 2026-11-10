"""Run a Pulumi stack from the project's checked-in ``infra/Pulumi.<stack>.yaml``.

When the selected source tree carries a stack file for the requested stack,
``yoke pulumi exec`` takes this file-backed path: it copies the whole
``infra/`` directory to a private temp dir, adds Yoke-owned values to the
copy of that stack file under the reserved ``yoke:`` config namespace, and
runs Pulumi there. The project's checkout is only read, never written.
The copy keeps the tree's symlinks (a linked virtualenv keeps working), so
a stack file that is itself a symlink is refused: Yoke and ``pulumi stack
init`` write the copied stack file, and a write through the link would
change its target. Nothing writes the copied ``Pulumi.yaml``.

The stack file is authoritative for every project value, including its
``secretsprovider`` and ``encryptedkey`` lines. Yoke inserts its own keys
as text, so the file's other entries keep their exact spelling, quoting and
comments; nothing is defaulted, re-typed or blanked. The only ``yoke:`` key
the file may set is ``yoke:github_access`` (metadata, variables or
runner_fleet; unset means metadata). Values are never delivered as
``--config`` flags (Pulumi persists those into the stack file) or as
environment variables (programs do not read those as config).

A stack without such a file still takes the rendered path. That dual path
is temporary: the purge item that follows removes the rendered path, its
templates, key allowlists and stack-kind table, once consumers have moved.
"""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
import re
import shutil

import yaml

from yoke_core.domain.pack_pulumi_sources import (
    PULUMI_PROGRAM_SUBDIRECTORY,
    pulumi_program_source,
)
from yoke_core.domain.pulumi_file_stack_values import (
    GITHUB_ACCESS_KEY,
    GITHUB_ACCESS_PERMISSIONS,
    METADATA_ACCESS,
    YOKE_CONFIG_NAMESPACE,
)
from yoke_core.tools.pulumi_exec_types import PulumiExecError


_STACK_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_ACCESS_CONFIG_KEY = f"{YOKE_CONFIG_NAMESPACE}:{GITHUB_ACCESS_KEY}"


def file_backed_stack_path(project_root: Path, stack: str) -> Path | None:
    """Return the checked-in stack file for ``stack``, or None for rendered."""
    if not _STACK_NAME.fullmatch(stack) or ".." in stack:
        return None
    path = pulumi_program_source(project_root, f"Pulumi.{stack}.yaml")
    return path if path.is_file() else None


def file_stack_github_access(stack_file: Path) -> str:
    """Validate the stack file's ``yoke:`` keys and return its GitHub level."""
    config = _stack_config(stack_file)
    reserved = sorted(
        key for key in config
        if str(key).split(":", 1)[0] == YOKE_CONFIG_NAMESPACE
        and str(key) != _ACCESS_CONFIG_KEY
    )
    if reserved:
        raise PulumiExecError(
            f"pulumi_yoke_namespace_reserved: {stack_file} sets "
            f"{', '.join(reserved)}; the {YOKE_CONFIG_NAMESPACE}: namespace "
            f"belongs to Yoke and a stack file may set only {_ACCESS_CONFIG_KEY}. "
            "Rename those keys under your own Pulumi project namespace and retry"
        )
    if _ACCESS_CONFIG_KEY not in config:
        return METADATA_ACCESS
    access = config[_ACCESS_CONFIG_KEY]
    if not isinstance(access, str) or access not in GITHUB_ACCESS_PERMISSIONS:
        raise PulumiExecError(
            f"pulumi_github_access_unknown: {stack_file} sets "
            f"{_ACCESS_CONFIG_KEY} to {access!r}; use one of "
            f"{', '.join(GITHUB_ACCESS_PERMISSIONS)} or remove it for "
            f"{METADATA_ACCESS}"
        )
    return access


def stage_file_backed_infra(
    project_root: Path,
    stack: str,
    destination: Path,
    yoke_values: Mapping[str, str] | None,
) -> Path:
    """Copy ``infra/`` to ``destination`` and merge ``yoke_values`` into it.

    Returns the copied ``infra`` directory Pulumi runs in.
    """
    source = project_root / PULUMI_PROGRAM_SUBDIRECTORY
    infra = destination / PULUMI_PROGRAM_SUBDIRECTORY
    _refuse_yoke_project_name(source / "Pulumi.yaml")
    _refuse_linked_stack_file(source / f"Pulumi.{stack}.yaml")
    shutil.copytree(source, infra, symlinks=True)
    if yoke_values:
        stack_path = infra / f"Pulumi.{stack}.yaml"
        original = stack_path.read_text(encoding="utf-8")
        merged = merge_yoke_config(original, yoke_values, source=stack_path)
        stack_path.write_text(merged, encoding="utf-8")
        stack_path.chmod(0o600)
    return infra


def merge_yoke_config(
    text: str, yoke_values: Mapping[str, str], *, source: Path
) -> str:
    """Insert ``yoke:`` entries into a stack file's ``config`` mapping as text."""
    entries = {
        f"{YOKE_CONFIG_NAMESPACE}:{key}": str(value)
        for key, value in sorted(yoke_values.items())
    }
    root = _compose(text, source)
    config_node = None
    if root is not None:
        for key_node, value_node in root.value:
            if key_node.value == "config":
                config_node = value_node
    if config_node is None:
        block = "".join(f"  {_scalar(k)}: {_scalar(v)}\n" for k, v in entries.items())
        separator = "" if not text or text.endswith("\n") else "\n"
        merged = f"{text}{separator}config:\n{block}"
    elif isinstance(config_node, yaml.MappingNode) and not config_node.flow_style:
        first_key = config_node.value[0][0].start_mark
        line_start = text.rfind("\n", 0, first_key.index) + 1
        indent = " " * first_key.column
        block = "".join(
            f"{indent}{_scalar(k)}: {_scalar(v)}\n" for k, v in entries.items()
        )
        merged = text[:line_start] + block + text[line_start:]
    elif isinstance(config_node, yaml.MappingNode):
        flow = ", ".join(f"{_scalar(k)}: {_scalar(v)}" for k, v in entries.items())
        opening = config_node.start_mark.index + 1
        joiner = ", " if config_node.value else ""
        merged = text[:opening] + flow + joiner + text[opening:]
    elif (
        isinstance(config_node, yaml.ScalarNode)
        and config_node.tag == "tag:yaml.org,2002:null"
    ):
        flow = ", ".join(f"{_scalar(k)}: {_scalar(v)}" for k, v in entries.items())
        start, end = config_node.start_mark.index, config_node.end_mark.index
        pad = "" if start and text[start - 1] in " \t" else " "
        merged = text[:start] + pad + "{" + flow + "}" + text[end:]
    else:
        raise PulumiExecError(
            f"pulumi_stack_file_invalid: {source} config must be a mapping; "
            "repair the stack file and retry"
        )
    _assert_merged(text, merged, entries, source)
    return merged


def _assert_merged(
    original: str, merged: str, entries: Mapping[str, str], source: Path
) -> None:
    before = _config_mapping(yaml.safe_load(original) or {}, source)
    after = _config_mapping(yaml.safe_load(merged) or {}, source)
    if after != {**before, **entries}:
        raise PulumiExecError(
            f"pulumi_stack_file_merge_failed: Yoke could not add its "
            f"{YOKE_CONFIG_NAMESPACE}: values to {source} without changing "
            "other entries; rewrite its config as a plain block mapping and retry"
        )


def _stack_config(stack_file: Path) -> dict:
    text = stack_file.read_text(encoding="utf-8")
    _compose(text, stack_file)
    return _config_mapping(yaml.safe_load(text) or {}, stack_file)


def _config_mapping(document: object, source: Path) -> dict:
    if not isinstance(document, dict):
        raise PulumiExecError(
            f"pulumi_stack_file_invalid: {source} must be a YAML mapping; "
            "repair the stack file and retry"
        )
    config = document.get("config") or {}
    if not isinstance(config, dict):
        raise PulumiExecError(
            f"pulumi_stack_file_invalid: {source} config must be a mapping; "
            "repair the stack file and retry"
        )
    return config


def _compose(text: str, source: Path) -> yaml.MappingNode | None:
    try:
        root = yaml.compose(text, Loader=yaml.SafeLoader)
    except yaml.YAMLError as exc:
        raise PulumiExecError(
            f"pulumi_stack_file_invalid: {source} is not valid YAML ({exc}); "
            "repair the stack file and retry"
        ) from exc
    if root is not None and not isinstance(root, yaml.MappingNode):
        raise PulumiExecError(
            f"pulumi_stack_file_invalid: {source} must be a YAML mapping; "
            "repair the stack file and retry"
        )
    return root


def _refuse_linked_stack_file(stack_file: Path) -> None:
    if stack_file.is_symlink():
        raise PulumiExecError(
            f"pulumi_stack_file_symlink: {stack_file} is a symlink; Yoke "
            "writes its own values into the copied stack file and a write "
            "through the link would change the link target. Replace the "
            "link with a regular file holding the same content and retry"
        )


def _refuse_yoke_project_name(pulumi_yaml: Path) -> None:
    try:
        declaration = yaml.safe_load(pulumi_yaml.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PulumiExecError(
            f"pulumi_project_file_invalid: {pulumi_yaml} could not be read "
            f"({exc}); add a valid Pulumi.yaml beside the stack file and retry"
        ) from exc
    name = declaration.get("name") if isinstance(declaration, dict) else None
    if name == YOKE_CONFIG_NAMESPACE:
        raise PulumiExecError(
            f"pulumi_yoke_namespace_reserved: {pulumi_yaml} names the Pulumi "
            f"project {YOKE_CONFIG_NAMESPACE!r}, whose config keys collide with "
            "Yoke's reserved namespace; rename the Pulumi project and retry"
        )


def _scalar(value: str) -> str:
    """Quote one string as a YAML double-quoted scalar (JSON is valid YAML)."""
    return json.dumps(value)


__all__ = [
    "file_backed_stack_path",
    "file_stack_github_access",
    "merge_yoke_config",
    "stage_file_backed_infra",
]
