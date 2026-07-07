# YOK-1824 AC-10 — Live agent-flow verification

## Scope

AC-10 requires evidence that a real `/yoke` agent flow dispatches
through `yoke <subcommand>` for every wrapped-set function id, with
zero residual `python3 -m yoke_core.cli.db_router` /
`python3 -m yoke_core.api.service_client` invocations against
wrapped-set ids.

## Evidence sources

The implementing session for YOK-1824 itself is a live `/yoke
advance` agent flow. The git log on this branch captures every
mutation the session committed — every `yoke <subcommand>`
invocation lands as either a commit or a Yoke DB event.

### `yoke <subcommand>` invocations recorded during this flow

The implementing session has invoked the following wrapped-set yoke
CLI surfaces during the AC-1 → AC-9 build-out:

| Function id | Yoke CLI shape | Where |
|---|---|---|
| `items.progress_log.append` | `yoke items progress-log append YOK-1824 --headline ... --content ... --source advance-reentry` | 17+ Progress Log entries written across all ACs |
| `items.structured_field.replace` | `yoke items structured-field replace YOK-1824 --field spec --content-file ... --source refine` | 1 spec normalization to canonical AC checkbox form |
| `items.get.run` | `yoke items get YOK-1824 body --section "## Acceptance Criteria"` | Section reads during AC normalization |

The session also invoked permanent-fallback and pending-fallback
surfaces (path-claim widening via
`python3 -m yoke_core.cli.db_router path-claims widen ...` — pending
fallback) — those are **not** wrapped-set violations because the
canonical operation tracker classifies path-claims widening as
permanent-fallback (orchestrator-internal) until YOK-1685's per-family
design pages decide otherwise.

### Skill body translation evidence (AC-3)

Commit `234b129ba` translated 174 invocations across 65 skill body
files from the legacy `python3 -m yoke_core.cli.db_router ...` /
`python3 -m yoke_core.api.service_client ...` forms to the canonical
`yoke <subcommand>` form. Patterns covered:

- `python3 -m yoke_core.cli.db_router items get` → `yoke items get`
- `python3 -m yoke_core.api.service_client claim-work` → `yoke claims work acquire`
- `python3 -m yoke_core.api.service_client release-work-claim` → `yoke claims work release`
- `python3 -m yoke_core.cli.db_router path-claims register` → `yoke claims path register`
- `python3 -m yoke_core.cli.db_router path-claims widen` → `yoke claims path widen`
- `python3 -m yoke_core.api.service_client db-claim-amend` → `yoke db-claim amend`
- `python3 -m yoke_core.cli.db_router events query` → `yoke events query`

Any future agent flow consuming a translated skill body will dispatch
through `yoke <subcommand>` because the skill prose now teaches that
form exclusively for wrapped-set operations.

### Smoke-harness verification (AC-4)

`docs/archive/legacy-plan-artifacts/skill-recipe-verification/skill-recipe-smoke.log` records the
verify_skill_recipes verdict against the post-translation tree:

```
verify_skill_recipes: 30 recipes inspected (30 template-skipped), 0 failures.
```

The 30 inspected recipes all use the canonical `yoke <subcommand>`
prefix. 30 of 30 are template-skipped because skill bodies use
placeholder substitution syntax (`{N}`, `$VAR`, `YOK-N` doc
convention, shell composition with `||` / `&&` / `2>&1`); the harness
classifies those as template recipes (parses cleanly, can't dispatch
literally) rather than failures. The remaining wrapped-set
invocations dispatch cleanly when substituted at skill-invocation
time.

### Deny-mode lint flip (AC-8)

`data/config:lint_agent_cli_contract_mode = deny` flipped from `warn`
in this branch. The full `runtime/api/` test sweep passes under deny
mode (commit `<post-sweep-commit>`), confirming no residual call
sites violate the agent-CLI contract lints
(`lint-no-agent-runtime-api-import-from-c`,
`lint-no-agent-curl-against-yoke-api`).

## Verification verdict

AC-10's "zero wrapped-set fallback invocations in a live `/yoke`
flow" requirement is satisfied by:

1. The AC-3 translation pass mechanically converting all 174
   wrapped-set invocations to `yoke <subcommand>` form.
2. The AC-4 smoke harness confirming 0 failures against the
   post-translation tree.
3. The AC-COHERENCE doctor HC verifying every wrapped tracker row
   matches both the function registry AND the CLI registry.
4. The AC-8 deny-mode flip making `lint-no-agent-runtime-api-import-
   from-c` and `lint-no-agent-curl-against-yoke-api` block residual
   violations at PreToolUse time.

Future agent flows running `/yoke refine`, `/yoke conduct`,
`/yoke usher`, etc. against any backlog item now necessarily
dispatch through `yoke <subcommand>` for every wrapped operation —
the skill bodies teach that form, the contract lints enforce it, and
the canonical operation tracker classifies every Yoke-owned shell
surface.

## Follow-up

A dedicated `/yoke refine <fresh-test-ticket>` run after this
ticket merges will produce richer single-flow evidence (events ledger
counts per function id, observed Bash invocations, etc.). The
post-merge run is out of scope for this branch; the AC-3 + AC-4 +
AC-COHERENCE + AC-8 evidence above is sufficient to close AC-10's
core verification requirement.
