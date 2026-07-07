# Harness Substrate

Yoke runs on multiple harnesses (Claude Code, Codex, future runtimes) without forking the per-agent prompt body, the per-skill phase prose, or the dispatch contract. This document describes the universal-source + per-harness-renderer model that makes that possible.

## One canonical body, two rendered adapters

Every Yoke agent has exactly one source-of-truth body file under `runtime/agents/{agent}.md`. The substrate renderer fans that body into harness-native adapter files:

- **Claude:** `runtime/harness/claude/agents/yoke-{agent}.md` — Markdown with YAML frontmatter (name, description, tools, model, hooks). The runtime `.claude/agents/` path is a symlink into this directory, so Claude Code reads the rendered file directly.
- **Codex:** `runtime/harness/codex/agents/yoke-{agent}.toml` — TOML custom-agent definition in the current Codex subagent schema: required `name` / `description` / `developer_instructions` (the canonical body inlined) plus the optional fields Codex inherits from the parent session when omitted. `model` is omitted by default so each subagent follows the parent session/default model, and is pinned only when the sidecar opts in via `model_policy="pinned"`; role posture is expressed with `sandbox_mode` (`read-only` for the read-only roles, `workspace-write` for the engineer). The Claude-style string tool allowlist and turn-budget field are not Codex subagent fields and are never emitted. The runtime `.codex/agents/` path is a symlink into this directory, so Codex Desktop reads the rendered TOML files as registered custom agents.

The renderer is owned by the `agents.render.run` function family and exposed to operators as `yoke agents render`. Both adapter directories regenerate from the same canonical body in a single pass; drift is caught by `HC-agent-canonical-drift` in doctor.

The shared manifest schema for agent registration lives at `runtime/harness/bootstrap-spec.json#canonical_agents` and `runtime/harness/codex/manifest.json`. These entries point at the canonical body path; they never inline the body. New harnesses describe their adapter shape in their manifest and add a renderer pass — they never duplicate the prompt text.

## Shared dispatch descriptors

Skill phase files (under `.agents/skills/yoke/{command}/`) name agents through dispatch descriptors rather than harness-specific tool calls. A descriptor is a small structured object that names the agent (`yoke-engineer`, `yoke-tester`, `yoke-architect`, `yoke-simulator`, etc.), supplies the task envelope (prompt body, file routing context, claim metadata), and declares result-ingestion expectations.

Both harnesses consume the same descriptor:

- **Claude** translates the descriptor into an `Agent(subagent_type=...)` tool call.
- **Codex** translates the same descriptor into a Codex custom-agent dispatch.

Result ingestion is parseable on both sides — verdicts, reflections, progress notes, and structured outputs land in the same Yoke-core DB tables (`shepherd_verdicts`, `epic_progress_notes`, `qa_runs`, `events`) regardless of which harness ran the agent. Phase files write the descriptor once; the harness adapter handles the call.

The capability registry exports `HARNESS_UNIVERSE` (the set of supported harnesses with their adapter shapes), so phase files and skills can branch on substrate-level capability without reading harness-specific manifests inline.

## Session cwd binding

Sessions running in `advance` / `conduct` / `polish` mode bind the harness cwd to the item's worktree at session start. The binding is structural: the harness session-start hook reads the active item from the session row (cross-reference: see your `harness_sessions` packet stanza for active-item attribution columns), resolves the absolute worktree path via `_resolve_item_worktree` (composed from the item's worktree branch slug under this machine's registered checkout for the numeric project id; cross-reference: see your `items` and `projects` packet stanzas), and chdir's the harness shell into that directory before any tool call fires.

This is the **first line of defense** against silent wrong-tree reads. With cwd structurally pinned, relative-path Bash reads resolve inside the worktree by default; the agent doesn't need to remember the worktree path to stay safe.

The Bash absolute-path rule (in `AGENTS.md`'s `## Code Conventions` section) is the **second line of defense**. Even with cwd bound, agents author absolute paths in Bash commands as defense-in-depth: parallel-batched Bash calls have shown shell cwd drift in practice, and the absolute-path rule survives that drift. Python import-root anchoring (PYTHONPATH set to the worktree root by the harness adapter) is a third defense-in-depth layer for Python module commands that resolve sibling imports from cwd.

#### Writer authority — `workspace_authority` (work-claim) plus `YOKE_BOUND_WORKSPACE` (legacy reader/lint anchor)

The **primary writer guard** is `yoke_core.domain.workspace_authority.assert_target_under_session_work_authority(target)`, which reads the calling session's live `work_claims` rows and refuses targets outside the claimed worktree (or the free-path allowlist `/tmp`, `/var/folders/...`). Sessions with no worktree claim (orchestrator / maintenance posture) fall through to no-op, matching the per-tool-call `lint_session_cwd` policy. The work-claim row IS the live authority — replacing the prior `$YOKE_BOUND_WORKSPACE` env-var snapshot, which went stale the moment a session rotated claims.

Tracked-source writers call the helper before their hot-path `.write_text` / `.write_bytes` / `os.replace`:

- `yoke_core.domain.agents_render._atomic_write` (substrate renderer)
- `yoke_core.tools.atlas_integrity_audit.write_report`
- `yoke_core.tools.atlas_render_docs.write`
- `yoke_core.domain.populate_registry_render._render_catalog`

`HC-workspace-anchored-writer-authority` enforces this against the canonical list at `runtime/api/engines/doctor_hc_workspace_anchored_writer_authority.py:IN_SCOPE_WRITERS`; add new tracked-source writers there to bring them under the guard.

`yoke_core.domain.rebuild_board.rebuild_one` is intentionally **out of scope** for the work-claim authority helper. Its only write targets are project-local `.yoke/BOARD.md` plus the sibling timestamp file, both untracked generated views regenerated from DB state on every status change. The board rebuild fires as a routine side effect of every `/yoke polish` and `/yoke usher` status transition while the session still holds the item's worktree work-claim; refusing those writes would break the polish/usher flow without addressing the incident shape: worktree-claim-bound writes of TRACKED rendered source files into main. `rebuild_board` still calls `assert_seed_source_under_target_root(schema.__file__, repo_root, ...)` to catch Coupling B (the schema module loaded from a different checkout than the resolved `repo_root`), as does `agents_render` for its imported seed module.

`YOKE_BOUND_WORKSPACE` survives as a legacy anchor with two narrow consumers:

- **Reader-root fallback.** `yoke_core.domain.agents_render_workspace.require_reader_root` consults the env var when no explicit `target_root` is supplied, before raising. SessionStart exports the value via `runtime/harness/hook_runner/session_dispatch.py` (helper module: `runtime/harness/hook_runner/session_workspace.py`). For Claude Code the value is appended to `$CLAUDE_ENV_FILE` so subsequent Bash invocations inherit it; for Codex the in-process `os.environ` set is sufficient because the runner subprocess tree spawned during the session inherits env from the same interpreter.
- **Cross-checkout PreToolUse lint.** `runtime/api/domain/lint_workspace_cwd_match.py` denies writer-class Bash commands (`pytest`, `python3 -m pytest`, `yoke agents render`, and the `yoke_core.tools.run_tests` helper) when the env var is set and the command's cwd is outside the workspace. Mode is pinned by machine config key `lint_workspace_cwd_match_mode` (Yoke dogfood: `deny`). The suppression token `# lint:no-workspace-cwd-check` is recorded as `outcome=suppression_attempted` audit evidence and does NOT unblock — symmetric with the path-claim guard's audit-only token shape.

When `YOKE_BOUND_WORKSPACE` is unset (operator/maintenance mode, sessions outside Yoke recognition), the reader fallback and the lint both no-op; the writer-authority helper continues to enforce against live work-claims and the writer-API contract (`target_root` required keyword on `write_all` / `write_all_claude`) remains the unconditional API-shape defense.

Worktree creation is a pure filesystem + DB operation, not a session boundary. The harness session that runs `/yoke advance ... implementation` (or the conduct task-lane equivalent) records the worktree branch slug on the item (cross-reference: see your `items` packet stanza), activates path claims, and continues into worktree-bound implementation/review work in the same session — no claim release, no `HarnessSessionEnded`, no relaunch block. (See `docs/event-catalog.md` for the registry's retired-event rows that document the prior session-end and session-envelope behaviors.)

### Session cwd binding: per-call claim-based authority

The session's authority to write under any given path is its **active work-claims** (cross-reference: see your `work_claims` packet stanza). `runtime/api/domain/lint_session_cwd.py` validates this per tool call: for each target path extracted from the call's payload (file_path for Edit/Read/Write; -C / --rootdir / leading absolute path args for Bash), the target must land under (a) a worktree the session holds a claim on, (b) the main control plane checkout excluding `.worktrees/`, or (c) the free-path allowlist (`/tmp`, `/var/folders/...`). The validator resolves the claimed worktree's branch slug (for item or epic-task targets; cross-reference: see your `items` and `epic_tasks` packet stanzas) and composes the absolute path via `_compose_worktree_path` under this machine's registered checkout for the numeric project id, all through `yoke_core.domain.session_claimed_worktrees.claimed_worktrees`. Sessions with no claims AND no resolvable parent (orchestrator one-offs, operator REPL sessions) pass unconditionally — the unconstrained control-plane shape needs no enforcement.

Parallel fan-out works without a race: each subagent dispatch acquires its own `work_claim` covering the lane it operates in, and the lint authorizes each subagent's writes against its own claim. The orchestrator's control-plane reads (`epic_progress_notes`, `db_router events list`, board rebuilds, GitHub mutations) always pass because they target control plane, which is always allowed.

Codex subagent dispatch runs in-process inside the parent harness session — same `session_id`, same hook chain, same `cwd`. Yoke's claim-aware lookups (`work_claims`, `path_claims`, `claimed_worktrees`, `_default_actor_id_resolver`, dispatcher claim verification) therefore land on the parent's row directly without any per-subagent identity propagation. Claude's `Agent`-tool subagents reuse the orchestrator's `session_id` for the same reason; in both harnesses the parent's claims are the subagent's claims by virtue of session-identity sharing.

The Claude Code / Claude Desktop main session keeps a sticky cwd between Bash tool calls (cross-reference: AGENTS.md `## Code Conventions` Bash bullet), so a `cd <worktree>` to an in-scope path persists across subsequent calls; subagent dispatch contexts behave differently, with each tool call reverting to the parent checkout. Yoke treats either shape as a supported substrate, not a failure: `runtime/api/domain/lint_session_cwd.py` validates each call's target paths against the session's active `work_claims` (not against cwd), so claim-based authority is the per-call authority signal regardless of which harness tier issued the call.

Inspect what the current session is authorized to write via the work-claim holder read:

```bash
yoke claims work holder-get YOK-N
```

Anything whose extracted target lands outside (a) / (b) / (c) above is denied by `lint_session_cwd`. The deny narrative names the offending target plus the session's active claims so the operator can fix the call by acquiring a claim on the intended worktree, correcting the target path, or routing through control plane.

For recursive discovery — the shape that broad relative `grep -r` /
`rg <pattern>` would normally fit — use the worktree-aware
`yoke_core.tools.search_code` helper instead of authoring `grep -r
./` against the worktree. Its default scope searches the claimed
worktree(s); callers must explicitly request main-checkout search when
that is the intended root.

The helper resolves absolute roots through the canonical Yoke resolvers
(`yoke_core.domain.worktree_item_resolve`), applies safe default excludes
(`.git`, `.worktrees`, `__pycache__`, cache dirs, `.venv` / `venv`,
`node_modules`, `dist`, `build`), prefers `rg` when present and uses a
tested Python fallback otherwise. The output mirrors `rg --line-number
--no-heading` (`<path>:<line>:<match>`); multi-worktree epic items prefix each
match with the worktree root so callers can disambiguate. The helper is
read-only — it does not touch claim, lifecycle, or session state.

The target extractor lives in `yoke_core.domain.lint_session_cwd_target_extract`; the validator lives in `yoke_core.domain.lint_session_cwd_validate`; the policy glue + deny envelope rendering live in `yoke_core.domain.lint_session_cwd`. Destructive shell shapes (`xargs rm`, `git reset --hard`, `git clean -f`) are still blocked by the separate `yoke_core.domain.lint_destructive_git` guard.

## SessionEnd defense: claim- and chain-aware refusal

Claude Desktop fires `SessionEnd` on transient signals (laptop sleep, app reload,
brief disconnect, idle timeout) — not only on permanent termination. The hook
runner no longer asserts the agent is gone on its own. The destructive path now
runs through the shared guard at
`yoke_core.domain.sessions_lifecycle_destructive_guard.evaluate_destructive_end`:

- `end_session` reads active work claims first; an active claim is the
  authoritative signal that the session's work is in flight and the
  `release_claims=True` branch evaluates the destructive guard only when
  claims are held.
- When a persisted chain checkpoint is chainable with remaining budget,
  the guard returns `defer=True` with reason `chain_pending`. The
  destructive `release_claims=True` branch in
  `sessions_render_end.end_session` emits `HarnessSessionEndDeferred`
  and returns early — claims stay active, no terminal
  `HarnessSessionEnded` is written.
- When no chain is pending, the guard returns `defer=False` and the
  destructive path runs as today. `HarnessSessionEnded` carries
  `chain_end_rationale="claude_session_end_hook_fired"` plus a structured
  `agent_presence_evidence` payload (`chain_budget_remaining`,
  `chain_override_authorized`).

`last_heartbeat` is no longer consulted by the destructive guard. After
the keepalive daemon was eliminated it became a tool-activity recency
signal rather than a liveness signal, conflating idle-but-alive sessions
with permanent ends. `last_heartbeat` survives only for the 30-minute
stale-session reclaim sweep in `yoke_core.domain.sessions_cleanup`.

The Stop-hook path (`session-end-if-empty`) and the SessionEnd-hook path
(`session-end --force --release-claims`) share the same claim+chain
decision through the guard module. `Stop` already preserved claims; the
SessionEnd path now matches that posture for transient signals.

## Reactivation: conditional auto-reacquire + slim resume block

`register_session` reactivation now runs conditional auto-reacquire alongside
the existing advisory. When the prior `release_reason='session_ended'` is
inside `session_reactivation_reacquire_window_s` (default 300s, configured
in machine config) AND no other session currently holds an active claim on the
same target, a new active `work_claims` row is inserted in the same
transaction. `SessionReactivationReacquiredClaims` records the receipt with
per-target reacquired / conflict outcomes.

The hook runner renders a slim resume block on the next `UserPromptSubmit`
(Claude) or `SessionStart` (Codex) for the reactivating session. The block
names the prior released targets, the auto-reacquire outcome, and the
explicit operator commands. `HarnessSessionResumeBlockShown` marks the
once-per-cycle render; a subsequent reactivation re-arms the block.

## Path-claim enforcement boundary

Every Yoke item's worktree carries a path-claim — the explicit set of directories and files that worktree may modify. The path-claim is enforced at three structural layers:

1. **Edit / Write tool guards (Claude):** `PreToolUse(Edit)` and `PreToolUse(Write)` hooks deny tool calls whose target file path is outside the active item's path-claim coverage. Same hook covers Codex's `PreToolUse(apply_patch)` matcher — `apply_patch` is Codex's structural equivalent to Claude's Write/Edit tools.
2. **Bash mutation guard (both harnesses):** `PreToolUse(Bash)` denies mutating shell commands (`>`, `>>`, `tee`, `mv`, `cp`, `rm`, `git checkout --`, `sed -i`, etc.) whose effective target path is outside path-claim coverage. Read-only inspection commands (`cat`, `grep PATTERN FILE`, `sed -n ... FILE`, `ls`, `head`, `tail`, `rg`, `diff`, `git show`, `git diff --name-only`, `python3 -m ... --help`, file-existence probes) are allowed without claim widening or suppression tokens. The parser treats the grep pattern operand as a pattern, not as a path-claim target. If a read command also performs a write, such as `grep needle file > out.txt`, the write target is still guarded through the redirect mutation.

   When an out-of-claim failure target lives **inside the active claim's bound worktree**, the deny narrative pivots away from the generic widen headline and toward the worktree preflight re-entry path owned by `yoke_core.domain.worktree_preflight`. The `yoke claims path widen --claim-id <claim-id> --add-paths <path> --reason R --item YOK-N` template stays as a secondary option for paths the claim does not cover by design. The narrative builders live in `yoke_core.domain.path_claim_bash_guard_narrative` (`format_narrative`, `target_under_active_worktree`, `worktree_preflight_template`, `ambiguous_narrative`); the guard module owns the verdict factory.
3. **Pre-commit path-claim coverage check:** A pre-commit hook refuses commits whose staged file list contains paths outside the path-claim. This catches the residual class where a tool-level guard missed a path (for example, a multi-file `apply_patch` whose subset edits crossed the claim boundary). Suppression token `[no-path-claim-check]` in the commit message is honored as audit evidence only — the rule still denies; the token does not unblock. The audit event records the suppression attempt for reviewer grep.

The companion suppression token at the tool level is `# lint:no-worktree-path-check` on the Bash command body (also audit-evidence only). Both tokens are documented here so any agent troubleshooting a guardrail denial can find them in one place.

## Renderer outputs and regeneration

The substrate renderer produces:

| Output | Purpose | Regeneration command |
|---|---|---|
| `runtime/harness/claude/agents/yoke-*.md` | Claude Code adapter files | `yoke agents render` |
| `runtime/harness/codex/agents/yoke-*.toml` (surfaced as `.codex/agents/yoke-*.toml`) | Codex custom-agent files | Same |
| `runtime/harness/bootstrap-spec.json#canonical_agents` | Shared canonical-body discovery | Manual (operator-authored manifest) |
| `runtime/harness/codex/manifest.json` | Codex affordances and limitations | Manual (operator-authored manifest) |

Regeneration is idempotent. Doctor's `HC-agent-canonical-drift` health check fails when any rendered adapter body diverges from its canonical source.

## Adding a new harness

To add a third harness adapter:

1. Author `runtime/harness/{harness_id}/manifest.json` (identity, affordances, substrate limitations).
2. Add a renderer pass for the harness's adapter shape (Markdown, TOML, YAML, etc.) in `yoke_core.domain.agents_render`.
3. Implement the dispatch-descriptor consumer for the harness's native subagent / custom-agent / tool-call primitive.
4. Add the harness to `HARNESS_UNIVERSE` in the capability registry.
5. Author a smoke-test runbook (mirror `runtime/harness/codex/SMOKE-TEST.md`).
6. Run `/yoke doctor` and confirm the harness-specific health checks pass.

The canonical bodies under `runtime/agents/` never change. The skill phase files never change. Only the adapter directory, the renderer pass, the manifest, and the smoke-test runbook are new.

## Related docs

- [Harness Bootstrap Contract](harness-bootstrap.md) — neutral startup expectations
- [Harness Adapter Template](harness-adapter-template.md) — five-part adapter template
- [Hook Parity Map](hook-parity-map.md) — three-tier hook classification across harnesses
- [Subagent Reference](agents.md) — agent-by-agent behavior
- [Harness README](../runtime/harness/README.md) — adapter directory convention
