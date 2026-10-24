"""Public usage recipes for strategy review and execution commands."""

USAGE_BY_FUNCTION_ID = {
    "strategy.surface.list": (
        "yoke strategy surface list --project P [--session-id S] [--json]"
    ),
    "strategy.surface.get": (
        "yoke strategy surface get SLUG --project P [--session-id S] [--json]"
    ),
    "strategy.revision.diff": (
        "yoke strategy revision diff SLUG "
        "--from-revision N --to-revision N "
        "--project P [--session-id S] [--json]"
    ),
    "strategy.revision.restore": (
        "yoke strategy revision restore SLUG "
        "--revision N --base-updated-at TS "
        "[--summary TEXT] [--state TEXT] "
        "--project P [--session-id S] [--json]"
    ),
    "strategy.parent.set": (
        "yoke strategy parent set SLUG (--parent-slug "
        "PARENT | --clear) --project P [--session-id "
        "S] [--json]"
    ),
    "strategy.coordination.append": (
        "yoke strategy coordination append SLUG "
        "--section NAME --entry TEXT --project P "
        "[--session-id S] [--json]"
    ),
    "strategy.execution.get": (
        "yoke strategy execution get ITEM --project P [--session-id S] [--json]"
    ),
    "strategy.execution.link": (
        "yoke strategy execution link ITEM --slug SLUG "
        "[--document-project P] --project P [--session-id S] [--json]"
    ),
    "strategy.claim.acquire": (
        "yoke strategy claim acquire ITEM --project P [--session-id S] [--json]"
    ),
    "strategy.claim.release": (
        "yoke strategy claim release (ITEM | PROCESS_KEY) [--reason "
        "TEXT] --project P [--session-id S] [--json]"
    ),
    "strategy.claim.break_glass_release": (
        "yoke strategy claim break-glass-release "
        "ITEM --reason TEXT --project P "
        "[--session-id S] [--json]"
    ),
    "strategy.doc_claim.acquire": (
        "yoke strategy doc-claim acquire SLUG [--reason TEXT] --project "
        "P [--session-id S] [--json]"
    ),
    "strategy.doc_claim.release": (
        "yoke strategy doc-claim release SLUG [--reason TEXT] --project "
        "P [--session-id S] [--json]"
    ),
    "strategy.doc_claim.list": (
        "yoke strategy doc-claim list [--all] --project P [--session-id S] [--json]"
    ),
}
