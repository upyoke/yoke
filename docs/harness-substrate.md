# Harness Substrate

Yoke shares canonical role bodies, situational skills and dispatch contracts
across Claude, Codex and Cursor. Harness-specific renderers/manifests define
native syntax and supported primitives; this optional contributor reference
explains their boundaries. Read the installed release manifest before asserting
live capability. [Bootstrap](harness-bootstrap.md) and
[native discovery](public/reference/harness-discovery.md) own loading.

## Canonical bodies and adapters

Each agent body lives once at `runtime/agents/{agent}.md`, with phase support in
its role directory. `agents.render.run` (`yoke agents render`) expands supported
conditional blocks and dispatch metadata into native adapters:

| Harness | Output and native discovery |
|---|---|
| Claude | Markdown/YAML `runtime/harness/claude/agents/yoke-{agent}.md`, reached by `.claude/agents`. |
| Codex | TOML `runtime/harness/codex/agents/yoke-{agent}.toml`, reached by `.codex/agents`. |
| Cursor | Markdown `runtime/harness/cursor/agents/yoke-{agent}.md`, reached by `.cursor/agents`. |

Claude sidecars own its tools/model/hooks/turn fields. Codex emits required
`name`, `description`, `developer_instructions` and supported optional fields;
model inherits when omitted and is pinned only by explicit sidecar
`model_policy="pinned"`. Role posture uses native sandbox settings; Claude tool
strings and turn fields never become Codex fields. Read actual source/sidecar
and renderer before changing grants. Canonical responsibility survives
conditional omission of unsupported native primitives.

`bootstrap-spec.json#canonical_agents` and generated manifests point to bodies
without embedding them. `yoke agents render check` / `HC-agent-canonical-drift`
verify parity. Render canonical changes before syncing the install bundle;
never hand-edit generated adapters. [Agent reference](agents.md) points to
role/phase owners; [manifest schema](../runtime/harness/manifest-schema.md)
defines maintainer contracts.

### Shared dispatch

Skills author a `DispatchDescriptor`: role identity, task prompt, file routing,
claim context and result-ingestion contract. Claude maps it to its Agent tool;
Codex/Cursor consume their supported native adapters. Structured verdicts,
reflections, progress and QA land in the same durable owners regardless of
harness. The capability registry's `HARNESS_UNIVERSE` identifies registered
shapes; branch only where a real supported primitive differs.

Inline Shepherd/Conduct/Usher are skills, not new personas. Their immutable
item workflow binding owns the active segment, staffing, retry ceilings and
fresh handoffs. Worktree preparation continues in the same session; it is not
claim release, session end or relaunch. Separate-session workers take their
assigned claim. In-process subagent tools use the actual parent session identity
and its live claims; do not infer independent ownership from a role name.

## Recorded lane authority

Cwd is execution convenience. Every workspace-sensitive call uses the session's
active `work_claims`, with explicit absolute paths and source import anchors.
Sticky main-shell cwd and subagent tool cwd can differ; neither grants authority.
Use the registered lane returned by preparation, never compose it from a branch
slug or a machine checkout mapping. Read [lanes and claims](public/reference/agent-rules/lanes-and-claims.md)
before overlap/recovery and [source-dev doctrine](source-dev-doctrine.md) before
source execution/render/verification.

`session_claimed_worktrees.claimed_worktrees` reads recorded
`item_worktrees.path`. An item claim covers every active registered lane of that
item, in lane-id order, without role/first-lane filtering. An epic-task claim
covers only its `epic_tasks.item_worktree_id` lane. Released/no-lane claims
contribute no path. This remains valid over HTTPS when the evaluator machine
has no checkout. Holder reads and guards must agree.

```text
yoke claims work holder-get PREFIX-N
```

`lint_session_cwd_target_extract`, `lint_session_cwd_validate` and
`lint_session_cwd` extract targets, validate them and render outcomes. Edit/Read/
Write carry explicit targets; Bash uses parsed operands such as `-C`, rootdir
and absolute paths, with declared cwd as a synthetic target when none are found.
Claimed calls admit held lanes, control-plane roots excluding `.worktrees/`,
free paths and declared read-only exceptions. Known capacity operands inspect
totals without granting content/mutation. Unresolved home operands and missing
session identity refuse. Ordinary home/reference reads use executing-machine
facts and must earn their read-shaped exemption.

Foreign lane occupancy is checked before own-claim scope. Reads/plain sanctioned
Git inspection can inspect another holder's lane; writes, redirects, compound
mutations and state moves refuse. A claimed pre-implementation lane refuses
mutation by its pinned workflow/status gate. No-claim operator/maintenance
contexts retain their defined posture after identity/foreign-lane checks; this
is not a permission to enter another item's live lane. Client-evidenced machine
roots and session-scoped watcher scratch preserve the same authority over relay.

Denials name the offending target/claims and recovery: correct the path, acquire
the intended assigned claim or use its registered control-plane operation.
Destructive shell/Git remains independently guarded by `lint_destructive_git`.

For broad search, the read-only `yoke_core.tools.search_code` resolves claimed
roots (explicit main opt-in), uses canonical worktree resolvers, prefers `rg`
with a tested Python fallback and excludes Git/worktrees/cache/venv/node_modules/
dist/build. Output is path:line:match; multi-lane results identify their root.
It changes no claims, lifecycle or session state. Ordinary `rg` reads should name
the exact absolute intended scope.

### Writer and reader anchors

`workspace_authority.assert_target_under_session_work_authority` protects
tracked-source writers before write/atomic rename. Through transport-aware
`verification_tree_binding.resolve_claim_worktrees` / `claims.work.holder_list`,
it requires a held lane or shared free path, with the owner-defined
pre-implementation planning-scratch carve-out. It resolves explicit/ambient
identity; no identity, unavailable lookup or no worktree claims keeps its
operator/maintenance/test posture. Those helper behaviors do not replace the
separate per-tool/permission guards.

Covered writers include `agents_render._atomic_write`, Atlas audit/render and
registry-catalog rendering. `HC-workspace-anchored-writer-authority` uses the
canonical `IN_SCOPE_WRITERS` list in `.yoke/doctor/check_workspace_anchored_writer_authority.py`;
register new tracked-source writers there. Board rebuild is outside this helper:
it writes only untracked `.yoke/BOARD.md` and its timestamp on explicit request,
so it remains available to an item holder.

`assert_seed_source_under_target_root` independently refuses mixed-checkout
seed/schema imports before writing. Renderers and board rebuild use it; check/
dry-run can require it even without a session. Installed release modules and
legitimate external-project/test scratch targets follow the explicit owner
exemptions, not guessed source layout.

Renderer writers require `target_root` as a keyword. `agents_render_workspace`
readers prefer explicit root, then first active claimed worktree; missing both
raises unless `allow_ambient=True` explicitly opts into CLI cwd. CLI resolution
prefers argument, then `YOKE_RENDER_TARGET_ROOT`; repo-root fallback is permitted
only outside a linked worktree. Linked cwd without an anchor refuses. The
source-binding entrypoint re-execs mixed source before rendering.

`lint_workspace_cwd_match` separately refuses writer-class Bash/test/render
commands whose cwd is outside all held lanes. Its machine-config key is
`lint_workspace_cwd_match_mode` (dogfood defaults deny); warn audits. Its token
`# lint:no-workspace-cwd-check` records `suppression_attempted` and does not unblock.

## Resume, end and reactivation

Wakes target the existing native conversation. Manifest
`launch_model_selection_manifest.resume_selection` owns per-surface selection:

- Claude CLI `native` omits model/effort/context so native resume restores it.
- Codex/Cursor CLI `explicit` replays current attested model and expressible
  knobs. Codex re-reads user config and has no resume context-window selector.
  Cursor interactive last-model metadata differs from print-mode/shared config;
  omission cannot preserve every relay-owned selection.
- Desktop surfaces have operator-owned wakes and no stopped-session native
  resume. Pending messages inject when the operator continues the same chat;
  Yoke launches no separate turn or selector into those windows.

Before served attestation, explicit replay may use stored launch request.
Afterward, omissions are current truth: never fill them from old requests or
machine preferences, and never translate unsupported knobs silently.

`Stop`/`SessionEnd` use non-destructive `end_session_if_empty`. Transient sleep,
reload/disconnect/idle signals cannot release ownership. Holds include claims,
document locks, keepalive, pending launch delivery and in-flight wake delivery.
A caller can keep a claimless wake target alive with a bounded
`yoke sessions keepalive hold <session-id> --reason R [--seconds N]`, released
by `yoke sessions keepalive release` or expiry. The target's own tools do not
clear it; it protects idle reaping, not explicit termination. Relay-verified
process death records evidence and spares open claims/locks.

Explicit destructive session end with `--release-claims` follows
`sessions_render_end.end_session` / `sessions_lifecycle_destructive_guard`.
Released claims record `release_reason=session_ended`; `HarnessSessionEnded`
retains `agent_presence_evidence`. Checkpoint budget never prevents ending.
Heartbeat is tool recency, not proof of death. `sessions_cleanup` uses the empty
session TTL (`session_stale_ttl_minutes`) and document-lock holdings TTL, while
active work claims have no inactivity reclaim deadline. Persisted holdings are
read before startup/periodic cleanup, including relay restart.

`register_session` can atomically auto-reacquire previously session-ended claims
inside `session_reactivation_reacquire_window_s` (default 300s, machine config)
when no competing holder exists. `SessionReactivationReacquiredClaims` records
per-target reacquired/conflict outcomes. The next supported prompt/start event
renders prior targets, actual outcomes and explicit recovery once;
`HarnessSessionResumeBlockShown` marks the cycle and later reactivation re-arms
it. Hook registration is automatic; do not manually register a launch session.

## Path-claim guard surfaces

Path claims and file budget are independent effective policies; required scope
never shrinks to current coverage. Reconcile overlap before override. Coverage
protects edits at three boundaries:

1. Native Edit/Write/apply_patch PreToolUse validates target coverage.
2. Bash guard parses redirect/copy/move/remove/in-place mutations. Plain reads
   need no widening; patterns are not targets. A read with redirect still guards
   its output. An in-lane unexpected coverage failure names worktree preflight
   re-entry; designed new scope uses `yoke claims path widen --claim-id ID
   --add-paths PATH --reason R --item PREFIX-N`. Narrative owners are
   `path_claim_bash_guard_narrative` and `worktree_preflight`.
3. Pre-commit checks all staged files. `[no-path-claim-check]` records audit
   evidence but retains denial; missed tool-level coverage cannot land a commit.

Rewrite ambiguous shell into parseable operations first. The Bash parser's
`# lint:no-worktree-path-check` sentinel records `suppression_attempted` and allows
that parser verdict, as defined by `path_claim_bash_parser` / `path_claim_bash_guard`.
It does not grant claim, lane, filesystem or destructive-operation authority.
Do not conflate its effect with the strict workspace-cwd or commit tokens.

## Regeneration and installation ownership

`yoke agents render` regenerates Claude/Codex/Cursor agents and Cursor hook/
manifest outputs. Bootstrap canonical discovery and harness manifests have their
source/renderer owners; inspect generated markers before editing them. Doctor
checks canonical drift. Current definitions, bootstrap and exact tool/event
surfaces come from manifests, not a prose copy.

Cursor `.cursor/cli.json` / `.cursor/sandbox.json` are installer-owned unions of
Yoke's region, preserving operator entries and resolving network origins from
the installing machine config. They are not byte-exact renderer outputs;
`HC-cursor-permission-config` checks the region. Read current install ownership
before updating these settings.

A new harness needs a manifest, renderer shape, shared-descriptor consumer,
capability-registry membership, smoke runbook and applicable Doctor checks.
Canonical responsibility and skill semantics remain shared; native-specific
conditional blocks and enumeration sites may require source changes. Inventory
executor labels, identity/ancestry, decision wires, dispatch, install constants
and checks before claiming parity. [Cursor assessment](harness-cursor-assessment.md)
provides an integration inventory; the current manifest is live authority.

Related: [adapter template](harness-adapter-template.md),
[hook parity](hook-parity-map.md), [agents](agents.md),
[harness directory convention](../runtime/harness/README.md).
