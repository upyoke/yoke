"""``claims`` topic wrapper-command recipes for the agent-context packet.

Sibling of :mod:`schema_api_context_commands` (which combines per-topic
lists into the canonical ``WRAPPER_COMMANDS``). Holds the ``claims``
topic entries: work-claim acquire/release, path-claim CRUD/widen,
path-claim conflict inspection, and the coordination-decision helper.

Recipe shape doctrine (current):
    The canonical claim function ids (``claims.work.acquire``,
    ``claims.work.release``, ``claims.path.register``,
    ``claims.path.widen``) use the strict ``yoke <subcommand>``
    grammar (CLI grammar contract). Break-glass or not-yet-wrapped claim
    surfaces are described as dispositions instead of taught as
    copy-paste command recipes.

Pure data only — no I/O, no DB connections, no imports beyond stdlib.
"""

from __future__ import annotations


CLAIMS_COMMANDS: list[dict] = [
    {
        "topic": "claims",
        "purpose": "Lookup live claim holder for an item",
        "recipe": ("yoke claims work holder-get PREFIX-N"),
        "notes": (
            "Registered read surface (function id "
            "`claims.work.holder_get`) for the live holder. Returns item "
            "-> claim row -> session row link. **Artifact writes require "
            "owning the item claim** — spec, body sections, File Budget, "
            "path-claim register/widen/narrow/release, and GitHub "
            "issue-body edits are shared coordination state, work writes "
            "governed by the same item-claim ownership as code edits. "
            "The session id returned here is a coordination identifier, "
            "not authority to mutate as that holder; copying it into "
            "`--session-id S` grants no capability over that holder's "
            "claim."
        ),
    },
    {
        "topic": "claims",
        "purpose": "Acquire a work claim (canonical agent shape — target variants)",
        "recipe": (
            "yoke claims work acquire --item PREFIX-N "
            "--reason draft-in-progress\n"
            "yoke claims work acquire --epic-id 833 --task-num 5 "
            "--reason engineer-dispatch\n"
            "yoke claims work acquire --process DOCTOR --project yoke "
            "--reason scheduled-run"
        ),
        "notes": (
            "Reason recommended on acquire, required on release. Pick "
            "exactly one target variant. Optional --session-id S is a "
            "self-identity assertion that the caller IS the named "
            "session; it is not cross-session authority. Steering claims "
            "are project-scoped work claims: `yoke claims steering acquire "
            "--project P [--reason TEXT]`. A second live steering claim for "
            "the project refuses and names its holder. Inspect with `yoke "
            "claims steering list --project P --active-only`; finish with "
            "`yoke claims steering release CLAIM_ID --reason TEXT`. Ordinary "
            "release and stale-session reclaim free the steering seat. The "
            "itemless loop is `/yoke steer SLUG [--project P]`: a strategy "
            "doc is required (offer to create if absent), the document lock "
            "releases before a Blitz can claim it, workers launch CLI-only "
            "and item-bound (never `/yoke do`), workers are addressed with "
            "`yoke say --item PREFIX-N --stdin` (`--session UUID` only for "
            "claim-less recipients), and the fleet report arrives appended "
            "to the messages this session receives — available work first, "
            "then idle holders, starved delivery, unregistered launches, "
            "items landed without close-out, and dead waits; pull it between "
            "wakes with `yoke steering report get --project P`."
        ),
    },
    {
        "topic": "claims",
        "purpose": "Claim → mutate → release (generic plan-stage edit)",
        "recipe": (
            "yoke claims work acquire --item PREFIX-N --reason edit\n"
            "printf '%s' \"$NEW_CONTENT\" | yoke items structured-field "
            "replace PREFIX-N --field spec --stdin\n"
            "yoke claims work release --item PREFIX-N "
            "--reason edit-complete"
        ),
        "notes": (
            "For section / addendum updates use "
            "`yoke items structured-field section-upsert`. The "
            "release form `--item PREFIX-N` looks up the calling session's "
            "active claim on that item; pass `--claim-id N` directly "
            "for explicit form."
        ),
    },
    {
        "topic": "claims",
        "purpose": "Operator override: release a stranded foreign-session work claim",
        "recipe": (
            "Use the operator break-glass claim-release surface named in the Atlas."
        ),
        "notes": (
            "Human-only override for when ANOTHER session holds the claim. "
            "Use this — NOT `yoke claims work release --session-id "
            "<foreign>`, which is self-only and the claim-boundary lint "
            "blocks as spoofing. `--reason` IS the operator rationale "
            "(recorded verbatim on the `OperatorClaimOverride` audit "
            "event); no `--override-rationale` flag on this surface. "
            "Refuses to run with YOKE_HOOK_EVENT set. Pick by "
            "who-am-I: holder -> `yoke claims work release --item "
            "PREFIX-N --reason TEXT` (self-release); not holder -> the "
            "Atlas-listed break-glass release."
        ),
    },
    {
        "topic": "claims",
        "purpose": "Release a work claim + manual spec-rewrite pattern",
        "recipe": (
            "# Canonical agent shape — release the calling session's "
            "active claim:\n"
            "yoke claims work release --item PREFIX-N --reason TEXT\n"
            "yoke claims work release --claim-id <id> --reason TEXT\n"
            "yoke claims work release --epic-id E --task-num K "
            "--reason TEXT\n"
            "yoke claims work release --all-mine\n"
            "# Manual spec-rewrite pattern (acquire → edit → release):\n"
            "yoke claims work acquire --item PREFIX-N "
            "--reason rewrite-in-progress\n"
            "yoke items structured-field replace PREFIX-N --field spec "
            "--stdin < PATH\n"
            "yoke claims work release --item PREFIX-N "
            "--reason rewrite-complete"
        ),
        "notes": (
            "The acquire → structured-field replace → release sequence "
            "composes existing primitives — no new skill required. "
            "Use the epic-task form for one task claim and `--all-mine` for "
            "session-scoped handoff cleanup. Process keys come from "
            "`yoke_core.domain.work_processes` (STRATEGIZE | FEED | "
            "DOCTOR)."
        ),
    },
    {
        "topic": "claims",
        "purpose": (
            "Release a work claim when this session is ending and a "
            "fresh session will continue"
        ),
        "recipe": (
            "yoke claims work release --item PREFIX-N "
            "--reason session-handoff-fresh-session"
        ),
        "notes": (
            "Use when the item's lifecycle status is NOT terminal but "
            "this conversation is ending in a way Yoke cannot detect "
            "as definitive (operator opening a fresh session, ending a "
            "working block, context-budget pause). The hook cleanup "
            "path (end_session_if_empty) only ends claim-free "
            "chain-free sessions — it never releases claims for you — "
            "so explicit release is the canonical handoff shape. For "
            "terminal handoffs (handoff-to-polish, handoff-to-usher, "
            "finalize-exit), the lifecycle transition itself releases "
            "— do not use this recipe there. Pair with a Progress Log "
            "entry so the fresh session inherits resume context."
        ),
    },
    {
        "topic": "claims",
        "purpose": (
            "Controlled handoff to a fresh session (Progress Log "
            "append → release claim)"
        ),
        "recipe": (
            "# 1. Append resume context to the Progress Log section:\n"
            "yoke items progress-log append PREFIX-N "
            "--headline 'handoff-to-fresh-session' "
            '--content "<resume-context-body>"\n'
            "# For multiline context, replace --content with "
            "--content-file PATH.\n"
            "# 2. Release the work claim explicitly:\n"
            "yoke claims work release --item PREFIX-N "
            "--reason session-handoff-fresh-session"
        ),
        "notes": (
            "Two-step shape: capture resume context with the "
            "append-only Progress Log surface (handler stamps timestamp "
            "+ merges with existing entries; accepts `--content` or "
            "`--content-file`); release the claim "
            "explicitly so the fresh session can acquire (use "
            "`yoke claims work release --item PREFIX-N --reason "
            "session-handoff-fresh-session` for one item or "
            "`yoke claims work release --all-mine` for every liveness-bound "
            "claim this session still holds; sticky resource claims survive). "
            "The harness owns session "
            "lifetime — Stop / SessionEnd hooks run the hook-runner "
            "cleanup helper; subagents never terminate sessions "
            "themselves (the pre-tool lint `lint_no_agent_session_end` "
            "refuses agent-dispatched shutdown-helper invocations). "
            "Never read the Progress "
            "Log section via shell and pipe it back through `sections "
            "upsert` — that destructive read-merge-write is caught by "
            "the structured-transform lint; `yoke items progress-log "
            "append` is the canonical agent shape. Skip the release "
            "step only when the same conversation will resume under "
            "the same session_id (transient signals — laptop sleep, "
            "app reload — where SessionEnd reactivation auto-reacquires)."
        ),
    },
    {
        "topic": "claims",
        "purpose": "List path claims for an item",
        "recipe": ("yoke claims path list --item PREFIX-N"),
        "notes": (
            "Registered read surface. Returns id, state, declared paths, target_ids."
        ),
    },
    {
        "topic": "claims",
        "purpose": "Register a path claim (canonical agent shape)",
        "recipe": (
            "yoke claims path register \\\n"
            "  --item PREFIX-N \\\n"
            "  --paths <project-source-path>/path_claim_targets.py,"
            "<project-test-path>/test_path_claim_targets.py,docs/event-catalog.md \\\n"
            "  --integration-target main --mode exclusive --allow-planned"
        ),
        "notes": (
            "--allow-planned for files not yet committed. --mode "
            "exception for no-repo-touch work items."
        ),
    },
    {
        "topic": "claims",
        "purpose": "Widen a path claim (canonical agent shape)",
        "recipe": (
            "yoke claims path widen --claim-id 138 "
            "--item PREFIX-N \\\n"
            "  --add-paths <project-source-path>/service_client_backlog_router.py,"
            "<project-test-path>/test_backlog_github_backfill_oversized.py \\\n"
            "  --reason 'backfill subcommand wiring touches "
            "router + new test file'"
        ),
        "notes": (
            "<claim-id> is the path_claims.id from path-claim-register "
            "response or `yoke claims path list`."
        ),
    },
    {
        "topic": "claims",
        "purpose": "Narrow a path claim (drop or keep paths)",
        "recipe": (
            "Path-claim narrow is an operator-debug/refine disposition; "
            "use `yoke claims path widen` for additive scope changes."
        ),
        "notes": (
            "No public narrow wrapper is taught here. Route scope shrinkage "
            "through refine/claim reconciliation until a registered adapter "
            "exists."
        ),
    },
    {
        "topic": "claims",
        "purpose": "List / get path claims",
        "recipe": ("yoke claims path list --item PREFIX-N\nyoke claims path get 138"),
        "notes": (
            "Registered read surfaces. Returns id, state, declared paths, "
            "target_ids. Pipe JSON output to jq for filtering."
        ),
    },
    {
        "topic": "claims",
        "purpose": "Summary of path-claim conflicts on a branch",
        "recipe": (
            "yoke path-claims conflicts list --integration-target main --project P"
        ),
        "notes": (
            "Registered read-only summary across all non-terminal claims. "
            "An explicit `--project` satisfies resolution from any mapped "
            "checkout; do not fall back to `yoke db read` against "
            "path_claims when the named project was already supplied. "
            "Write-side checkout binding is unchanged."
        ),
    },
    {
        "topic": "claims",
        "purpose": "Find conflicts on specific paths (SQL)",
        "recipe": (
            'yoke db read "\n'
            "SELECT pc.id, pc.owner_kind, pc.owner_item_id, pc.state, "
            "tgt.path_string\n"
            "FROM path_claims pc\n"
            "JOIN path_claim_targets pct ON pct.claim_id = pc.id\n"
            "JOIN path_targets tgt ON tgt.id = pct.target_id\n"
            "WHERE tgt.path_string IN ('<project-source-path>/foo.py', "
            "'<project-source-path>/bar.py')\n"
            "  AND pc.state NOT IN ('cancelled','released')\""
        ),
        "notes": (
            "Raw diagnostic read. Use when path-claim-conflicts is too "
            "coarse; `db_router query` is only the source-dev/"
            "operator-debug break-glass fallback."
        ),
    },
    {
        "topic": "claims",
        "purpose": "Classify a path-claim overlap before authoring a coordination edge",
        "recipe": (
            "yoke claims path coordination-decision-build "
            "--item PREFIX-N --conflicting-claim CLAIM_ID "
            "--paths a.py,b.py"
        ),
        "notes": (
            "Registered read-only surface; works over HTTPS. Returns "
            "a JSON evidence packet with both items' specs, the "
            "conflicting claim's state + path metadata, and three "
            "ready-to-paste commands (one per decision option: "
            "`coordination_only`, directional `activation`, operator "
            "`escalate`). The helper does NOT decide; the caller "
            "classifies and runs the matching command. Most independent "
            "same-file edits resolve as `coordination_only` via "
            "`yoke shepherd dependency-add ... --gate-point "
            "coordination_only --rationale TEXT`."
        ),
    },
]
