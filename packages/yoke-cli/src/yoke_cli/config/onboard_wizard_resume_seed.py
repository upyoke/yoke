"""Seed a resumed setup wizard with the answers its run already confirmed.

``yoke setup --resume RUN-ID`` in the wizard (including the rerun after setup
installed the served release mid-run) reopens at Review with the run's saved
answers instead of walking every question again from fresh defaults. The
answers come from the run report's input snapshot: ``prepare_run`` already
folds it into the parsed command line, and the hosting choice and board art,
which only the wizard asks, are read from the snapshot directly.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.project_contract.board_art import generate_default_variants

from yoke_cli.config import onboard_project

# WizardResult field <- parsed command-line attribute, as restored from the run.
_FIELDS = {
    "env_name": "env_name",
    "api_url": "api_url",
    "destination": "destination",
    "admin_name": "admin_name",
    "token": "token",
    "token_file": "token_file",
    "machine_github_choice": "machine_github_choice",
    "machine_github_api_url": "machine_github_api_url",
    "project_mode": "project_mode",
    "project_remote_url": "project_remote_url",
    "project_checkout": "project_checkout",
    "project_slug": "project_slug",
    "project_name": "project_name",
    "project_org": "project_org",
    "project_github_repo": "project_github_repo",
    "project_github_repository_id": "project_github_repository_id",
    "project_github_installation_id": "project_github_installation_id",
    "project_default_branch": "project_default_branch",
    "project_public_item_prefix": "project_public_item_prefix",
    "existing_project_id": "existing_project_id",
    "existing_project_match_source": "existing_project_match_source",
    "existing_project_local_source": "existing_project_local_source",
    "project_github_adoption": "github_adoption",
    "project_github_adoption_preserve": "project_github_adoption_preserve",
    "project_keep_existing_remote": "project_keep_existing_remote",
    "project_publish_owner": "project_publish_owner",
    "project_publish_owner_login": "project_publish_owner_login",
    "project_publish_repo_name": "project_publish_repo_name",
    "project_publish_private": "project_publish_private",
    "project_publish_create_repository": "project_publish_create_repository",
    "project_publish_repository_id": "project_publish_repository_id",
    "project_publish_installation_id": "project_publish_installation_id",
    "project_clone_outcome": "project_clone_outcome",
    "project_clone_existing_layer_decision": "project_existing_yoke_layer",
    "project_clone_keep_upstream": "project_clone_keep_upstream",
}


def answers(parsed: Any) -> dict[str, Any] | None:
    """The resumed run's confirmed wizard answers, or None when not resuming."""
    payload = getattr(parsed, "resume_payload", None)
    if not getattr(parsed, "resume_run_id", None) or not isinstance(payload, Mapping):
        return None
    seeded = {
        field: getattr(parsed, name)
        for field, name in _FIELDS.items()
        if getattr(parsed, name, None) is not None
    }
    seeded["project_publish_to_github"] = bool(
        seeded.get("project_publish_owner") or seeded.get("project_publish_repo_name")
    )
    if (
        getattr(parsed, "project_default_branch_source", None)
        == onboard_project.DEFAULT_BRANCH_SOURCE_SOURCE_REPO
    ):
        seeded["project_source_default_branch"] = seeded.get("project_default_branch")
    snapshot = payload.get("input_snapshot")
    snapshot = snapshot if isinstance(snapshot, Mapping) else {}
    hosting = _mapping(snapshot.get("hosting"))
    if hosting.get("choice"):
        seeded["hosting_choice"] = hosting["choice"]
        seeded["hosting_provider_note"] = hosting.get("provider_note") or None
    art = _mapping(snapshot.get("board_art"))
    if art.get("word") and art.get("seed"):
        seeded["board_art_word"] = art["word"]
        seeded["board_art_seed"] = art["seed"]
        seeded["board_art_variants"] = generate_default_variants(
            art["word"], seed_text=art["seed"]
        )
    return {
        "run_id": str(parsed.resume_run_id),
        "payload": dict(payload),
        "result": seeded,
    }


def apply(shell: Any, resume_answers: Mapping[str, Any] | None) -> None:
    """Load the answers onto a fresh wizard so it opens at Review."""
    shell._resume_seeded = bool(resume_answers)
    if not resume_answers:
        return
    for field, value in resume_answers["result"].items():
        setattr(shell.result, field, value)
    shell._resume_run_id = resume_answers["run_id"]
    shell._resume_payload = resume_answers["payload"]
    shell._project_mode_preset = True
    shell._destination_preset = True


def apply_kwargs(result: Any) -> dict[str, Any]:
    """Apply's inputs, with the board art the run snapshot keeps for a resume."""
    kwargs = result.build_report_kwargs(apply=True, check_identity=True)
    kwargs["board_art"] = {"word": result.board_art_word, "seed": result.board_art_seed}
    return kwargs


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


__all__ = ["answers", "apply", "apply_kwargs"]
