# /yoke idea — invocation notes and standing cautions


- **`/yoke idea` is a harness skill entrypoint, not a `yoke` CLI subcommand.** Invoke it as the `/yoke idea` slash command — there is no `yoke idea` CLI adapter, so `yoke idea --help` returns `unknown subcommand`. The `yoke <subcommand>` CLI wraps item/claim/lifecycle operations; work item *intake* is a skill flow, not a CLI verb.
- An explicit `/yoke idea --workflow blitz "{title}"` selection is passed to
  the registered `items.create` function as `workflow: "blitz"` with
  `entry_surface: "harness_skill"`. The new item still starts at `idea`;
  refinement must link exactly one execution strategy document before
  `/yoke blitz` begins at `refined-idea`.
- Status is always `idea` for new items. Follow the workflow-specific
  handoff in `infer-and-create.md`: Issue and Epic use `/yoke shepherd`;
  Blitz uses `/yoke refine` and then `/yoke blitz`. Task uses `/yoke do`
  or `/yoke advance` into implementing, then Dash close-out to done.
- The PREFIX-N ID is permanent — it never changes even after GitHub sync.
- Items are auto-synced to GitHub on creation. If GitHub sync is unavailable, the item is created locally and can be synced later through the internal item sync repair path; do not teach that repair path as normal product flow.
- This is a write command — it creates a file and inserts a DB row.
- **Maximum questions rule:** This flow asks at most 3 binary questions total per invocation. Most items should require zero questions (all fields inferred from context). Count your questions — if you have already asked 3, stop asking and use best-guess defaults for remaining ambiguities.
- **Done-means must be guard-permitted.** Verification commands written into the spec (definition of done, AC verify steps, "run this to prove it") must be a shape PreToolUse allows: `yoke <subcommand>`, `yoke watch pytest -- ...`, or `yoke dev run -- python3 -m ...`. Never prescribe `python3 -c` importing `yoke_core` / `yoke_cli` / `yoke_harness`. Readiness `BLOCKED_AGENT_COMMAND_SHAPE` blocks fenced or backticked prescriptions of that shape.
