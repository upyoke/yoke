# Advance — Worktree Preflight + Re-entry

> **Orchestrator role:** For implementation-entry advances, the advance implementation-entry orchestrator ([`runtime/api/engines/advance_implementation_entry.py`](../../../../runtime/api/engines/advance_implementation_entry.py)) calls `worktree_preflight.run_preflight` directly and emits the outcome as `AdvancePhaseCompleted{phase="worktree"}`. The doc below remains the canonical contract for the worktree-preflight envelope and exit codes — the orchestrator's reference. The CLI invocation below remains valid for operators reconciling worktree state outside the orchestrator.

Called by the advance router when target status is `implementing` (including issue `implementation` entry). Owns collision detection, dirty-main protection, canonical/legacy worktree recognition, and worktree creation. The session's write authority over the new worktree is its work-claim (acquired in Step 1), validated per tool call by `lint_session_cwd`.

This phase is **Python-owned** through `yoke_core.domain.worktree_preflight`. The skill prose no longer hand-authors any of the shell snippets that previously routed agents through guard-hostile shapes (`db_router query -separator "|"`, manual `.worktrees/` `ls`, project shell-variable lookup, dirty-tree compound).

**Context variables** (set by router): `{N}`, `_type`, `--no-worktree` flag, `--force` flag

**Enforcement owner:** `runtime/api/domain/worktree_preflight.py` (orchestrator + CLI), with step helpers in `runtime/api/domain/worktree_preflight_steps.py`.

---

## Invocation

Normal implementation-entry advance invokes `worktree_preflight.run_preflight`
in-process through the orchestrator. The standalone worktree-preflight CLI is a
Yoke source-dev/admin boundary for operators reconciling worktree state outside
the orchestrator; no registered product CLI wrapper exists, so do not teach it
as normal product flow.

Optional flags:

- `--project <id>` — supply when the item targets a project other than `yoke` (the orchestrator otherwise resolves the project from the item row).
- `--no-worktree` — evidence-only items: skip worktree creation but still resolve the work claim, activate path claims, and emit the envelope (with `semantic_scope=main`).
- `--session-id <id>` — override the session id (defaults to the standard `YOKE_SESSION_ID` / `CLAUDE_SESSION_ID` / `CODEX_THREAD_ID` env chain).

Exit codes:

| Exit | Meaning                                                                  |
|---   |---                                                                       |
| 0    | Success. The execution envelope is on stdout as JSON.                    |
| 1    | Sanctioned block (`work-claim-conflict`, `path-claim-blocked`, `dirty-tracked`, `dirty-untracked`, `worktree-create-failed`). Narrative on stderr; do NOT advance status. |
| 2    | Bad input (missing / malformed `--item`).                                |

The envelope shape is the operator-defined shape — see the Operator Handoff Addendum for the contract:

```json
{
  "ok": true,
  "item_id": 1234,
  "branch": "YOK-N",
  "worktree_path": "/Users/.../.worktrees/YOK-N",
  "semantic_scope": "worktree",
  "physical_cwd_mode": "static",
  "actions_taken": ["work-claim:already-owned", "path-claim:activated=[39]", "worktree:reused"],
  "notes": ["..."]
}
```

## Harness cwd is independent of write authority

A harness may keep its physical cwd at the main checkout even after the worktree is provisioned. The envelope reports `physical_cwd_mode=matched` when cwd is inside the worktree and `physical_cwd_mode=static` when cwd stayed at main. Yoke treats both as supported — write authority comes from the session's work-claim, not from cwd.

**`cd "<worktree>"` is the canonical first action after worktree provisioning** when the harness supports a sticky cwd. The implementation sub-skill teaches it as Step 0 of [`implementing/implementation.md`](implementing/implementation.md); read that step verbatim. On sticky-cwd harnesses (Claude Code / Claude Desktop), the `cd` silently persists across subsequent Bash tool calls because `.worktrees/<branch>/` lives inside the declared project root — every later Read/Edit/Write/Grep/Glob and every later `pytest` / `python3 -m pytest` / `python3 -m yoke_core.tools.watch_pytest` invocation resolves relative paths against the worktree automatically. Without the `cd`, sticky cwd stays at the main checkout, pytest's positional collection path resolves under main, and the wrong tree gets exercised silently. `watch_pytest` hard-refuses wrong-cwd invocations under a worktree-bearing claim — `cd` once at the top of the session and the refusal never fires.

On static-cwd harnesses (Codex's terminal — `physical_cwd_mode=static` AND no sticky cwd between Bash calls), the `cd` does not persist between calls. Use absolute paths for worktree-bound tool calls — `git -C <worktree> ...` for git ops, absolute paths under `<worktree>/...` for Edit/Read/Write, and `python3 -m pytest --rootdir <worktree> <test-target>` for pytest (run directly as a foreground command since Codex relies on native PTY streaming).

Either way, `lint_session_cwd` validates each call's target paths against the session's claimed worktree set; mismatched targets are denied with a clear "no active claim covering this path" reason.

## Recursive discovery in the bound worktree

Broad relative `grep -r` against the bound worktree is correctly suspicious
when the harness's physical cwd is at main — the helper below is the
canonical shape for recursive discovery so agents do not need to author
relative recursive commands that the per-call target-path validator would
flag as ambiguous:

```bash
python3 -m yoke_core.tools.search_code --item YOK-{N} --pattern PATTERN \
    --scope worktree   # default — searches the bound worktree(s)
python3 -m yoke_core.tools.search_code --item YOK-{N} --pattern PATTERN \
    --scope main       # searches the project repo root only when explicit
```

The helper resolves absolute roots via `yoke_core.domain.worktree_item_resolve`,
applies safe default excludes (`.git`, `.worktrees`, cache dirs, virtualenvs,
`node_modules`, `dist`, `build`), prefers `rg` when present and falls back
to a tested Python implementation. Output shape is `<path>:<line>:<match>`;
multi-worktree epic items prefix each match with the worktree root.

Single-file `grep PATTERN /absolute/path/file` and other single-target
read-only inspection pass `lint_session_cwd` because their target paths
are absolute and land under the claimed worktree — use those shapes when
the discovery target is already known. Reach for `search_code --scope
worktree` when the recursive walk is the point.

## What preflight handles internally

- **Step 1 — Work claim.** Idempotent for same-session re-claim. A live conflict surfaces a `work-claim-conflict` block with a narrative that explicitly disclaims claim-widening as the wrong remediation.
- **Step 2 — Path-claim activation.** Delegates to `yoke_core.domain.advance_path_claim_activation` (the path-claim activation CLI). Diverged refs and blocked claims propagate to the caller verbatim.
- **Step 3 — Worktree resolution.** Canonical `YOK-N` is reused idempotently.
- **Step 3 — Dirty-main guard.** Runs **only** when this call would create a new worktree. Tracked or staged dirt blocks as `dirty-tracked`; untracked non-gitignored files block as `dirty-untracked`. Re-entry into an existing worktree never touches main and is never blocked by main dirt.
- **Step 4 — Worktree creation + DB write.** `create_worktree` records branch + status on the item. The session continues — no scope envelope, no parent-stop, no claim release, no relaunch. The work-claim acquired in Step 1 is the session's authority over the new worktree, validated per tool call by `lint_session_cwd`.
- **Step 5 — Envelope rendering.** Emits descriptive `semantic_scope`, `physical_cwd_mode`, and an optional advisory note if the harness cwd is static at main (informational only — the work-claim is what authorizes writes).

## Failure handling

`worktree_preflight` returning a non-zero exit code is **always** a sanctioned block. Surface the stderr narrative verbatim and stop the advance — do not advance status, do not retry, and do not paper over the block with `--force` or path-claim widening.

For `work-claim-conflict`, the right remediation is to coordinate with the holder or wait. For `path-claim-blocked`, follow the `BLOCKED:` / `DIVERGED:` rows to the upstream coordination ticket. For `dirty-tracked` / `dirty-untracked`, commit / stash / remove / gitignore on main and retry. For `worktree-create-failed`, surface the `git worktree add` error verbatim and stop.

## --no-worktree

Pass `--no-worktree` only for evidence-only items that intentionally make no repo changes. The envelope sets `semantic_scope=main`, omits `physical_cwd_mode`, and records `worktree:skipped` in `actions_taken`. The downstream done-transition empty-branch guard is satisfied because no worktree is recorded on the item.

---

After preflight returns `ok=true`, return to the router to continue with the environment phase and finalize. The session does NOT stop and does NOT relaunch.
