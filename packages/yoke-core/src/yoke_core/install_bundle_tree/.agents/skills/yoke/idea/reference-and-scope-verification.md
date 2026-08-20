# Idea Intake Reference And Scope Verification

When `/yoke idea` proposes concrete file paths, package roots, or owner-symbol
names that will land in the spec body, verify every reference against the live
tree before writing it. Naming intuition drifts as the codebase evolves, and a
wrong reference makes refinement and execution chase ghosts.

Apply these checks during inference, body drafting, and any later edit that
introduces an implementation surface.

## Verify Concrete Paths

Run an explicit verification verb before writing a proposed implementation
path:

- For a directory or package root, run `test -d <path>` from the repo root.
- For a specific file or pattern, use the Glob tool and require a match.

If the path does not resolve, re-derive it from the live tree. Prefer the
project's verified migration root, the live `.agents/skills/yoke/` structure
for skill prose, or a recently completed item in the same family. If it still
cannot be verified, record a clarification question instead of guessing.

## Verify Owner Symbols

Before naming a lifecycle gate, status-write gate, QA gate, or error-code
owner, run this template against the project's verified source and test roots:

```bash
rg -n 'def _run_.*_gate|def check_.*_gate|GATE_[A-Z_]+' <source-roots>
```

Use the owner from the output, not a vocabulary-only filename. Item stage and
gate placement belong to immutable workflow definitions interpreted by
`workflow_runtime.py`; independent epic-task vocabulary belongs to
`task_lifecycle.py`.

For any other concrete `module.function_name` the spec proposes to change,
run:

```bash
rg -n '^def <funcname>' <source-roots> <docs-and-agent-instruction-roots>
```

Cite the verified definition. A zero-match result becomes a clarification
question. Scope searches to roots discovered from the project rules or
tracked top-level paths; never assume another project's layout. Item bodies
are virtual DB projections and are read with `yoke items get PREFIX-N body`,
not filesystem search. Use single-quoted `rg` patterns so zsh cannot interpret
backticks as command substitutions.

The idea-exit and refine-entry readiness checks repeat this verification
through `yoke readiness check`.

## Preserve Scope Across Path-Claim Conflicts

Claimed paths never narrow work-item scope. Keep every required file in the
execution artifact and in every enabled File Budget or path-claim surface.
Treat overlap as coordination or dependency evidence, not permission to omit
the file.

Accepted remediations are:

- classify independent edits with a `coordination_only` edge;
- record order-dependent work with an activation-gated dependency and rationale;
- leave the candidate claim blocked while waiting for the holder;
- coordinate with the holder or ask them to narrow or cancel their claim;
- use operator `path-claim-override` only as a last resort.

See `AGENTS.md` `## Path Claims — Hard Rule` for the complete contract.
