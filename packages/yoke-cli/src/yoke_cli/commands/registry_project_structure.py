"""Project-structure entries for the aggregate ``yoke`` registry."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters


AdapterFn = Callable[[List[str]], int]


PROJECT_STRUCTURE_SUBCOMMAND_REGISTRY: Dict[
    Tuple[str, ...], Tuple[str, AdapterFn]
] = {
    ("project-structure", "patch", "apply"):
        ("project_structure.patch.apply",
         _adapters.project_structure_patch_apply),
    ("project-structure", "deploy-defaults", "get"):
        ("project_structure.deploy_defaults.get",
         _adapters.project_structure_deploy_defaults_get),
}


__all__ = ["PROJECT_STRUCTURE_SUBCOMMAND_REGISTRY"]
