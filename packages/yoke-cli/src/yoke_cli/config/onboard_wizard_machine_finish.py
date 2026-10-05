"""Account projects and usable next steps after machine-only setup."""

from __future__ import annotations

from shlex import quote
from urllib.parse import urlsplit

from textual.widgets import Static

from yoke_cli.config import onboard_destinations, onboard_project, yoke_token_verify
from yoke_cli.config.onboard_wizard_flow_hosted_machine import platform_url_for_env


def machine_finish_lines(result) -> list[str]:
    """Use the already-verified account scope, without another network call."""
    verification = result.yoke_token_verification
    if result.project_mode != onboard_project.PROJECT_MODE_MACHINE_ONLY:
        return []
    if not isinstance(verification, dict):
        return []
    details = yoke_token_verify.detail_lines(verification)
    actor = next(
        (line.removeprefix("Actor: ") for line in details if line.startswith("Actor:")),
        "verified actor",
    )
    orgs = [
        str(org.get("name") or org.get("slug") or "").strip()
        for org in verification.get("orgs") or []
        if isinstance(org, dict)
    ]
    connected = " · ".join([f"Connected as {actor}", *(org for org in orgs if org)])
    projects = [
        project
        for project in verification.get("projects") or []
        if isinstance(project, dict) and project.get("slug")
    ]
    lines = [connected, ""]
    if projects:
        labels = []
        for project in projects:
            slug = str(project["slug"])
            prefix = str(project.get("public_item_prefix") or "").strip()
            # Older serving builds omit the prefix; never invent it from a slug.
            labels.append(f"{slug} ({prefix})" if prefix else slug)
        project_arg = quote(str(projects[0]["slug"]))
        lines.extend(
            [
                f"Your projects: {' · '.join(labels)}",
                "",
                "You can file and browse work from any folder:",
                "  Before filing, read the project's execution instructions:",
                "  yoke workflow execution-instruction resolve --workflow dash \\",
                f"    --project {project_arg} --full",
                '  yoke dash "Title" "what to do" \\',
                f"    --project {project_arg} --execution-instructions-considered",
                f"  yoke items list --project {project_arg}",
            ]
        )
    else:
        lines.append("Your account has no projects yet.")
    hosted_env = onboard_destinations.hosted_environment_for_url(result.api_url)
    server = urlsplit(str(result.api_url or ""))
    if hosted_env:
        lines.append(f"Or open the dashboard: {platform_url_for_env(hosted_env)}")
    elif server.netloc:
        # A team server serves its own workbench at its site root.
        lines.append(f"Or open the workbench: {server.scheme}://{server.netloc}/")
    else:
        lines.append("Or open the workbench: yoke ui up")
    lines.extend(
        [
            "",
            "To work on a project's code from this machine later, run: yoke setup",
        ]
    )
    return lines


def machine_finish_widgets(result) -> list[Static]:
    return [
        Static(line, markup=False, classes="onboard-plan-line")
        for line in machine_finish_lines(result)
    ]
