"""yoke_core — the server runtime and single source of control-plane authority.

Owns the FastAPI app/routes, function handlers, DB/domain invariants, lifecycle,
backlog, claims, sessions, QA, projects, deployment, migrations, Doctor/merge
engines, core tooling, install-bundle + agent-packet rendering, and the
authority-bearing session/claim/event/worktree logic relocated from the harness.

All shared state is mutated here, server-side; clients reach it over the function-
call API. May depend on `yoke_contracts`, the `yoke_cli` client substrate, and
`yoke_harness` (client-neutral harness-identity helpers). Clients (`yoke_cli`,
`yoke_harness`, `yoke_contracts`) MUST NOT import this package — enforced by
import-graph tests.
"""
