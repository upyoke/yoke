"""Always-run floor: CI repo-contract failure classes import reachability misses.

WHY: Operation inventory exactness, Atlas integrity / docs/atlas.md pairing,
item-reference construction policy, GitHub token-scope declarations, and
schema packet line budgets mirror ``ci_repo_contracts`` concerns that have no
import edge from everyday lane edits. Packet budgets are the sharpest case: a
packet is rendered from live ``--help`` probes and live schema, so editing one
command's usage string can push a role over its line budget from a module the
budget test never imports.
The token-scope member is the same shape read from the other end: it walks
every source module looking for a call that resolves an installation token
without declaring the permissions it needs, so the file that breaks it is
always a file the contract does not import — the one that just grew the call.

Lanes run impacted selection, so this family must execute on every local
impacted run. Keep the set fast (roughly 30 seconds) — the budget member is
the focused packet-budget file, not the broad schema-context suite that also
renders every packet, and the token-scope member is an AST walk rather than a
suite that builds anything.
"""

CI_ONLY_CONTRACT_FLOOR_TESTS = (
    "runtime/api/cli/test_yoke_operation_inventory.py",
    "runtime/api/domain/test_github_operation_permission_scopes.py",
    "runtime/api/domain/test_lint_item_ref_construction.py",
    "runtime/api/domain/test_schema_api_context_packet_budget.py",
    "runtime/api/tools/test_atlas_integrity_contract.py",
)

__all__ = ["CI_ONLY_CONTRACT_FLOOR_TESTS"]
