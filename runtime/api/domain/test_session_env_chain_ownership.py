"""One module owns the session env chain; nothing else enumerates it.

A private copy of the chain is how a Codex subagent came to resolve to
its own thread: each copy listed the variables it happened to know
about, so adding one to the canonical chain fixed the canonical resolver
and left every copy behind. The guard below is therefore shaped around
*enumeration*, not mention — a module that reads one variable is asking
a single question ("is this a Codex process?"), while a module that
reads two in one expression is re-deriving the chain.

Scope is live source only. Tests legitimately build environments that
name several variables at once; they satisfy the same rule by importing
:data:`yoke_contracts.session_identity.AMBIENT_ENV_VARS` when they mean
"the whole chain", which is what makes a chain that grows reach them.

The owner spells the chain out per harness family rather than as one
flat tuple, because which family a process belongs to decides which of
the variables may answer for it. The guard therefore asks whether the
owner names every chain variable somewhere, not whether one statement
lists them all.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterator, List, Set, Tuple

from yoke_contracts.session_identity import AMBIENT_ENV_VARS


REPO_ROOT = Path(__file__).resolve().parents[3]

#: Trees holding code that runs in production, as opposed to test trees.
#: Each package's declared ``src`` root, so a stale ``build/lib`` copy of
#: a module — which is output, not source — never becomes a finding.
SOURCE_ROOTS = (
    *sorted(REPO_ROOT.glob("packages/*/src")),
    REPO_ROOT / ".yoke" / "doctor",
)

#: The chain's single owner, and the one module allowed to spell it out.
_CHAIN_OWNER = (
    "packages/yoke-contracts/src/yoke_contracts/harness_family_identity.py"
)

#: ``CODEX_THREAD_ID`` here keys a Codex *runtime thread* — which
#: transcript and cache belong to the process now running — and not a
#: Yoke session. Substituting the parent would read the wrong
#: transcript, so these lookups stay child-keyed by design.
_RUNTIME_THREAD_LOOKUPS = (
    "packages/yoke-harness/src/yoke_harness/hooks/identity_codex_runtime.py",
)

_EXEMPT = frozenset((_CHAIN_OWNER, *_RUNTIME_THREAD_LOOKUPS))

_CHAIN = frozenset(AMBIENT_ENV_VARS)


def source_files() -> Iterator[Path]:
    for root in SOURCE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            parts = path.parts
            if "install_bundle_tree" in parts or "__pycache__" in parts:
                continue
            yield path


def _relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _chain_names_in(node: ast.AST) -> Set[str]:
    """Chain variable names appearing as string literals under *node*."""
    return {
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant)
        and isinstance(child.value, str)
        and child.value in _CHAIN
    }


def _enumerations(tree: ast.AST) -> List[Tuple[int, Set[str]]]:
    """Return ``(lineno, names)`` for each expression naming 2+ variables.

    Walking statements rather than every nested node keeps one finding
    per site: an ``or`` chain, a tuple literal, and a nested
    ``os.environ.get(a, os.environ.get(b))`` all report once.
    """
    found: List[Tuple[int, Set[str]]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        names: Set[str] = set()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.stmt):
                continue  # a nested statement reports on its own pass
            names |= _chain_names_in(child)
        if len(names) > 1:
            found.append((node.lineno, names))
    return found


def test_the_scan_actually_reaches_the_source_tree() -> None:
    """A guard that silently scans nothing would pass forever."""
    assert len(list(source_files())) > 100


def test_only_session_identity_enumerates_the_chain() -> None:
    offenders: List[str] = []
    for path in source_files():
        rel = _relative(path)
        if rel in _EXEMPT:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:  # pragma: no cover - defensive
            offenders.append(f"{rel}: unreadable ({exc})")
            continue
        for lineno, names in _enumerations(tree):
            offenders.append(f"{rel}:{lineno} names {sorted(names)}")

    assert not offenders, (
        "these modules re-derive the session env chain instead of asking "
        "yoke_contracts.session_identity, so a variable added to the chain "
        "would not reach them:\n  " + "\n  ".join(offenders)
    )


def test_the_owner_really_does_enumerate_the_chain() -> None:
    """The guard above is only meaningful while the owner is the exception."""
    tree = ast.parse((REPO_ROOT / _CHAIN_OWNER).read_text(encoding="utf-8"))
    assert _chain_names_in(tree) == _CHAIN, (
        "the chain owner no longer spells out the chain; move the guard"
    )


def test_runtime_thread_lookups_stay_child_keyed() -> None:
    """The exempt module reads the child thread, and only the child thread."""
    for rel in _RUNTIME_THREAD_LOOKUPS:
        source = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "CODEX_THREAD_ID" in source
        assert "CODEX_SESSION_ID" not in source, (
            f"{rel} keys Codex runtime transcripts by the thread actually "
            "running; the parent session id does not belong there"
        )
