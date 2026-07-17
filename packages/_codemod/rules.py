"""Frozen package-split codemod rules for the transitional carve-out.

The single machine-readable source of truth for the move; the human-reviewable form
is docs/archive/decisions/yoke-package-split/codemod-rules.md. The engine
(apply.py) consumes `slice_renames(name)` / `resolve(old)`; it never hard-codes a
rule.

Design: core is the DEFAULT SINK. So the data is small —
- EXACT_* maps: the carve-outs that LEAVE core (contracts/cli/harness) + the
  dev-fenced cli modules that STAY core. Exact-match, NEVER globs (the 3-way
  machine_config*/project_*/session* stems make a glob unsafe).
- PREFIX_RULES_CORE: the unambiguous core subtrees (domain/engines/routes/tools/
  board/api top-level). Applied only to runtime.api.* not matched by an exact rule.
  Ordered most-specific-first so handlers/migrations beat the domain catch-all.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

# --- contracts carve-out — full, verified against the live tree ---------
EXACT_CONTRACTS: Dict[str, str] = {
    "runtime.api.domain.yoke_function_models": "yoke_contracts.api.function_call",
    # machine_config_contract* total 560 lines -> 3 cap-respecting 1:1 files, not a merge.
    "runtime.api.domain.machine_config_contract": "yoke_contracts.machine_config.schema",
    "runtime.api.domain.machine_config_contract_projects": "yoke_contracts.machine_config.schema_projects",
    "runtime.api.domain.machine_config_contract_example": "yoke_contracts.machine_config.schema_example",
    "runtime.api.domain.field_note_text": "yoke_contracts.field_note_text",
    "runtime.api.domain.project_contract_scaffolds": "yoke_contracts.project_contract.scaffolds",
    # Art cluster: the candidate merges (art_config+config_paths+board_emoji=453,
    # art_shared+art_ascii=355, image_art+image_to_emoji_art=642) exceed the 350-line
    # cap, so each is a cap-respecting 1:1 move to a DISTINCT board_art file (the
    # engine auto-moves them). Only the facade (__init__) and the art_data split are
    # hand-authored. board_art is a package; its members import each other by path.
    "runtime.api.domain.project_contract_art": "yoke_contracts.project_contract.board_art",
    "runtime.api.domain.project_contract_art_shared": "yoke_contracts.project_contract.board_art.render_seed",
    "runtime.api.domain.project_contract_art_ascii": "yoke_contracts.project_contract.board_art.ascii",
    "runtime.api.domain.project_contract_art_mixed": "yoke_contracts.project_contract.board_art.variants",
    "runtime.api.domain.project_contract_art_image_mixed": "yoke_contracts.project_contract.board_art.variants_image",
    "runtime.api.domain.project_contract_art_data": "yoke_contracts.project_contract.board_art._data",
    "runtime.api.domain.project_contract_image_art": "yoke_contracts.project_contract.board_art.image_to_emoji",
    "runtime.api.domain.project_contract_image_art_palette": "yoke_contracts.project_contract.board_art.palette",
    "runtime.api.tools.image_to_emoji_art": "yoke_contracts.project_contract.board_art.image_pipeline",
    "runtime.api.tools.image_to_emoji_art_decode": "yoke_contracts.project_contract.board_art.image_decode",
    "runtime.api.board.art_config": "yoke_contracts.project_contract.board_art.config",
    "runtime.api.board.board_emoji": "yoke_contracts.project_contract.board_art.emoji",
    "runtime.api.board.config_paths": "yoke_contracts.project_contract.board_art.config_paths",
    "runtime.api.domain.harness_hook_ordering": "yoke_contracts.hook_runner.hook_ordering",
}

# New modules that are HAND-merged/split (several olds -> one new, or one old split
# across new files). The engine rewrites their references but does NOT auto-`git mv`
# (the merge/split is authored by hand). board_art is a package facade (__init__).
CONSOLIDATED_NEW_MODULES = {
    # Only the package facade is hand-authored (engine would make a board_art.py
    # module, but board_art is a package needing __init__.py). Every other art
    # module is a 1:1 auto-move; _data moves 1:1 then gets hand-split (extract
    # MIXED_EMOJI_COLUMNS to package-data .txt) after the move.
    "yoke_contracts.project_contract.board_art",  # facade __init__
}

# --- cli carve-out — transcribed from carve-out-cli.md.
# The transport chokepoint split (service_client_structured_api_adapter) is a
# hand-split, not a 1:1 rename, so it is authored directly rather than listed here.
EXACT_CLI: Dict[str, str] = {
    "runtime.api.cli.board_rebuild_output": "yoke_cli.commands.board_rebuild_output",
    "runtime.api.cli.yoke_board_art_variant_command": "yoke_cli.commands.board_art.variant",
    "runtime.api.cli.yoke_board_art_variant_image": "yoke_cli.commands.board_art.image",
    "runtime.api.cli.yoke_board_art_variant_loop": "yoke_cli.commands.board_art.loop",
    "runtime.api.cli.yoke_cli_manifest": "yoke_cli.manifest",
    "runtime.api.cli.yoke_flag_adapters": "yoke_cli.commands.flag_adapters",
    "runtime.api.cli.yoke_flag_adapters_board": "yoke_cli.commands.adapters.board",
    "runtime.api.cli.yoke_flag_adapters_claims": "yoke_cli.commands.adapters.claims",
    "runtime.api.cli.yoke_flag_adapters_claims_read": "yoke_cli.commands.adapters.claims_read",
    "runtime.api.cli.yoke_flag_adapters_config": "yoke_cli.commands.adapters.config",
    "runtime.api.cli.yoke_flag_adapters_config_write": "yoke_cli.commands.adapters.config_write",
    "runtime.api.cli.yoke_flag_adapters_db_claim": "yoke_cli.commands.adapters.db_claim",
    "runtime.api.cli.yoke_flag_adapters_doctor": "yoke_cli.commands.adapters.doctor",
    "runtime.api.cli.yoke_flag_adapters_epic_progress": "yoke_cli.commands.adapters.epic_progress",
    "runtime.api.cli.yoke_flag_adapters_epic_review": "yoke_cli.commands.adapters.epic_review",
    "runtime.api.cli.yoke_flag_adapters_epic_state": "yoke_cli.commands.adapters.epic_state",
    "runtime.api.cli.yoke_flag_adapters_epic_task": "yoke_cli.commands.adapters.epic_task",
    "runtime.api.cli.yoke_flag_adapters_events": "yoke_cli.commands.adapters.events",
    "runtime.api.cli.yoke_flag_adapters_github": "yoke_cli.commands.adapters.github",
    "runtime.api.cli.yoke_flag_adapters_github_actions": "yoke_cli.commands.adapters.github_actions",
    "runtime.api.cli.yoke_flag_adapters_github_actions_wait": "yoke_cli.commands.adapters.github_actions_wait",
    "runtime.api.cli.yoke_flag_adapters_helpers": "yoke_cli.commands._helpers",
    "runtime.api.cli.yoke_flag_adapters_hooks": "yoke_cli.commands.adapters.hooks",
    "runtime.api.cli.yoke_flag_adapters_install": "yoke_cli.commands.adapters.install",
    "runtime.api.cli.yoke_flag_adapters_items": "yoke_cli.commands.adapters.items",
    "runtime.api.cli.yoke_flag_adapters_items_scalar": "yoke_cli.commands.adapters.items_scalar",
    "runtime.api.cli.yoke_flag_adapters_items_section": "yoke_cli.commands.adapters.items_section",
    "runtime.api.cli.yoke_flag_adapters_listing": "yoke_cli.commands.adapters.listing",
    "runtime.api.cli.yoke_flag_adapters_misc": "yoke_cli.commands.adapters.misc",
    "runtime.api.cli.yoke_flag_adapters_projects": "yoke_cli.commands.adapters.projects",
    "runtime.api.cli.yoke_flag_adapters_qa": "yoke_cli.commands.adapters.qa",
    "runtime.api.cli.yoke_flag_adapters_qa_browser": "yoke_cli.commands.adapters.qa_browser",
    "runtime.api.cli.yoke_flag_adapters_qa_crud": "yoke_cli.commands.adapters.qa_crud",
    "runtime.api.cli.yoke_flag_adapters_qa_read": "yoke_cli.commands.adapters.qa_read",
    "runtime.api.cli.yoke_flag_adapters_render": "yoke_cli.commands.adapters.render",
    "runtime.api.cli.yoke_flag_adapters_strategy": "yoke_cli.commands.adapters.strategy",
    "runtime.api.cli.yoke_flag_adapters_strategy_create": "yoke_cli.commands.adapters.strategy_create",
    "runtime.api.cli.yoke_flag_adapters_strategy_render": "yoke_cli.commands.adapters.strategy_render",
    "runtime.api.cli.yoke_flag_adapters_templates": "yoke_cli.commands.adapters.templates",
    "runtime.api.cli.yoke_flag_adapters_usage": "yoke_cli.commands.adapters.usage",
    "runtime.api.cli.yoke_git_hook_commands": "yoke_cli.commands.git_hook",
    "runtime.api.cli.yoke_hooks_relay": "yoke_harness.hooks.relay",
    "runtime.api.cli.yoke_hooks_relay_identity": "yoke_harness.hooks.identity",
    "runtime.api.cli.yoke_operation_inventory": "yoke_cli.operation_inventory",
    "runtime.api.cli.yoke_operation_inventory_data": "yoke_cli.operation_inventory_data",
    "runtime.api.cli.yoke_operations_cli": "yoke_cli.main",
    "runtime.api.cli.yoke_qa_browser_command": "yoke_cli.commands.qa_browser",
    "runtime.api.cli.yoke_subcommand_registry": "yoke_cli.commands.registry",
    "runtime.api.cli.yoke_tool_shaped": "yoke_cli.commands.tool_shaped",
    "runtime.api.cli.terminal_pager": "yoke_cli.terminal_pager",
}

# --- harness carve-out — populate from carve-out-harness.md when running the
# harness carve-out. The 11 SPLIT files are hand-split (function-level), not 1:1 renames.
EXACT_HARNESS: Dict[str, str] = {}

# --- dev-fenced cli modules that STAY core -------------------------------
EXACT_CORE_FENCES: Dict[str, str] = {
    "runtime.api.cli.db_router": "yoke_core.cli.db_router",
    "runtime.api.cli.db_router_dispatch": "yoke_core.cli.db_router_dispatch",
    "runtime.api.cli.db_router_init": "yoke_core.cli.db_router_init",
    "runtime.api.cli.db_router_help": "yoke_core.cli.db_router_help",
    "runtime.api.cli.db_router_suggestions": "yoke_core.cli.db_router_suggestions",
    "runtime.api.cli.raw_query": "yoke_core.cli.raw_query",
    "runtime.api.cli.raw_query_catalog": "yoke_core.cli.raw_query_catalog",
    "runtime.api.cli.board_rebuild_timing_events": "yoke_core.cli.board_rebuild_timing_events",
}

# --- core default prefix rules — most-specific first --------------------
PREFIX_RULES_CORE: List[Tuple[str, str]] = [
    ("runtime.api.domain.handlers.", "yoke_core.domain.handlers."),
    ("runtime.api.domain.migrations.", "yoke_core.db.migrations."),
    ("runtime.api.domain.", "yoke_core.domain."),            # catch-all (LAST domain)
    ("runtime.api.routes.", "yoke_core.api.routes."),
    ("runtime.api.engines.", "yoke_core.engines."),
    ("runtime.api.tools.", "yoke_core.tools."),
    ("runtime.api.board.", "yoke_core.board."),
    ("runtime.api.service_client", "yoke_core.api.service_client"),  # family prefix
    ("runtime.api.app_factory", "yoke_core.api.app_factory"),
    ("runtime.api.server_entrypoint", "yoke_core.api.server_entrypoint"),
    ("runtime.api.http_auth", "yoke_core.api.http_auth"),
    ("runtime.api.observability", "yoke_core.api.observability"),
    ("runtime.api.main", "yoke_core.api.main"),
    ("runtime.api.routing_config", "yoke_core.api.routing_config"),
    ("runtime.api.container_healthcheck", "yoke_core.api.container_healthcheck"),
    ("runtime.api.repo_root", "yoke_core.api.repo_root"),
]

# Per-slice rename selection. core uses prefix rules + fences applied at run time.
SLICES: Dict[str, str] = {
    "contracts": "EXACT_CONTRACTS",
    "cli": "EXACT_CLI",
    "harness": "EXACT_HARNESS",
    "core-fences": "EXACT_CORE_FENCES",
}

_ALL_EXACT: Dict[str, str] = {
    **EXACT_CONTRACTS,
    **EXACT_CLI,
    **EXACT_HARNESS,
    **EXACT_CORE_FENCES,
}


def resolve(old_dotted: str) -> Optional[str]:
    """Resolve one old dotted module to its new dotted module, or None if no rule.

    Exact carve-out/fence rules win over the core prefix defaults. Among prefix
    rules the list order (most-specific-first) decides, so handlers/migrations beat
    the domain catch-all.
    """
    if old_dotted in _ALL_EXACT:
        return _ALL_EXACT[old_dotted]
    for old_pre, new_pre in PREFIX_RULES_CORE:
        if old_dotted == old_pre.rstrip(".") or old_dotted.startswith(old_pre):
            return new_pre + old_dotted[len(old_pre):] if old_dotted.startswith(old_pre) \
                else new_pre.rstrip(".")
    return None


def slice_renames(name: str) -> Dict[str, str]:
    """Rename map for a named slice. 'core' = prefix rules are resolved lazily by the
    engine over the residual tree, so it is not an exact map; the four exact-map
    slices return their dict directly."""
    if name not in SLICES:
        raise SystemExit(f"unknown slice {name!r}; known: {sorted(SLICES)}")
    return dict(globals()[SLICES[name]])
