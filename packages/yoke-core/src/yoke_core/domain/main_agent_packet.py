"""``main_agent`` packet renderers — compact main-session DB/API teaching.

Owns the rendering of the layer-explicit ``main_agent`` packet that sits
between ``schema_api_context`` (LLM-facing schema/API truth) and
``harness_contract`` (substrate manifest truth).

Lives in the shipped core package because three surfaces need it and the
packet must be identical in all three: the source-repo startup renderer,
the install bundle (which composes the packet into the managed doctrine
block every managed project auto-loads), and the client-side session
orientation a managed project's hooks render. Keeps the packet generated,
not hand-copied prose: one source of truth for what the main session sees
about live tables, claim shape, and wrapper commands.

Public surface:

- :data:`MAIN_AGENT_ROLE` — canonical role identifier.
- :func:`render_main_agent_block` — return the compact markdown block to
  embed in startup orientation. Returns ``""`` when the packet generator
  is unavailable so the bootstrap path remains fail-open.
- :func:`render_main_agent_block_full` — full-orientation variant with a
  short ``=== ... ===`` heading suitable for the verbose render path.
- :func:`render_install_advisory_block` — 3-line install advisory
  prepended to both ``main_agent`` variants when ``shutil.which("yoke")``
  returns no path, so a fresh shell sees the canonical install command
  at session start rather than after the first failed Yoke CLI call.
- :func:`render_interpreter_advisory_block` — interpreter-dependency
  advisory rendered when the resolved ``python3`` is missing pydantic
  (typical Mac default: ``/usr/bin/python3`` is Apple Python 3.9
  without pydantic). Independent of the install advisory; both may
  render in the same orientation.
"""

from __future__ import annotations

import shutil


MAIN_AGENT_ROLE = "main_agent"

# Canonical 3-line install advisory rendered at the top of the
# ``main_agent`` packet when ``yoke`` is not resolvable on PATH. The
# operator must be able to copy line 2 verbatim, so the literals stay
# self-contained: the packet ships into managed projects, where a
# pointer at a Yoke source-repo doc would name a file that is not there.
# Renders empty when ``yoke`` is on PATH so installed sessions see no noise.
INSTALL_ADVISORY_HEADING = (
    "Yoke CLI not on PATH — install with one command:"
)
INSTALL_ADVISORY_COMMAND = (
    "    python3 -m yoke_core.tools.install_yoke_launcher"
)
INSTALL_ADVISORY_POINTER = (
    "(add --help to that command for the install variants)"
)

# Stable orientation-block heading. Both the compact and full variants
# share the same heading so operators see one name regardless of where
# the packet appears.
_MAIN_AGENT_HEADING = "Main-session DB/API packet (main_agent)"

# Canonical prefix for the structured banner returned when
# ``schema_api_context.render_role_packet`` raises (typically
# ``DriftError`` when the packet seed and the live schema disagree).
# The banner replaces a silent ``return ""`` so operators see a loud
# signal at session start and the regression test grounds on this
# constant rather than a duplicated literal.
RENDER_FAILURE_PREFIX = "[!!!] MAIN_AGENT PACKET RENDER FAILED"

# Short prefix shown above the rendered packet body. Reminds the main
# session that the packet is generated truth — the rule is the same one
# subagents see, just surfaced earlier so ad-hoc investigation does not
# need to discover it.
_MAIN_AGENT_PREFIX = (
    "Layer-explicit packet for the top-level Yoke session. Treat as "
    "live schema/API truth — never hand-copy this content into prompts. "
    "Regenerate after schema changes via "
    "`python3 -m yoke_core.domain.agents_render render`; check drift "
    "via `python3 -m yoke_core.domain.schema_api_context check`. "
    "Subagent packets (`architect_agent`, `engineer_agent`, "
    "`tester_agent`, `simulator_agent`, `boss_agent`) carry the same "
    "spine plus role-scoped topics. Substrate capability truth lives in "
    "the harness manifest under the `harness_contract` packet name and "
    "is documented separately."
)


def _render_failure_banner(exc: BaseException) -> str:
    """Return the structured render-failure banner for a packet exception.

    The banner becomes the packet body, so every consumer (compact,
    full, the two append helpers) surfaces it automatically — no new
    hook surface required. The first line carries
    :data:`RENDER_FAILURE_PREFIX` so the bootstrap orientation is
    visibly broken instead of silently empty.
    """
    error_class = type(exc).__name__
    message = str(exc) or "(no message)"
    return (
        f"{RENDER_FAILURE_PREFIX} — schema_api_context drift detected.\n"
        f"\n"
        f"    {error_class}: {message}\n"
        f"\n"
        f"Subagents still receive their packets via agents_render "
        f"(rendered at build time).\n"
        f"The main session is operating WITHOUT live schema/API "
        f"teaching for this session.\n"
        f"\n"
        f"Recovery: regenerate the packet seed to match the live "
        f"schema, or run\n"
        f"  python3 -m yoke_core.domain.schema_api_context check\n"
        f"to identify the drift. After the seed update lands, restart "
        f"this session\n"
        f"to pick up the freshly rendered packet."
    )


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
            INSTALL_ADVISORY_COMMAND,
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


def _render_packet_body() -> str:
    """Return the freshly generated ``main_agent`` packet body.

    Returns ``""`` only when the ``schema_api_context`` import itself
    fails (fresh checkout, broken bootstrap state) — the bootstrap path stays
    fail-open in that case so a missing module does not break startup
    orientation. When the module imports but
    :func:`schema_api_context.render_role_packet` raises (typically a
    ``DriftError`` between the seed and the live schema), returns a
    structured render-failure banner so the bootstrap consumers surface
    the drift loudly instead of silently dropping the packet block.
    """
    try:
        from yoke_core.domain.schema_api_context import render_role_packet
    except Exception:
        return ""
    try:
        return render_role_packet(MAIN_AGENT_ROLE).rstrip()
    except Exception as exc:
        return _render_failure_banner(exc)


def render_main_agent_block() -> str:
    """Return the compact orientation block for the ``main_agent`` packet.

    Layout matches the sibling sections in ``bootstrap.render_compact``:
    a labeled heading, the prefix sentence, an empty line, then the
    packet body. Returns ``""`` when the packet generator is unavailable
    so the caller can simply skip the section.
    """
    body = _render_packet_body()
    if not body:
        return ""
    parts: list[str] = _render_leading_advisories()
    parts.extend(
        [
            f"{_MAIN_AGENT_HEADING}:",
            _MAIN_AGENT_PREFIX,
            "",
            body,
        ]
    )
    return "\n".join(parts).rstrip()


def render_main_agent_block_full() -> str:
    """Return the verbose-orientation variant with an ``=== ... ===`` heading.

    Used by ``bootstrap.render_full`` so the section visually matches
    the surrounding required-files / required-commands sections in the
    full render. Returns ``""`` when the packet generator is unavailable.
    """
    body = _render_packet_body()
    if not body:
        return ""
    parts: list[str] = _render_leading_advisories()
    parts.extend(
        [
            f"=== {_MAIN_AGENT_HEADING} ===",
            _MAIN_AGENT_PREFIX,
            "",
            body,
        ]
    )
    return "\n".join(parts).rstrip()


def append_main_agent_compact(lines: list) -> None:
    """Append the compact ``main_agent`` block to *lines*, with leading blank."""
    block = render_main_agent_block()
    if block:
        lines.extend(["", block])


def append_main_agent_full(parts: list) -> None:
    """Append the full ``main_agent`` block to *parts*, with trailing blank."""
    block = render_main_agent_block_full()
    if block:
        parts.extend([block, ""])
