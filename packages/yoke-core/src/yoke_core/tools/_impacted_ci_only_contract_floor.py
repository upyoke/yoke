"""Always-run floor: CI repo-contract failure classes import reachability misses.

WHY: Operation inventory exactness, Atlas integrity / docs/atlas.md pairing,
and schema packet line budgets mirror ``ci_repo_contracts`` concerns that
have no import edge from everyday lane edits. Packet budgets are the
sharpest case: a packet is rendered from live ``--help`` probes and live
schema, so editing one command's usage string can push a role over its
line budget from a module the budget test never imports. Lanes run
impacted selection, so this family must execute on every local impacted
run. Keep the set fast (roughly 30 seconds) — the budget member is the
focused packet-budget file, not the broad schema-context suite that also
renders every packet.
"""

CI_ONLY_CONTRACT_FLOOR_TESTS = (
    "runtime/api/cli/test_yoke_operation_inventory.py",
    "runtime/api/tools/test_atlas_integrity_contract.py",
    "runtime/api/domain/test_schema_api_context_packet_budget.py",
)

__all__ = ["CI_ONLY_CONTRACT_FLOOR_TESTS"]
