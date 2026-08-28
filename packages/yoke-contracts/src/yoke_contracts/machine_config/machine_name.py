"""The name this machine's operator gave it, for surfaces people read."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import socket
import subprocess
import sys


PROBE_TIMEOUT_SECONDS = 2

# Absolute binary paths, never bare names. The only process that persists this
# name is the relay daemon, and launchd hands that daemon a deliberately
# bounded PATH ending at /bin:/usr/bin — /usr/sbin, where scutil lives, is
# absent from it. A bare-name probe resolves through the caller's PATH, so it
# answers correctly from an interactive shell and fails in the one environment
# whose answer is written to the roster.
DARWIN_PROBE_COMMANDS = (
    # LocalHostName is the owner-set DNS label. ComputerName is the same idea
    # with spaces allowed.
    ("/usr/sbin/scutil", "--get", "LocalHostName"),
    ("/usr/sbin/scutil", "--get", "ComputerName"),
)
# systemd's "pretty" hostname is the operator-set one. It is routinely unset,
# and an unset value reports as empty output rather than as a failure.
LINUX_PROBE_COMMANDS = (("/usr/bin/hostnamectl", "--pretty"),)

_LOGGER = logging.getLogger(__name__)

# The relay re-resolves this name on every heartbeat, so an unrunnable probe
# would otherwise repeat its warning every few seconds and bury the rest of
# the log. Report each distinct failure once per process instead.
_reported_probe_failures: set[str] = set()


@dataclass(frozen=True)
class _ProbeOutcome:
    """A probe's answer, and the reason it could not produce one at all."""

    name: str = ""
    unavailable: str = ""


def _probe(command: tuple[str, ...]) -> _ProbeOutcome:
    """Run one name probe, separating "no answer" from "could not run".

    A probe that exits non-zero has answered: the platform holds no
    operator-set name, which is an ordinary reason to fall back. A probe whose
    binary cannot be executed has answered nothing, and folding the two
    together is what hid this defect through several rounds of fixing it.
    """
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except OSError as exc:
        return _ProbeOutcome(unavailable=f"{command[0]} could not be executed: {exc}")
    except subprocess.SubprocessError as exc:
        return _ProbeOutcome(unavailable=f"{command[0]} did not finish: {exc}")
    if completed.returncode != 0:
        return _ProbeOutcome()
    return _ProbeOutcome(name=completed.stdout.strip())


def _probe_commands() -> tuple[tuple[str, ...], ...]:
    if sys.platform == "darwin":
        return DARWIN_PROBE_COMMANDS
    if sys.platform.startswith("linux"):
        return LINUX_PROBE_COMMANDS
    # Windows already resolves the operator-set name through the host name, so
    # the fallback is the answer rather than a degraded one.
    return ()


def _report_unavailable_probes(reasons: list[str], fallback: str) -> None:
    unreported = [reason for reason in reasons if reason not in _reported_probe_failures]
    if not unreported:
        return
    _reported_probe_failures.update(unreported)
    _LOGGER.warning(
        "machine name probe could not run (%s); this machine is reporting the "
        "network host name %r, which on macOS is a generic token such as "
        "'Mac' rather than the name its operator chose. The probe uses an "
        "absolute binary path and deliberately ignores PATH, so a missing or "
        "non-executable binary at that exact path is the only cause: confirm "
        "the path exists and is executable on this host.",
        "; ".join(unreported),
        fallback,
    )


def machine_display_name() -> str:
    """Return the operator-set machine name, falling back to the host name.

    ``socket.gethostname()`` answers with whatever the network handed the
    host, which on macOS is a truncated DHCP-assigned label — a machine whose
    owner named it ``beebauman-macbook-pro-16`` answers ``Mac``. Two people on
    default-named laptops then become indistinguishable on any roster that
    shows the result. Ask the platform for the name its operator chose first,
    and keep the network name as the fallback that always answers.
    """
    chosen = ""
    unavailable: list[str] = []
    for command in _probe_commands():
        outcome = _probe(command)
        if outcome.unavailable:
            unavailable.append(outcome.unavailable)
            continue
        if outcome.name:
            chosen = outcome.name
            break
    fallback = socket.gethostname()
    if unavailable:
        _report_unavailable_probes(unavailable, fallback)
    return chosen or fallback


__all__ = [
    "DARWIN_PROBE_COMMANDS",
    "LINUX_PROBE_COMMANDS",
    "PROBE_TIMEOUT_SECONDS",
    "machine_display_name",
]
