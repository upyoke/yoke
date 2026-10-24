"""Wait on Yoke's exact main factory before dispatching its hosted release."""

from __future__ import annotations

from yoke_core.domain import json_helper

MAIN_FACTORY_WORKFLOW = "yoke-build-artifacts.yml"


def check_main_factory(repo, project, head_sha, timeout_sec, *, github_actions, sd=None):
    """Reuse the CI relay and its client-side wait; refuse without factory proof."""
    response = github_actions(
        "check-ci", repo, MAIN_FACTORY_WORKFLOW,
        "--branch", "main", "--head-sha", head_sha, "--main-factory",
        "--wait", "--timeout", str(timeout_sec), "--json",
        project=project, sd=sd, timeout=timeout_sec + 30,
    )
    output = "\n".join(part.strip() for part in (response.stdout, response.stderr) if part.strip())
    envelope = None
    for line in reversed(output.splitlines()):
        try:
            parsed = json_helper.loads_text(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and "success" in parsed:
            envelope = parsed
            break
    if not envelope or envelope.get("success") is not True:
        return False, (
            f"main_factory_unavailable: cannot verify {MAIN_FACTORY_WORKFLOW} for {head_sha}. "
            f"GitHub Actions relay detail: {output or 'typed response missing'}. "
            "Restore relay access and retry the gate; no release was dispatched."
        )
    result = envelope.get("result") or {}
    if result.get("main_factory_checked") is not True:
        return False, (
            "main_factory_gate_version_skew: the serving API lacks the main-factory "
            "gate response required by this driver. Use the reviewed source-dev "
            "local GitHub authority for this self-deploy bootstrap, then retry; "
            "do not dispatch a release without factory proof."
        )
    if result.get("state") == "passed":
        return True, f"  CI gate: CI and main factory passed for {head_sha}"
    newest = result.get("newest_successful_main_sha")
    recovery = (
        f"Newest main commit with a successful factory: {newest}."
        if newest else "No newest successful main commit was available from GitHub."
    )
    return False, (
        f"main_factory_not_successful: {MAIN_FACTORY_WORKFLOW} for {head_sha} "
        f"has state {result.get('state')}, conclusion {result.get('conclusion') or 'none'} "
        f"(run {result.get('run_id') or 'missing'}). {recovery} "
        f"{result.get('message') or ''} "
        "Inspect the factory and correct its cause, or compose a new release on "
        "the named successful commit; retry this gate before dispatch."
    )
