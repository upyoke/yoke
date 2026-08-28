"""What credential a remote git command actually ran under, recorded not guessed.

A failed remote command is unattributable without this: the same git error
appears whether Yoke supplied a credential the remote rejected or supplied
none at all, and those need opposite responses.

The record is written by the code that builds the environment, at the moment
it decides. An attribution re-derived after the fact answers "what would this
command have done" rather than "what did it do" — it would report a credential
applied whenever the target merely looked like the configured origin, including
on a run that went out with no credential at all.
"""

from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Sequence

from yoke_contracts.github_auth_transience import GITHUB_AUTH_RETRY_RECIPE


@dataclass(frozen=True)
class CredentialDecision:
    """What one git command was given, decided before the command ran."""

    network: bool
    url: str = ""
    web_url: str | None = None
    token_applied: bool = False


LOCAL_COMMAND = CredentialDecision(network=False)


def attribution(decision: CredentialDecision) -> str:
    """One line naming which credential this command ran under, and why."""

    if not decision.network:
        return ""
    if not decision.url:
        return (
            "No credential was applied: the remote this command would contact "
            "could not be resolved from the checkout, so there was nothing to "
            "authenticate against."
        )
    if not decision.token_applied:
        return (
            f"No credential was applied: {decision.url} is not this machine's "
            f"configured GitHub origin "
            f"({decision.web_url or 'https://github.com'}), so the command ran "
            "with the ambient credentials for that remote."
        )
    return (
        f"This machine's stored GitHub credential WAS applied, scoped to "
        f"{decision.url}. A credential prompt or authentication failure above "
        "means the remote rejected it rather than that none was supplied. The "
        "usual cause is that another local Yoke operation refreshed the "
        f"authorization while this command was in flight, so {GITHUB_AUTH_RETRY_RECIPE}. "
        "Do not reconnect GitHub to clear it: a reconnect rotates the "
        "authorization and revokes the token every other running command holds."
    )


def attributed(
    result: subprocess.CompletedProcess,
    decision: CredentialDecision,
) -> subprocess.CompletedProcess:
    """Append the credential attribution to a failed command's stderr."""

    line = attribution(decision)
    if not line:
        return result
    stderr = (result.stderr or "").rstrip()
    return subprocess.CompletedProcess(
        result.args,
        result.returncode,
        result.stdout,
        f"{stderr}\n{line}" if stderr else line,
    )


def command_text(argv: Sequence[str]) -> str:
    """Render a git argument vector for a diagnostic message."""

    return " ".join(str(item) for item in argv)


__all__ = [
    "LOCAL_COMMAND",
    "CredentialDecision",
    "attributed",
    "attribution",
    "command_text",
]
