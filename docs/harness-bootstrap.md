# Harness Bootstrap Contract (internal)

Source-maintainer contract for startup rendering, capability ownership and
adapter integration. Installed projects use their shipped rules and manifests;
they do not inherit contributor-only source procedures from this reference.

## Startup Reads

`runtime/harness/bootstrap-spec.json` is the executable ordered read list:
`required_files`, `required_commands` and optional `recommended_files`.
The shared `yoke_core.hooks.bootstrap` renderer resolves that spec. Hook,
wrapper or native configuration may provide the reads; the mechanism must
preserve the required standing rules before their governed actions.

`render_compact` lists existing required files and the shared main-session
startup block. It does not embed their contents, a command catalog or role
packet. `render_full` is a deliberate complete read: invariants, the startup
block, required file bodies, command output and available recommended files.
Missing file/command definitions are reported, never fabricated as present.
The shared short prompt doctrine remains in its canonical
[source](prompt-philosophy.md); live code explains itself without planning
provenance.

`yoke_core.domain.main_agent_packet` owns the identical startup block used by
source bootstrap and managed-project orientation. Keep connection authority
and message trust inline before receipt handling: authenticated envelope,
inert JSON body records, peer body without command authority and exact valid
message settlement. Include actual session identity and machine advisories;
never infer identity from the board. Optional recent commit, then branch
context, may be omitted to meet the target harness's inline UTF-8 budget;
authority, trust and identity remain. Measure the complete composed receiver,
not isolated fragments, and do not report unknown variable input as zero.

Schema and command depth is on demand:

```text
yoke packets render --role main_agent --topic T
yoke packets render --role main_agent --topic T --detail full
```

The seed and renderer own role/topic membership and full-depth recipes.
Generated packet bodies are never hand-copied into orientation. A broken
optional advisory probe cannot invent an identity or bypass authority.

## Layer Names: main_agent and harness_contract

| Layer | Authority |
|---|---|
| LLM-facing schema/API context | `schema_api_context_seed.ROLE_TOPICS`, topic owners and packet renderer |
| Substrate capabilities (`harness_contract`) | Installed-release harness manifest and [manifest schema](../runtime/harness/manifest-schema.md) |
| Workflow/skill semantics | Shared skill registry and the item's immutable workflow pin |

`harness_contract` is not a packet role. Adding an adapter changes its manifest,
not the schema role vocabulary. Hooks, env/session identity, cwd, render format,
tools, supported/disabled paths, wake primitives and parity limits must be
grounded in the target manifest before assertion. Canonical agent bodies are
`runtime/agents/`; generated adapters and manifest-declared conditional blocks
select each harness's primitives without exporting them to another harness.

## Safe Operator Commands

<!-- BEGIN GENERATED: skill-registry -->
Skill metadata is generated from `yoke_contracts.skill_registry`.
Change that source and run `yoke dev run -- python3 -m
yoke_core.tools.render_skill_registry_inline --target-root CHECKOUT`.

| Skill | Kind | Session mode | Autonomy | Purpose |
|---|---|---|---|---|
| `/yoke blitz {PREFIX-N}` | stage | `blitz` | autonomous execution | execute document-led work |
| `/yoke charge [--dry-run] [--item PREFIX-N] [--project P] [--wip-cap N]` | orchestrator | `charge` | autonomous execution | select runnable frontier work |
| `/yoke conduct PREFIX-N [--max-attempts N] [--no-chain]` | stage | `conduct` | autonomous execution | execute generated task lanes |
| `/yoke curate (no arguments)` | utility | `curate` | follow skill decision gates | curate the Ouroboros learning log |
| `/yoke dash "instruction" \| {PREFIX-N}` | stage | `dash` | autonomous execution | execute instruction-led work |
| `/yoke doctor [project] [--fix] [--file path]` | utility | `doctor` | follow skill decision gates | run health checks |
| `/yoke feed [--no-new-items] [PREFIX-N ...] [--model MODEL]` | orchestrator | `feed` | follow skill decision gates | refresh frontier work |
| `/yoke help` | utility | `wait` | follow skill decision gates | show command reference |
| `/yoke idea [--dry-run] [--workflow issue\|epic\|blitz\|task] {title}` | utility | `idea` | follow skill decision gates | file a backlog item |
| `/yoke implement {PREFIX-N} [--no-worktree] [--force] [--qa-bypass]` | stage | `implement` | autonomous execution | implement and review an item |
| `/yoke models lookup MODEL_ID \| get \| validate \| diff \| publish \| revisions \| restore \| level-proposal` | utility | `wait` | follow skill decision gates | publish model catalog revisions and propose level changes |
| `/yoke onboard [--project P] [--run-id RUN]` | orchestrator | `wait` | follow skill decision gates | make a wired project execution-ready |
| `/yoke polish {PREFIX-N}` | stage | `polish` | autonomous execution | review and finish implementation |
| `/yoke refine {PREFIX-N}` | stage | `refine` | follow skill decision gates | critique and improve item artifacts |
| `/yoke resync [--fix]` | utility | `wait` | follow skill decision gates | detect and repair GitHub drift |
| `/yoke shepherd {PREFIX-N}` | stage | `shepherd` | autonomous execution | execute the pinned planning interval |
| `/yoke simulate {epic-ref} [--auto-fix] \| --system` | utility | `simulate` | follow skill decision gates | trace integration paths; no terminal `yoke simulate` adapter |
| `/yoke steer [STRATEGY-DOC-SLUG] [--project P ...]` | orchestrator | `steer` | autonomous execution | staff work from a strategy document; omitted slug defaults to `CURRENT-PLAN` |
| `/yoke strategize [--model MODEL]` | orchestrator | `strategize` | follow skill decision gates | review project strategy |
| `/yoke usher PREFIX-N [PREFIX-N ...] [--dry-run] [--merge-only] [--deploy-only] [--resume PREFIX-N]` | stage | `usher` | autonomous execution | merge and deliver an item |
| `/yoke wrapup (no arguments)` | utility | `wrapup` | follow skill decision gates | wrap up the session |
<!-- END GENERATED: skill-registry -->

## Command Classification

| Surface | Use |
|---|---|
| Operator skill | Invoke its canonical procedure and obey decision gates |
| Internal skill | Follow only its parent's routed phase and authority |
| Registered CLI/function | Use its typed adapter, payload, claims and permission checks |
| Raw internal Python | Source-dev/operator diagnostics only where explicitly sanctioned |
| Git, gh and external tools | Their native command-shaped surfaces |

<!-- BEGIN GENERATED: skill-registry-internal -->
Internal skills are generated from `yoke_contracts.skill_registry`.

| Skill body | Purpose |
|---|---|
| `.agents/skills/yoke/amend/SKILL.md` | amend a synced task graph |
| `.agents/skills/yoke/approve/SKILL.md` | record a deployment approval |
| `.agents/skills/yoke/implement/implementing/SKILL.md` | kick off implementation |
<!-- END GENERATED: skill-registry-internal -->

Skills transition through `yoke lifecycle transition`, enforcing pinned gates;
commit fixes and refresh affected QA first. Item fields, claims, tasks, sessions
and deployment records use their registered owners. Raw service clients,
db-router mutations or internal helpers are not alternative agent entrypoints.
Diagnostic SELECTs use `yoke db read`; source-development break-glass retains
the separate [source-dev doctrine](source-dev-doctrine.md) authority.
The [function catalog](public/reference/db-reference/functions.md) and command
`--help` provide exact targets, envelopes, claim policy and recovery.

## Session Identity Expectations

The opening hook registers supported sessions automatically. Launch handoff
requires the launch's registered session to match the resolved current identity;
do not manually register or infer an assignment from an absent message.
Registration preserves the canonical stable harness conversation id,
workspace/project attribution, actor and executor family/surface. Canonical
harness families come from the shared executor owner and manifests; surface
aliases remain display facts, not a second identity. Client hooks may enrich a
previously unknown surface when observed; a relay server cannot infer the
client's surface from its own process.

Model/provider/effort/context metadata is truthful observed evidence, not
required invented data. Requested launch choices remain separate from served
identity. UI/fleet views label requests and retain differing values. Manifest
encoding and native observed variants select the knobs; a selectable model
label never attests a running session's context window. Preview validates each
knob, refuses conflicts and reports bounded safe runtime rejection without
silent fallback. Read the target manifest and native discovery before choosing.

`yoke_contracts.session_identity` owns the client-side ambient chain:
Yoke stamp, nearest process-tree harness family, that family's variables,
hook-written process anchors, then its conversation mapping. Inherited outer
harness variables cannot identify a nested session. Multiplexed hosts stop
anchor walks; PID reuse or live contention cannot select another session.
An unresolved identity is an infrastructure gap with operator recovery, never
permission to export a guessed session variable. `--session-id` is audited
operator-debug override. See the complete
[identity contract](session-identity-contract.md).

Supported commands/paths derive from the shared registry minus manifest
limitations. Harness-passed copied lists are not authority for Yoke-owned
harnesses. Resolve unknown executor behavior from the actual registry owner;
do not present an unknown manifest as verified support. Unsupported downstream
work retains its named routed recovery.

### Session scratch cleanup

Only positively dead registered owners, or non-harness unknown-session runs
whose process is proven dead, permit cleanup. Preserve active, unknown, live or
unverifiable owners; recheck PID liveness and hold the machine sweep lock.
Registry unavailability fails mutation closed. Filesystem age alone is not
ownership proof. Doctor fix uses the same contract; see
[scratch root](scratch-root.md) before recovery.

## Machine Identity and Launcher Authority

Machine registration and its access document own launch capacity; unregistered
machines refuse with registration recovery. Setup Apply/status perform their
declared registration. Read [machine registry](machine-registry.md) for owner,
human name, capacity and same-universe actor permission.

Launcher diagnosis follows the actual command shell before inherited `$SHELL`;
only zsh's unmatched-glob semantics justify that guard. Unknown shell does not
establish zsh. Path authority and scratch writers admit canonical absolute
client temp/home identities, never a server-home guess. The login-shell launcher
must be the installed canonical shim; repair quarantines PATH shadows instead
of deleting them. Use the install owner's named repair from the operator shell.

## Standing Relay Release Authority

Setup installs the exact connection and machine config it is writing. Retry
first verifies whether that relay is already loaded, configured identically
and running a present current build; satisfied means no restart. Unreadable or
incomplete state needs repair and preserves the installer's bounded redacted
refusal, exit status and recovery.

For HTTPS, the native user service executes the stable relay runtime interpreter.
Isolated bootstrap resolves one physical immutable release and binds supervised
Python children to it. Vendor CLIs and surface probes drop relay activation
variables and relay-owned bin directories, preserving the user's PATH and
installed launcher so project commands cannot install into the relay. The
release comes from that environment's distribution index, never an editable
checkout. OS consent remains conditional on actual protected-content access.

A local universe instead runs its installed launcher and has no served pin or
distribution handshake. Missing launcher refuses with repair. Paired
prod-flagged Postgres administration owns no second relay; the served HTTPS
connection supplies it. [Linux relay](public/reference/linux-relay.md) owns its
user-service/login/logout/no-linger procedure and named systemd recovery.

Fresh handshake alone triggers upgrade: install beside the active release,
verify load, atomically repoint, drain jobs and exec the stable runtime entry.
Fetch/load failure retains the prior working process and pin and records retry
evidence. Status reports both loaded service and authenticated poll outcome.
A matching receipt alone is not readiness: the isolated runtime must import
the pinned release's actual packages and report its exact core build. Editable
or outside-release imports refuse; checks are bounded and run when asserting
readiness/reuse, never every heartbeat. Candidate checks precede pointer swap.
Every candidate-install child is isolated from the active release's package
path. Repair from an ordinary login shell through `yoke --env ENV relay install`;
remove inherited `PYTHONPATH` for that invocation. Retain installed releases.

### Report retries and custody

Permanent report rejections include settled conflict, expired lease, closed job,
missing/mismatched attempt and invalid payload. Launch reports quarantine after
three permanent rejections without retaining claims; wake reports quarantine
immediately and release finished resume custody. Preserve refusal evidence and
do not replay quarantined reports. Early operator quarantine requires existing
report-scoped permanent evidence and records path/digest. Connectivity or
ambiguous failures retain resume custody or the launch retry queue; pending
launch retries hold new claims until drained. A timeout is not a permanent
rejection. Use relay health and the named recovery, not a guessed replay loop.

Claude usage counts each assistant message id once across incremental folds and
repeated compaction history. Watermark ids, per-model totals, reader version and
offset save atomically without transcript content. Codex replaces cumulative
totals. Do not convert unknown readings to zero.

### Hook evaluation and remount

Hook/guard fingerprints expose source SHA, install kind/path and both client/
server origins when relayed; timeout names local fallback. Authorized request
project binds all hook scratch for that request without process-wide env or
server-checkout inference. Unstamped or conversation-shaped session identity
cannot authorize a write. Identity failure denies writes only. Hook replay
returns the verdict without anchor/map/remount/registration writes.

Cursor's new conversation after remount does not name its prior holder. The
client records a short-lived remount-expect receipt on the main checkout; the
linked-worktree hook consumes it before aliasing. A live holder with no receipt
is identity failure, not an inferred folder fold.

## Unattended Permission Posture

`yoke_contracts.session_control.launch_permission_bypass` owns launched-worker
flags; `yoke_contracts.harness_unattended_posture` owns persistent machine config
for operator-opened sessions. The install/setup plan names each detected
harness, path, key and undo in Review. `--skip-harness-permissions` excludes
the step from preview/apply. A harness absent from the machine is skipped.

| Harness | Managed machine configuration |
|---|---|
| Claude | Platform desktop config and `~/.claude/settings.json` permissions |
| Codex | Resolved `CODEX_HOME/config.toml` approval/sandbox and project trust |
| Cursor | `~/.cursor/cli-config.json` approval/sandbox |

Use the owner to resolve exact keys and platform paths; [Linux paths](harness-linux.md)
retain existing-file and explicit-false behavior. Write only absent keys,
preserve operator values and unrelated settings, and report each write or
conflict. Inventory/Doctor report actual posture; config presence is not proof.

Folder trust is separate and path-specific. Project install/lane creation write
the exact checkout's declared trust; do not assume a parent covers a worktree.
Command-prefix allowances cannot admit an enclosing shell loop/substitution.
Repeat authorized calls plainly; do not weaken a gate to hide a prompt.

## Repo-local Skill Discovery

Canonical skills are `.agents/skills/yoke/`: root/direct `SKILL.md` bodies,
nested internal bodies and phase/support files. Phase files and support
directories are not standalone skills. Hidden-path discovery must explicitly
include hidden files. `.claude/skills/yoke` is a native discovery symlink;
wrapper/tooling paths remain canonical `.agents/...` paths. Native harness
loaders use their declared discovery; no parallel mirror is needed for symmetry.

The existing source bootstrap resolver supports:

```text
yoke dev run -- python3 -m yoke_core.hooks.bootstrap skill-list --root CHECKOUT
yoke dev run -- python3 -m yoke_core.hooks.bootstrap skill-path NAME --root CHECKOUT
```

These retained source-tool modes enumerate top-level bodies or return the
absolute canonical path. Missing names refuse with that path; no home-directory
fallback. Discovery modes need no bootstrap spec. Wrapper-only adapters verify
the tree before routing; thin inventories derive names rather than copy them.
Do not add a shell resolver or per-skill sidecars without a current need and
one canonical metadata owner.

## Hook Approval

`yoke_contracts.harness_hook_approval` owns declared hook-specific gates; absence
from its mapping means no declared requirement, not proof of no security gate.
Workspace trust remains separate. Install/setup and activation health read the
same declaration instead of inventing a harness-specific prompt.

Yoke mints Codex trust only for the exact hooks file it just authored, at the
literal checkout path and current content hash. Byte-identical lanes may mirror
that trust; changes outside the install boundary invalidate it and require the
operator's re-trust. Other harness gates and non-Yoke changes remain
operator-owned. Doctor reports main, lane and stale deleted-path entries.
Missing recent telemetry is an unobserved hook, not a diagnosis of approval;
readable untrusted state names its actual repair surface.
