# Codex Harness Smoke-Test Runbook

Manual verification matrix for wrapper-only and hook-enhanced Codex modes. This runbook proves the full Tier 1 operator surface — including `/yoke conduct` — runs end-to-end on Codex. The core proof points are the `apply_patch` deny smoke (PreToolUse write-side guardrails on Codex's file-edit tool) and the Codex agent smoke (rendered `.toml` custom agents dispatched through shared dispatch descriptors). Both are exercised below and in the automated test matrix referenced from this runbook.

Last updated: 2026-05-29 (Step 14 split into runnable schema, protocol-schema, and Desktop-spawn proof lanes; unfinished `config/read` automation moved out of the required smoke path)

## Prerequisites

- Codex CLI installed (any build with Bash tool support for wrapper-only)
- For hook-enhanced mode: Codex >= 0.118.0-alpha.2, launched with `codex app <repo>`
- Yoke repo checked out at a known-good state
- Connected Postgres authority available (at least one backlog item for routing tests)

## Mode 1: Wrapper-Only

Wrapper-only mode is any Codex build without hook support: no session hooks
fire, so all correctness comes from Yoke core and the agent reaches Yoke
through the `yoke` CLI and the `/yoke` prompt commands. There is no separate
entry launcher — Codex loads the repo's own rules files, and the startup
reads are rendered on demand.

### Step 1: Bootstrap orientation

```sh
python3 -m runtime.harness.bootstrap render-full --spec runtime/harness/bootstrap-spec.json --root .
```

**Verify:**
- [ ] Output includes `=== AGENTS.md ===` section
- [ ] Output includes `=== harness-bootstrap.md ===` section
- [ ] Output includes the `main_agent` packet block

### Step 2: Identity resolution without hooks

```sh
yoke sessions whoami
```

**Verify:**
- [ ] Reports `executor: codex` when run inside Codex
- [ ] Does NOT report `YOKE_SUPPORTED_PATHS` (capabilities derived server-side)

### Step 3: Operator entrypoints

Wrapper-only mode routes every operation through the prompt-level `/yoke`
commands and the `yoke` CLI; there is no launcher indirection to verify.

**Verify:**
- [ ] `/yoke idea "Test smoke idea"` files an idea
- [ ] `/yoke do` returns a session offer
- [ ] `/yoke refine YOK-N`, `/yoke advance YOK-N implementation`,
      `/yoke polish YOK-N`, and `/yoke usher YOK-N --dry-run` each route

### Step 6: Decision engine path validation

This step verifies the decision engine respects the shared-registry `supported_paths` set after applying manifest limitations. The truthful check is through the shared session-offer service tests, because constructing `SessionOffer(...)` directly bypasses the server-side derivation path.

```sh
python3 -m pytest runtime/api/test_service_client_sessions_offer.py -k "limits_when_input_omitted or limits_override_spoofed_supported_paths"
```

**Verify:**
- [ ] The shared-registry Codex path set is honored when the caller omits `--supported-paths`
- [ ] Spoofed caller input does not override the shared-registry Codex path set

### Step 7: Shepherd proof sequence

In a Codex session (wrapper-only mode):

```
# After bootstrap, use the operator command:
/yoke shepherd YOK-{N}
```

Where `YOK-{N}` is an item in `idea` status that needs shepherding.

**Verify:**
- [ ] Shepherd completes without routing errors
- [ ] Item progresses through shepherd stages
- [ ] No unsupported-path escalation occurs (shepherd is in supported_paths)

### Steps 8-11: Tier 1 proof lanes (refine, advance, polish, usher)

Run each operator command in a Codex session against an item in the right status:

| Step | Command | Status precondition | Verify |
|------|---------|---------------------|--------|
| 8 | `/yoke refine YOK-{N}` | Spec/plan worth tightening | Codex reads structured fields, writes via `python3 -m yoke_core.cli.db_router items update <id> <field> --stdin`; no worktree or code edits |
| 9 | `/yoke advance YOK-{N} implementation` | Implementation-eligible issue | Codex creates or re-enters the issue worktree; implementation and review stay in the same worktree; `advance` in supported_paths |
| 10 | `/yoke polish YOK-{N}` | Existing worktree branch | Codex resolves the recorded worktree, reviews diff against artifacts, commits fixes on the branch, runs verification from the worktree root |
| 11 | `/yoke usher YOK-{N} --dry-run` | `implemented` item | Dry-run eligible; hard-block deps empty/explained; blocking QA count zero; deployment routing explicit; `usher` in supported_paths |

### Step 12: Conduct proof lane

Conduct is a Codex-safe Tier 1 entrypoint. In a Codex session, run conduct against a dispatch-ready epic:

```
/yoke conduct YOK-{N}
```

**Verify:**
- [ ] Codex advertises `conduct` as a supported operator entrypoint and downstream path
- [ ] The shared dispatch descriptor module remains the cross-harness source for subagent task envelopes
- [ ] Result ingestion records Engineer / Tester outcomes without Claude-only `subagent_type` assumptions
- [ ] The parent item reaches the reviewed-implementation handoff or reports a Yoke-owned gate failure

### Step 13: apply_patch deny smoke (core proof point)

This step verifies the Codex `PreToolUse(apply_patch)` hook denies write-side guardrail violations the same way Claude's Write/Edit matchers do.

In a Codex session inside a worktree, attempt an `apply_patch` mutation that violates a write-side guardrail (for example, editing a path outside the worktree's path-claim coverage, or a lifecycle-mutation command without the suppression token):

**Verify:**
- [ ] The hook denies the call before the patch lands
- [ ] The denial event (`HarnessToolCallDenied`) appears in the events table with `tool_name=apply_patch`
- [ ] Remediation message names the violated guardrail (path-claim, lifecycle-mutation, write-path)
- [ ] The same hook subsequently allows a compliant `apply_patch` against a path inside coverage

### Step 14: Codex Desktop custom-agent schema load smoke (core proof point)

Proves the generated `.codex/agents/yoke-*.toml` adapters satisfy Yoke's pinned schema contract, the installed Codex app-server protocol still advertises the custom-agent/subagent surfaces Yoke depends on, and the Desktop runtime can spawn a real Yoke custom agent after it reloads `.codex/agents`.

First, run the deterministic adapter-schema check:

```sh
python3 -m pytest runtime/api/domain/test_agents_render_codex_schema.py
```

Then, generate the installed Codex app-server protocol schema and confirm the relevant protocol names still exist:

```sh
_schema_dir=$(mktemp -d /tmp/codex-app-server-schema.XXXXXX)
codex app-server generate-json-schema --experimental --out "$_schema_dir"
rg -n 'config/read|externalAgentConfig/detect|SubagentStart|SubagentStop|agent_role|agent_nickname' "$_schema_dir"
```

Finally, run the actual Desktop registration proof. Fully quit and relaunch Codex Desktop before attempting a custom-agent spawn. On codex-cli 0.133.0 the in-app `multi_agent` spawn surface rejected `agent_type="yoke-architect"` as an unknown agent type until the app was restarted; after a clean relaunch `multi_agent_v1` advertised and spawned all seven Yoke custom agents from `.codex/agents`. Newly rendered `.codex/agents/yoke-*.toml` adapters are picked up by the spawn surface only after the relaunch.

Do **not** use `externalAgentConfig/detect` as registration evidence. On codex-cli 0.133.0 it reports external migration candidates, not the already-loaded custom-agent registry; it returned no subagents for the Yoke checkout even with valid `.codex/agents` symlinks. A successful `multi_agent_v1` spawn after restart is the registration proof.

`config/read` is not part of this required smoke. It is an app-server JSON-RPC method, not a `codex app-server config/read <path>` subcommand, and the exact daemon/proxy transport plus request params need a separate automation recipe before this runbook can rely on it.

**Verify:**
- [ ] `runtime/api/domain/test_agents_render_codex_schema.py` passes
- [ ] `generate-json-schema` succeeds for the installed `codex` binary
- [ ] The generated protocol schema still names `config/read`, `externalAgentConfig/detect`, `SubagentStart`, `SubagentStop`, `agent_role`, and `agent_nickname`
- [ ] No `Ignoring malformed agent role definition` / `expected struct ToolsToml` lines for any `yoke-*.toml`
- [ ] A real spawned Yoke custom agent (for example `yoke-architect`) starts from the repo without schema warnings — spawned via the `multi_agent_v1` surface after the Desktop restart above

**CI-contingency (native Desktop/app-server smoke unavailable):** the pytest schema check is the minimum automated gate. It `tomllib`-parses every adapter and asserts the required `name` / `description` / `developer_instructions` keys, the absence of the retired `prompt` / `tools` / `max_turns` fields, and the role `sandbox_mode` posture. The Desktop spawn remains the authoritative runtime registration proof.

**Role posture:** adapters declare `sandbox_mode` = `read-only` for the read-only roles (product-manager, product-designer, architect, tester, simulator, boss) and `workspace-write` for the engineer; `model` is omitted so each subagent inherits the parent session model. Official Codex docs state subagents inherit the parent sandbox policy and that custom agents may override sandbox config, so record the observed behavior when a real custom agent is spawned. Read-only write-prevention does not depend on `sandbox_mode` alone — the `PreToolUse(apply_patch)` write-side guard (Step 13) plus parent-session policy enforce it regardless.

---

## Mode 2: Hook-Enhanced

Hook-enhanced mode adds `.codex/hooks.json` hooks on top of the wrapper-only baseline. Requires Codex >= 0.118.0-alpha.2 with hook support.

### Enablement

1. Verify Codex version: `codex --version` (must be >= 0.118.0-alpha.2)
2. Verify `.codex/hooks.json` exists at repo root (symlink to `runtime/harness/codex/hooks.json`)
3. Fully quit and relaunch Codex Desktop
4. Open a brand-new Yoke thread in the Yoke repo after the app launches

Note: current Codex builds do not need a separate feature flag here. The proven Desktop setup is the repo-local `.codex/hooks.json` pack (backed by the canonical `runtime/harness/codex/hooks.json`) plus a clean app relaunch.

### Step 1: Session start hook

Start a new Codex session in the Yoke repo.

**Verify:**
- [ ] Orientation context is automatically injected (no manual bootstrap needed)
- [ ] Output includes `## Yoke Orientation (Codex hook-enhanced)`
- [ ] Output includes `Executor: codex`
- [ ] Fire-once: refreshing the session does NOT repeat orientation

### Step 2: Prompt submit hook

Submit a prompt in the Codex session.

**Verify:**
- [ ] First prompt shows safe operator command reminder
- [ ] Second prompt does NOT repeat the reminder (fire-once)

### Step 3: Pre/Post tool hooks

Execute a Bash command in the session:

```
echo "hello world"
```

**Verify:**
- [ ] Pre-tool hook fires (check for any lint guard output if applicable)
- [ ] Post-tool hook fires (check for any observation output)
- [ ] Both hooks exit 0 (no errors)
- [ ] Hooks degrade gracefully when Yoke scripts directory is missing

### Step 4: Shepherd with hooks

Run the same shepherd proof sequence as wrapper-only mode Step 7, but now with hooks active.

**Verify:**
- [ ] Same shepherd behavior as wrapper-only
- [ ] Hook-injected orientation makes bootstrap step unnecessary
- [ ] Event lineage: HarnessSessionOffered and NextActionChosen events are emitted (verify via `events` table or API)

### Step 5: Stop hook (direct cleanup)

`Stop` is wired into `runtime/harness/codex/hooks.json` and dispatches through the identity-pinned command shape `env YOKE_EXECUTOR=codex YOKE_PROVIDER=openai PYTHONPATH=... python3 -m runtime.harness.hook_runner Stop`, with the same shared runner entrypoint Claude uses. The dispatch routes to `runtime.harness.hook_runner.session_dispatch._run_stop`, runs bounded `session-end-if-empty`, and returns `{}`.

Inside a hook-enhanced Codex session, allow the assistant to finish a turn so Codex emits `Stop`. Then, from the operator shell, capture the most recent lifecycle telemetry for this session:

```sh
python3 -m yoke_core.cli.db_router query "SELECT event_name, created_at, event_outcome FROM events WHERE session_id='<session_id>' AND event_name IN ('HarnessSessionEnded','ChainEndDeferred','HarnessSessionHookFailed') ORDER BY created_at DESC LIMIT 10"
```

**Verify:**
- [ ] The hook command in `runtime/harness/codex/hooks.json` includes `YOKE_EXECUTOR=codex`, `YOKE_PROVIDER=openai`, and resolves to `python3 -m runtime.harness.hook_runner Stop`
- [ ] `runtime.harness.hook_runner Stop` exits 0 (no chain failure surfaced back into Codex)
- [ ] **Codex `Stop` stdout is exactly `{}`** — the JSON contract is preserved even when direct cleanup times out or the service client is missing
- [ ] Exactly one of `HarnessSessionEnded` or `ChainEndDeferred` is present when the session was eligible for cleanup
- [ ] `HarnessSessionHookFailed` is absent for a clean run and present only when direct cleanup cannot complete
- [ ] Caveat preserved: Codex `Stop` is a **turn-boundary cleanup**, not an archive trigger. The next prompt may legitimately re-register the same stable Codex thread/session id and clear `ended_at`.

## Automated Test Coverage

The following test scripts validate the matrix programmatically:

| Test file | Coverage |
|-----------|----------|
| `runtime/harness/test_bootstrap.py` | Neutral bootstrap spec/helper: ordering, doctrine rendering, drift guard |
| `runtime/api/test_service_client_sessions_offer.py` | Decision engine: shared-registry supported paths and session-offer behavior |
| `runtime/api/test_capability_consistency.py` | Shared registry, Codex manifest limitations, and CODEX.md capability drift guards |
| `runtime/harness/test_hook_runner.py` | Shared hook runner: dispatch, identity, lifecycle, graceful degradation |
| `runtime/harness/test_hook_runner_runner.py` | Hook runner chain execution: per-event sub-handler ordering and fanout |
| `runtime/harness/test_hook_runner_telemetry.py` | Hook runner telemetry: tool-call denial events, latency, payload shaping |
| `runtime/api/domain/test_agents_render_substrate.py` | Codex custom-agent renderer: `.codex/agents/yoke-*.toml` parity with canonical bodies + subdir fragments |
| `runtime/api/domain/test_agents_render_codex_schema.py` | Codex custom-agent schema: every `yoke-*.toml` parses with `tomllib`, carries required `name`/`description`/`developer_instructions`, omits retired `prompt`/`tools`/`max_turns`, declares role `sandbox_mode` posture |

Run them:

```sh
python3 -m pytest runtime/harness/test_bootstrap.py
python3 -m pytest runtime/api/test_service_client_sessions_offer.py
python3 -m pytest runtime/api/test_capability_consistency.py
python3 -m pytest runtime/harness/test_hook_runner.py
python3 -m pytest runtime/harness/test_hook_runner_runner.py
python3 -m pytest runtime/harness/test_hook_runner_telemetry.py
python3 -m pytest runtime/api/domain/test_agents_render_substrate.py runtime/api/domain/test_agents_render_codex_schema.py
```

## Event Lineage Verification

The session-offer path emits two canonical events regardless of harness:

1. **HarnessSessionOffered** -- emitted before decision-engine evaluation; includes `supported_paths`
2. **NextActionChosen** -- emitted after the engine returns a directive; includes `action`, `reason`, `correlation_id`

In wrapper-only mode, these events are emitted by the shared session-offer path (`service_client.py` / API endpoint), not by the entry launcher. The launcher prints or exports the identity contract (`YOKE_EXECUTOR`, `YOKE_PROVIDER`, `YOKE_MODEL`), and Yoke core derives `supported_paths` from the shared registry plus manifest limitations keyed by `executor`. Operators still enter this flow through `/yoke do`; the direct `service_client.py session-offer` call is an internal implementation detail of the shared loop.

To verify lineage after a `/yoke do` invocation:

```sh
python3 -m yoke_core.cli.db_router query \
  "SELECT event_name, created_at FROM events WHERE event_name IN ('HarnessSessionOffered','NextActionChosen') ORDER BY created_at DESC LIMIT 10"
```
