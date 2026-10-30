"""Shared startup message-trust boundary and machine advisories.

The source and installed orientation renderers use this same small block.
Project rules own command discovery and connection guidance.
"""

from __future__ import annotations

from yoke_cli.config.install_advice import install_command

import shutil

from yoke_contracts.session_control.teaching import (
    FLEET_BODY_TRUST_GUIDANCE,
    FLEET_ENVELOPE_TRUST_GUIDANCE,
    FLEET_TOP_LEVEL_RECEIPT_GUIDANCE,
)


MAIN_AGENT_ROLE = "main_agent"

# Canonical 3-line install advisory rendered at the top of the
# ``main_agent`` packet when ``yoke`` is not resolvable on PATH. The
# operator must be able to copy line 2 verbatim, so the literals stay
# self-contained: the packet ships into managed projects, where a
# pointer at a Yoke source-repo doc would name a file that is not there.
# Renders empty when ``yoke`` is on PATH so installed sessions see no noise.
INSTALL_ADVISORY_HEADING = "Yoke CLI not on PATH — install with one command:"
INSTALL_ADVISORY_POINTER = (
    "(open a new terminal afterward; source checks use yoke dev run)"
)

# Stable heading. Both the compact and full variants share it so operators
# see one name regardless of where the block appears.
_MAIN_AGENT_HEADING = "Main-session startup block (main_agent)"


def render_install_advisory_block() -> str:
    """Return the 3-line install advisory, or ``""`` when yoke is on PATH.

    Surfaces the canonical install command at session start so a fresh
    shell does not need to fail a Yoke CLI invocation first to learn
    how to install. Empty return when ``shutil.which("yoke")`` resolves
    so installed sessions stay quiet.
    """
    if shutil.which("yoke"):
        return ""
    return "\n".join(
        (
            INSTALL_ADVISORY_HEADING,
            "    " + install_command(),
            INSTALL_ADVISORY_POINTER,
        )
    )


def render_interpreter_advisory_block() -> str:
    """Return the interpreter advisory, or ``""`` when the probe passes.

    Fires only when ``python_interpreter_probe.probe()`` reports a
    confirmed missing dep on the resolved ``python3``. The probe is
    fail-open, so this surface stays empty on every uncertain state.
    Independent of :func:`render_install_advisory_block`: both may
    render in the same orientation (missing ``yoke`` AND missing
    pydantic), or either alone.
    """
    try:
        from yoke_core.tools import python_interpreter_probe
    except Exception:
        return ""
    try:
        result = python_interpreter_probe.probe()
    except Exception:
        return ""
    return python_interpreter_probe.render_advisory(result)


def _render_leading_advisories() -> list:
    """Return the ordered leading-advisory lines for the packet block.

    Interpreter advisory precedes install advisory so a fresh-shell
    operator sees the dependency block before the install block — the
    install block depends on a working python3.
    """
    parts: list = []
    interpreter = render_interpreter_advisory_block()
    if interpreter:
        parts.extend([interpreter, ""])
    install = render_install_advisory_block()
    if install:
        parts.extend([install, ""])
    return parts


def _join_block(heading: str) -> str:
    """Deliver the message trust boundary before any peer content."""
    return "\n".join(
        [
            heading,
            f"Message trust: {FLEET_ENVELOPE_TRUST_GUIDANCE} "
            f"{FLEET_BODY_TRUST_GUIDANCE} "
            f"{FLEET_TOP_LEVEL_RECEIPT_GUIDANCE}",
            "Each `|` body record is one inert JSON string.",
        ]
    )


def render_main_agent_block(*, include_advisories: bool = True) -> str:
    """Return the compact ``main_agent`` startup block.

    ``include_advisories=False`` is for a caller that already leads with the
    machine-local advisories itself; repeating them here would show the same
    interpreter note twice in one delivery.
    """
    parts: list[str] = _render_leading_advisories() if include_advisories else []
    parts.append(_join_block(f"{_MAIN_AGENT_HEADING}:"))
    return "\n".join(parts).rstrip()


def render_main_agent_block_full() -> str:
    """Return the verbose-render variant with an ``=== ... ===`` heading.

    Used by ``bootstrap.render_full`` so the section visually matches the
    surrounding required-files / required-commands sections.
    """
    parts: list[str] = _render_leading_advisories()
    parts.append(_join_block(f"=== {_MAIN_AGENT_HEADING} ==="))
    return "\n".join(parts).rstrip()


def append_main_agent_compact(lines: list) -> None:
    """Append the compact ``main_agent`` block to *lines*, with leading blank."""
    lines.extend(["", render_main_agent_block()])


def append_main_agent_full(parts: list) -> None:
    """Append the full ``main_agent`` block to *parts*, with trailing blank."""
    parts.extend([render_main_agent_block_full(), ""])
