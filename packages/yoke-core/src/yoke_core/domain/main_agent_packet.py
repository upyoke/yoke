"""``main_agent`` startup block — the short core and the reads that follow it.

Owns the block a top-level Yoke session receives at startup: the
machine-local advisories, and the precise reads that reach the rest. It sits
between ``schema_api_context`` (LLM-facing schema/API truth) and
``harness_contract`` (substrate manifest truth).

**The packet body is not inlined here.** It used to be, and it did not
arrive: the composed startup block reached 106.8 KB against a harness inline
ceiling of 8 KiB, so the harness persisted it to a file and showed the model
a preview from the top. Every rule past the preview was delivered in name
only. The block therefore carries the facts a session cannot look up — its
own identity and this machine's advisories — plus one line per question
naming the command that answers it. ``yoke packets render --role main_agent``
returns the packet in full, and the session runs it when a schema question
actually arrives.

Lives in the shipped core package because both startup surfaces need it and
the block must be identical in each: the source-repo startup renderer and
the client-side session orientation a managed project's hooks render.

Public surface:

- :data:`MAIN_AGENT_ROLE` — canonical role identifier.
- :func:`render_main_agent_block` — the compact startup block.
- :func:`render_main_agent_block_full` — the same block under an
  ``=== ... ===`` heading, for the verbose render path.
- :func:`render_install_advisory_block` — 3-line install advisory rendered
  when ``shutil.which("yoke")`` returns no path, so a fresh shell sees the
  canonical install command at session start rather than after the first
  failed Yoke CLI call.
- :func:`render_interpreter_advisory_block` — interpreter-dependency
  advisory rendered when the resolved ``python3`` is missing pydantic
  (typical Mac default: ``/usr/bin/python3`` is Apple Python 3.9 without
  pydantic). Independent of the install advisory; both may render in the
  same block.
"""

from __future__ import annotations

import shutil

from yoke_contracts.connection_authority_teaching import (
    CONNECTION_AUTHORITY_STANZA,
)


MAIN_AGENT_ROLE = "main_agent"

# Canonical 3-line install advisory rendered at the top of the
# ``main_agent`` packet when ``yoke`` is not resolvable on PATH. The
# operator must be able to copy line 2 verbatim, so the literals stay
# self-contained: the packet ships into managed projects, where a
# pointer at a Yoke source-repo doc would name a file that is not there.
# Renders empty when ``yoke`` is on PATH so installed sessions see no noise.
INSTALL_ADVISORY_HEADING = "Yoke CLI not on PATH — install with one command:"
INSTALL_ADVISORY_COMMAND = "    python3 -m yoke_core.tools.install_yoke_launcher"
INSTALL_ADVISORY_POINTER = (
    "(add --help for variants; --repair rewrites ~/.local/bin/yoke)"
)

# Stable heading. Both the compact and full variants share it so operators
# see one name regardless of where the block appears.
_MAIN_AGENT_HEADING = "Main-session startup block (main_agent)"

# The short core. Every line names the one command that answers its question,
# because the answers themselves do not fit the channel this block rides —
# and a truncated answer is worse than a pointer to a complete one.
MAIN_AGENT_STARTUP_READS = (
    "This block is short on purpose. Each line below names the one command "
    "that answers its question in full; run it when the question arrives.\n"
    "\n"
    "- Live schema, claim shape, and the registered command set — "
    "`yoke packets render --role main_agent`. Add "
    "`--topic core|claims|auth|qa|packs` to narrow it, and `--detail full` "
    "for the per-table and per-command notes. Read it before naming any "
    "column, table, or function id; the packet is generated truth, so never "
    "hand-copy it into a prompt.\n"
    "- This machine's control-plane connections and what each authorizes — "
    "`yoke env list`.\n"
    "- What a harness can and cannot do — its own "
    "`runtime/harness/<harness_id>/manifest.json`, never a document's claim "
    "about it.\n"
    "- Any operation's variants, flag matrix, and decision tree — that "
    "operation's own `--help`.\n"
    "\n"
    "Regenerate the packet after a schema change with `yoke agents render`; "
    "`yoke packets check` reports drift and packet budget overruns."
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


def _join_block(heading: str) -> str:
    """Frame the block: heading, connection authority, then the reads.

    Connection authority stays inline rather than becoming a fourth read.
    It is the one invariant a session can violate before it has asked any
    question — writing through the wrong transport — and it costs a few
    hundred bytes in a channel measured in kibibytes.
    """
    return "\n".join(
        [heading, CONNECTION_AUTHORITY_STANZA, "", MAIN_AGENT_STARTUP_READS]
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
