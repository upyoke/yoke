"""Categories, live severity, and operator-facing text for local privacy findings.

Yoke's authority over the operator's own machine is narrow, and this module
is where that boundary is written down. Whether an agent may read the
operator's documents or drive a GUI application is decided by the harness
permission prompt and the operating system's privacy controls — not here. So
those categories are classified for automated-test isolation and left alone
in live tool calls.

Two things survive as live verdicts. The system privacy database stays
refused outright, because a process that can read it enumerates every
application's grants and no permission prompt is asked first. Broad
discovery rooted at the home directory stays advisory, because it is almost
always an accident rather than a request, and saying so costs the agent one
line while a refusal costs it the work.
"""

from __future__ import annotations


SYSTEM_PRIVACY_DATABASE = "system_privacy_database"
HOME_DISCOVERY = "home_discovery"
PERSONAL_FILE_ACCESS = "personal_file_access"
LOCAL_GUI_AUTOMATION = "local_gui_automation"

LIVE_DENY = "deny"
LIVE_ADVISORY = "advisory"
LIVE_ALLOWED = "allowed"

# What each category means for a live tool call. Automated-test isolation
# reads none of this: the test tripwire blocks every category, because a
# unit test has no operator standing behind it to authorize anything.
LIVE_SEVERITY: dict[str, str] = {
    SYSTEM_PRIVACY_DATABASE: LIVE_DENY,
    HOME_DISCOVERY: LIVE_ADVISORY,
    PERSONAL_FILE_ACCESS: LIVE_ALLOWED,
    LOCAL_GUI_AUTOMATION: LIVE_ALLOWED,
}

_DIAGNOSIS = {
    SYSTEM_PRIVACY_DATABASE: (
        "Target: {target}\n"
        "Reading the system privacy database enumerates every application's "
        "{service} and Screen Recording grants on this machine. Yoke refuses "
        "this itself rather than deferring: the file is plain to any process "
        "that already holds {service}, so no harness prompt or operating "
        "system dialog stands between the read and the answer."
    ),
    HOME_DISCOVERY: (
        "Target: {target}\n"
        "This search is rooted at the operator's home directory ({service}) "
        "rather than at a project. Yoke is not refusing it — the harness "
        "permission prompt and the operating system's privacy controls decide "
        "whether it runs — but an unanchored home scan is nearly always "
        "accidental, and it is slow and noisy where an anchored search is "
        "neither."
    ),
    PERSONAL_FILE_ACCESS: (
        "Target: {target}\n"
        "This reads a privacy-managed personal folder ({service}). Yoke does "
        "not decide it: the harness permission prompt and the operating "
        "system's {service} authorization are what grant or refuse the read."
    ),
    LOCAL_GUI_AUTOMATION: (
        "Target: {target}\n"
        "This drives local GUI automation ({service}) on the operator's "
        "machine. Yoke does not decide it: the operating system's {service} "
        "authorization and the harness permission prompt are what grant or "
        "refuse it."
    ),
}

_LIVE_RECOVERY = {
    SYSTEM_PRIVACY_DATABASE: (
        "Read the single permission you actually need from System Settings > "
        "Privacy & Security, or run the probe against the sanctioned target "
        "host rather than the operator's machine."
    ),
    HOME_DISCOVERY: (
        "Anchor the search at the repository, the worktree, or a named "
        "harness dot-directory. For native harness binary discovery use "
        "resolve_native_cli / resolve_native_cli_source; _CLI_FALLBACKS owns "
        "bundled application paths."
    ),
}

_TEST_RECOVERY = (
    "Automated tests must not reach the operator's real machine. Point HOME "
    "and ZDOTDIR at the test fixture, use the fake automation opener, or — "
    "for a deliberate integration test — set "
    "YOKE_ALLOW_LOCAL_PRIVACY_INTEGRATION=1 in the child environment."
)


# Ordered weakest to strongest. A command touches several things and each
# operand answers separately, so the reported finding has to be the strongest
# one present: an allowed personal-file read sitting earlier in the same
# command must not speak for a privacy-database read sitting later in it.
_SEVERITY_RANK = {LIVE_ALLOWED: 0, LIVE_ADVISORY: 1, LIVE_DENY: 2}


def severity_rank(category: str) -> int:
    """Return the comparable strength of ``category``'s live severity."""
    return _SEVERITY_RANK[live_severity(category)]


def live_severity(category: str) -> str:
    """Return what a live tool call in ``category`` gets: deny/advisory/allowed."""
    return LIVE_SEVERITY.get(category, LIVE_ALLOWED)


def diagnosis(category: str, target: str, service: str) -> str:
    """Return the category's finding text, naming who actually decides."""
    template = _DIAGNOSIS.get(category)
    if template is None:
        raise ValueError(
            f"no local privacy diagnosis for category {category!r}; add one to "
            "local_privacy_messages._DIAGNOSIS when adding a category"
        )
    return template.format(target=target, service=service)


def live_reason(category: str, target: str, service: str) -> str:
    """Return the text a live deny or advisory shows, with its recovery step."""
    recovery = _LIVE_RECOVERY.get(category)
    if recovery is None:
        raise ValueError(
            f"category {category!r} is {live_severity(category)} in live tool "
            "calls and has no live message; check live_severity before "
            "composing one"
        )
    return f"{diagnosis(category, target, service)}\n\nRecovery: {recovery}"


def test_isolation_reason(category: str, target: str, service: str) -> str:
    """Return the text the automated-test tripwire shows for any category."""
    return f"{diagnosis(category, target, service)}\n\nRecovery: {_TEST_RECOVERY}"


__all__ = [
    "HOME_DISCOVERY",
    "LIVE_ADVISORY",
    "LIVE_ALLOWED",
    "LIVE_DENY",
    "LIVE_SEVERITY",
    "LOCAL_GUI_AUTOMATION",
    "PERSONAL_FILE_ACCESS",
    "SYSTEM_PRIVACY_DATABASE",
    "diagnosis",
    "live_reason",
    "live_severity",
    "severity_rank",
    "test_isolation_reason",
]
