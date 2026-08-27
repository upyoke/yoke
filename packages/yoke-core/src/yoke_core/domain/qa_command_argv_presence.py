"""Whether a proposed verification command names something that can run.

Registering a command is a claim that running it verifies the project. An argv
naming a script the repository does not have cannot verify anything; it fails
at the gate, long after the person who typed it has moved on. The worked
example is a `vendor/bin/phpunit` or `./scripts/test.sh` named from memory for
a repository that never had it.

Only one shape is refusable. A path-shaped argv head names a file the
repository is supposed to provide, so its absence there is a fact about the
registration and is refused. A bare program name is a fact about whichever
machine runs the suite, which is often not the machine registering it — an
operator on a laptop binding `mvn verify` for a repository whose CI has Maven
is doing exactly the right thing, and refusing that would make the honest case
impossible. So a bare name that resolves on PATH is reported as verified, and
one that does not is reported as unverified-here rather than wrong.

Nothing here asks whether the command is a *good* gate. That judgement belongs
to the operator, and when the honest answer is "there is no suite", the
attestation surface exists to say so rather than inventing an argv.

An unverified outcome is always named. A silent pass is how the invented
command gets registered in the first place.
"""

from __future__ import annotations

import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path


#: Outcomes that are evidence the registration itself is wrong, rather than
#: evidence that this machine could not check it. Only these refuse.
REFUSING_REASON_CODES = frozenset({
    "empty_command", "unparsable_command", "argv_absent_from_repo",
})


@dataclass(frozen=True)
class ArgvPresence:
    """The verdict, plus everything a refusal message needs to be actionable."""

    verified: bool
    reason_code: str
    token: str
    message: str


def _unverifiable(token: str) -> ArgvPresence:
    return ArgvPresence(
        verified=False,
        reason_code="checkout_unmapped",
        token=token,
        message=(
            "this machine has no checkout mapped for the project, so the "
            "command was not verified against the repository it claims to "
            "run. Map the checkout with `yoke project register <checkout> "
            "--project-id <id>` and register from the machine that holds it "
            "to get that verification."
        ),
    )


def check_argv_presence(command: str, *, checkout: Path | None) -> ArgvPresence:
    """Decide whether *command*'s leading token names something runnable.

    ``checkout=None`` means no checkout is mapped here, which is reported as
    its own unverifiable outcome rather than assumed in either direction.
    """
    text = str(command or "").strip()
    if not text:
        return ArgvPresence(
            verified=False,
            reason_code="empty_command",
            token="",
            message="a registered verification command cannot be empty.",
        )
    try:
        argv = shlex.split(text)
    except ValueError as exc:
        return ArgvPresence(
            verified=False,
            reason_code="unparsable_command",
            token=text,
            message=(
                f"the command {text!r} is not a parsable shell invocation "
                f"({exc}). Fix the quoting and register it again."
            ),
        )
    token = argv[0] if argv else ""
    if "/" in token:
        if checkout is None:
            return _unverifiable(token)
        if (checkout / token).exists():
            return ArgvPresence(
                verified=True,
                reason_code="resolved_in_checkout",
                token=token,
                message=f"{token!r} exists in {checkout}.",
            )
        return ArgvPresence(
            verified=False,
            reason_code="argv_absent_from_repo",
            token=token,
            message=(
                f"{token!r} does not exist in {checkout}, so the command "
                f"{text!r} cannot run and would register a gate that fails "
                f"wherever it is executed. Register the argv this repository "
                f"actually runs, or — when it has no suite at all — attest "
                f"that with `yoke qa no-tests attest --project <project> "
                f"--reason <why>`."
            ),
        )
    if shutil.which(token):
        return ArgvPresence(
            verified=True,
            reason_code="resolved_on_path",
            token=token,
            message=f"{token!r} resolves on PATH.",
        )
    return ArgvPresence(
        verified=False,
        reason_code="program_not_on_this_machine",
        token=token,
        message=(
            f"{token!r} is not on this machine's PATH, so the command "
            f"{text!r} was not verified here. That is expected when the suite "
            f"runs somewhere this machine is not — CI, a container, a build "
            f"box — and is not a refusal. If the repository has no suite at "
            f"all, say so with `yoke qa no-tests attest --project <project> "
            f"--reason <why>` instead of binding a command."
        ),
    )


def require_argv_present(
    command: str,
    *,
    checkout: Path | None,
    project: str,
    scope: str,
) -> ArgvPresence:
    """Refuse an argv that provably cannot run; report what could not be seen.

    Only the outcomes that are evidence of a wrong registration refuse. An
    unmapped checkout and a program this machine lacks are both the machine
    saying it cannot confirm — the ordinary cases for a control plane serving a
    repository it does not hold, and for an operator binding the command of a
    suite that runs elsewhere. Those ride back in the result so the caller can
    report them, rather than being swallowed as a pass or promoted into a
    refusal that would make the honest case impossible.
    """
    presence = check_argv_presence(command, checkout=checkout)
    if presence.reason_code in REFUSING_REASON_CODES:
        raise ValueError(
            f"cannot register {scope!r} verification for project {project!r}: "
            f"{presence.message}"
        )
    return presence


__all__ = [
    "REFUSING_REASON_CODES",
    "ArgvPresence",
    "check_argv_presence",
    "require_argv_present",
]
