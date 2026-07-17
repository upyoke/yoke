"""Pass-through arg-shape guards for ``watch_pytest``.

Split out of :mod:`yoke_core.tools.watch_pytest` to keep that module
under the authored-file line cap. Owns the rejection guards that repair
a doomed invocation before the underlying pytest run launches: the
nested ``python3 -m pytest`` shape and the bare ``runtime/`` path shape
(which demotes ``runtime/api/conftest.py`` from initial-conftest status
and fails collection — ``pytest_plugins`` in a non-top-level conftest).
"""

from __future__ import annotations

import os
import re
from typing import Sequence

NESTED_PYTEST_REJECTION_MESSAGE = (
    "watch_pytest expects bare pytest args after --; "
    "do not include python3 -m pytest.\n"
    "Example: python3 -m yoke_core.tools.watch_pytest -- runtime/api/ -q"
)

BARE_RUNTIME_REJECTION_MESSAGE = (
    "watch_pytest refuses bare 'runtime/' as a pytest path: anchoring "
    "collection at runtime/ demotes runtime/api/conftest.py from "
    "initial-conftest status and collection fails with \"Defining "
    "'pytest_plugins' in a non-top-level conftest is no longer "
    "supported\".\n"
    "Full-suite shape: python3 -m yoke_core.tools.watch_pytest -- "
    "runtime/api/ runtime/harness/ tests/"
)

# Match the bare interpreter names operators most commonly retype, plus
# the literal ``sys.executable`` token (sometimes copied from the wrapper
# source). Path forms (``/usr/bin/python3``) reuse this against the
# basename so we accept them without separately enumerating prefixes.
_PYTHON_BASENAME_RE = re.compile(r"^python(\d+(\.\d+)?)?$")


def looks_like_python_executable(token: str) -> bool:
    """Return True when ``token`` names a Python interpreter.

    Accepts ``python``, ``python3``, ``python3.11`` (and similar
    versioned forms), any path ending in one of those names, and the
    literal string ``sys.executable``. The literal token is included
    because the wrapper source itself spells the underlying invocation
    that way and operators occasionally paste it verbatim.
    """
    if token == "sys.executable":
        return True
    base = token.rsplit("/", 1)[-1]
    return bool(_PYTHON_BASENAME_RE.match(base))


def is_nested_pytest_invocation(args: Sequence[str]) -> bool:
    """Return True if pass-through ``args`` start with ``<python> -m pytest``."""
    if len(args) < 3:
        return False
    return (
        looks_like_python_executable(args[0])
        and args[1] == "-m"
        and args[2] == "pytest"
    )


# Pytest flags that consume the following token, so a flag value like
# ``-k runtime`` is never mistaken for a positional path arg.
_PYTEST_VALUE_FLAGS = frozenset(
    {"-k", "-m", "-n", "-p", "-o", "-W", "-c", "--rootdir", "--numprocesses"}
)


def has_bare_runtime_path(args: Sequence[str]) -> bool:
    """Return True when a positional pytest path arg is bare ``runtime``.

    Covers the ``runtime``, ``runtime/``, and ``./runtime/`` spellings
    via normpath. Anchored paths (``runtime/api/``) and flag values are
    never matched.
    """
    skip_next = False
    for token in args:
        if skip_next:
            skip_next = False
            continue
        if token.startswith("-"):
            skip_next = token in _PYTEST_VALUE_FLAGS
            continue
        if os.path.normpath(token) == "runtime":
            return True
    return False
