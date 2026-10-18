"""Place optional setup context without crowding required orientation."""

from collections.abc import Sequence

PROJECT_POINTER = "Setup: run yoke onboard checklist get"
GLOBAL_POINTER = (
    "Setup: run yoke setup --agent; more: https://upyoke.com/docs/start/agent-setup"
)


def render_with_setup(
    lines: list[str],
    metadata: Sequence[list[str]],
    tail: list[str],
    setup_lines: Sequence[str],
    budget: int,
    *,
    global_context: bool = False,
) -> str:
    choices = [list(setup_lines)]
    if setup_lines:
        pointer = GLOBAL_POINTER if global_context else PROJECT_POINTER
        if len(setup_lines) == 1 and ";" in setup_lines[0]:
            reason = setup_lines[0].partition(";")[0]
            command = (
                "yoke setup --agent" if global_context else "yoke onboard checklist get"
            )
            pointer = f"{reason}; run {command} to diagnose and retry."
        choices.append([pointer])
    for setup in choices:
        rendered = "\n".join(lines + metadata[0] + setup + tail).rstrip() + "\n"
        if len(rendered.encode()) <= budget:
            return rendered
    # Setup collapses before Git or other optional metadata gives way.
    for optional in metadata[1:]:
        rendered = "\n".join(lines + optional + choices[-1] + tail).rstrip() + "\n"
        if len(rendered.encode()) <= budget:
            return rendered
    return rendered
