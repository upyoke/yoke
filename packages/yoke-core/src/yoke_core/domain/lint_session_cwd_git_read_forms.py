"""Classify a git call as a read or a possible write.

``branch``, ``remote`` and ``config`` both report and write, so they are
read by form: a write flag or verb is a write, a list or get form is a
read, and otherwise a new branch name or a config value is a write.
"""

from __future__ import annotations

from typing import List, Optional

_GIT_VALUE_FLAGS = frozenset({"-C", "-c", "--config-env", "--git-dir", "--work-tree"})
# Inspection verbs report unless an output-file flag requests a write.
GIT_INSPECTION_SUBS = frozenset(
    {
        "status",
        "log",
        "diff",
        "show",
        "rev-parse",
        "describe",
        "ls-files",
        "ls-tree",
        "blame",
        "shortlog",
    }
)
GIT_LISTING_SUBS = frozenset({"branch", "remote", "config"})
GIT_READ_ONLY_SUBS = GIT_INSPECTION_SUBS | GIT_LISTING_SUBS
GIT_MUTATING_SUBS = frozenset({"commit", "add", "mv", "rm"})

_WRITE_FLAGS = {
    "branch": frozenset(
        "-d -D --delete -m -M --move -c -C --copy -u --set-upstream-to"
        " --unset-upstream --edit-description".split()
    ),
    "config": frozenset(
        "--add --unset --unset-all --replace-all --rename-section"
        " --remove-section -e --edit".split()
    ),
}
# Matched against the first positional only.
_WRITE_VERBS = {
    "remote": frozenset(
        "add remove rm rename set-url set-head set-branches prune update".split()
    ),
    "config": frozenset("set unset rename-section remove-section edit".split()),
}
# ``-v`` / ``--verbose`` stay out: with a name, ``branch -v`` creates it.
_READ_FORMS = {
    "branch": frozenset(
        "-l --list --contains --no-contains --merged --no-merged --points-at".split()
    ),
    "config": frozenset(
        "-l --list --get --get-all --get-regexp --get-urlmatch --get-color"
        " --get-colorbool get list".split()
    ),
}
# Config flags whose value is the next token, not a key or value.
_CONFIG_VALUE_FLAGS = frozenset({"-f", "--file", "--blob", "--type", "--default"})
# Positionals a listing subcommand accepts before it means a write.
_READ_POSITIONALS = {"branch": 0, "config": 1}


def git_subcommand_index(tokens: List[str]) -> Optional[int]:
    """Index of the git subcommand, skipping ``-C`` / ``--git-dir`` values."""
    if not tokens or tokens[0].rsplit("/", 1)[-1] != "git":
        return None
    i = 1
    while i < len(tokens):
        tok = tokens[i]
        if tok in _GIT_VALUE_FLAGS:
            i += 2
            continue
        if tok.startswith("--git-dir=") or tok.startswith("--work-tree="):
            i += 1
            continue
        if tok.startswith("-"):
            i += 1
            continue
        return i
    return None


def git_subcommand(tokens: List[str]) -> Optional[str]:
    """Return the git subcommand, skipping ``-C`` / ``--git-dir`` values."""
    index = git_subcommand_index(tokens)
    return None if index is None else tokens[index]


def _is_write_flag(sub: str, token: str) -> bool:
    """True when ``token`` selects a write flag the way git parses it.

    A long flag matches any write flag it abbreviates, as git accepts
    unique prefixes. A short cluster matches by letter, up to a letter
    whose value is attached (``-uorigin``, ``-f<file>``).
    """
    writes = _WRITE_FLAGS.get(sub, frozenset())
    if token.startswith("--"):
        name = token.split("=", 1)[0]
        return len(name) > 2 and any(flag.startswith(name) for flag in writes)
    value_flags = _CONFIG_VALUE_FLAGS if sub == "config" else frozenset()
    for letter in token[1:]:
        if f"-{letter}" in writes:
            return True
        if f"-{letter}" in value_flags:
            return False
    return False


def _listing_is_read(sub: str, args: List[str]) -> bool:
    flags, positionals = set(), []
    i = 0
    while i < len(args):
        token = args[i]
        if token.startswith("-"):
            if _is_write_flag(sub, token):
                return False
            flags.add(token.split("=", 1)[0])
            if sub == "config" and token in _CONFIG_VALUE_FLAGS:
                i += 1
        else:
            positionals.append(token)
        i += 1
    first = positionals[0] if positionals else ""
    if first in _WRITE_VERBS.get(sub, frozenset()):
        return False
    if sub == "remote":
        return True
    reads = _READ_FORMS[sub]
    if flags & reads or first in reads:
        return True
    return len(positionals) <= _READ_POSITIONALS[sub]


def classify_git(tokens: List[str]) -> Optional[str]:
    """``git-<sub>`` when the call only reads, including ``git -C <path>``."""
    index = git_subcommand_index(tokens)
    if index is None:
        return None
    sub = tokens[index]
    args = tokens[index + 1 :]
    if any(t == "--output" or t.startswith("--output=") for t in args):
        return None
    if sub in GIT_LISTING_SUBS and not _listing_is_read(sub, args):
        return None
    if sub in GIT_READ_ONLY_SUBS:
        return f"git-{sub}"
    return None


__all__ = [
    "GIT_INSPECTION_SUBS",
    "GIT_LISTING_SUBS",
    "GIT_MUTATING_SUBS",
    "GIT_READ_ONLY_SUBS",
    "classify_git",
    "git_subcommand",
    "git_subcommand_index",
]
