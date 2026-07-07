"""HCs covering the Codex hook substrate.

Three checks share this module because they all read the Codex hook artefacts
(``runtime/harness/codex/hooks.json``, ``runtime/harness/codex/manifest.json``,
and the SMOKE-TEST + parity-map docs):

* ``HC-codex-hook-matchers`` — required event/tool combinations are present in
  ``runtime/harness/codex/hooks.json``.
* ``HC-codex-hook-floor`` — operator's installed Codex CLI version meets the
  manifest's ``runtime_minimums.hook_enhanced`` floor.
* ``HC-codex-hook-doc-drift`` — Codex hook docs (the smoke runbook and the
  parity map's Codex sections) name the live matcher set.

The ``HC-apply-patch-*`` smoke checks live in ``doctor_hc_apply_patch`` to keep
each module comfortably below the 350-line cap.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import List, Sequence

from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
    _run,
)


# Required event -> matcher pairs in hooks.json. Codex hooks fire on Bash only
# in tested mode; matcher == "" means "no matcher" (event-level only).
_REQUIRED_HOOK_PAIRS: tuple[tuple[str, str], ...] = (
    ("SessionStart", ""),
    ("UserPromptSubmit", ""),
    ("PreToolUse", "Bash"),
    ("PostToolUse", "Bash"),
    ("Stop", ""),
)

_HOOKS_PATH = Path("runtime/harness/codex/hooks.json")
_MANIFEST_PATH = Path("runtime/harness/codex/manifest.json")
_SMOKE_DOC = Path("runtime/harness/codex/SMOKE-TEST.md")
_PARITY_DOC = Path("docs/hook-parity-map.md")


def _hooks_path() -> Path:
    root = _resolve_repo_root()
    return Path(root) / _HOOKS_PATH if root else _HOOKS_PATH


def _manifest_path() -> Path:
    root = _resolve_repo_root()
    return Path(root) / _MANIFEST_PATH if root else _MANIFEST_PATH


def _doc_path(rel: Path) -> Path:
    root = _resolve_repo_root()
    return Path(root) / rel if root else rel


# ---------------------------------------------------------------------------
# HC-codex-hook-matchers
# ---------------------------------------------------------------------------


def hc_codex_hook_matchers(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    name = "HC-codex-hook-matchers"
    desc = "Codex hooks.json matchers cover required event/tool combos"
    p = _hooks_path()
    if not p.exists():
        rec.record(name, desc, "FAIL", f"missing: {_HOOKS_PATH}")
        return
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        rec.record(name, desc, "FAIL", f"unreadable {_HOOKS_PATH}: {exc}")
        return

    hooks = data.get("hooks") or {}
    missing: List[str] = []
    for event, matcher in _REQUIRED_HOOK_PAIRS:
        entries = hooks.get(event)
        if not isinstance(entries, list) or not entries:
            missing.append(f"{event}{('@' + matcher) if matcher else ''}")
            continue
        if matcher:
            ok = any(
                isinstance(e, dict) and e.get("matcher") == matcher
                for e in entries
            )
            if not ok:
                missing.append(f"{event}@{matcher}")
        # event-level only — presence of any entry is enough
    if missing:
        rec.record(
            name, desc, "FAIL",
            "missing required hook entries: " + ", ".join(missing),
        )
        return
    rec.record(
        name, desc, "PASS",
        f"all {len(_REQUIRED_HOOK_PAIRS)} required hook entries present",
    )


# ---------------------------------------------------------------------------
# HC-codex-hook-floor
# ---------------------------------------------------------------------------


_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+(?:-[A-Za-z0-9._]+)?)")


def _parse_floor(value: str) -> str | None:
    """Extract a semver-ish token from a manifest floor string."""
    if not value:
        return None
    m = _VERSION_RE.search(value)
    return m.group(1) if m else None


def _semver_tuple(token: str) -> tuple:
    """Convert a semver-ish token to a comparable tuple. Pre-release strings
    sort after their base release ('0.118.0' > '0.118.0-alpha.2'), matching
    the SemVer 2.0 ordering rule that pre-releases precede their base."""
    base, _, pre = token.partition("-")
    parts = []
    for chunk in base.split("."):
        try:
            parts.append((0, int(chunk)))
        except ValueError:
            parts.append((1, chunk))
    if pre:
        # Pre-release tags sort BEFORE the base release.
        return (tuple(parts), 0, tuple(pre.split(".")))
    return (tuple(parts), 1, ())


def _read_floor_token() -> str | None:
    p = _manifest_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    raw = (data.get("runtime_minimums") or {}).get("hook_enhanced") or ""
    return _parse_floor(raw)


def _detect_codex_version() -> str | None:
    if not shutil.which("codex"):
        return None
    r = _run(["codex", "--version"], timeout=10)
    if r.returncode != 0:
        return None
    return _parse_floor((r.stdout or r.stderr or "").strip())


def hc_codex_hook_floor(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    name = "HC-codex-hook-floor"
    desc = "Operator Codex CLI meets manifest hook_enhanced floor"
    floor = _read_floor_token()
    if not floor:
        rec.record(
            name, desc, "PASS",
            "manifest hook_enhanced floor unavailable; "
            "skipping CLI version comparison",
        )
        return
    installed = _detect_codex_version()
    if not installed:
        rec.record(
            name, desc, "PASS",
            f"floor={floor}; codex CLI not installed locally — "
            "wrapper-only mode is the documented fallback",
        )
        return
    if _semver_tuple(installed) < _semver_tuple(floor):
        rec.record(
            name, desc, "FAIL",
            f"installed codex {installed} is below "
            f"manifest floor {floor}",
        )
        return
    rec.record(
        name, desc, "PASS",
        f"installed codex {installed} >= floor {floor}",
    )


# ---------------------------------------------------------------------------
# HC-codex-hook-doc-drift
# ---------------------------------------------------------------------------


def _doc_describes_pairs(
    text: str, pairs: Sequence[tuple[str, str]],
    *, strict: bool = True,
) -> List[str]:
    """Return the list of pairs not mentioned in *text*.

    When *strict* is True (parity map), require the literal event name. When
    False (smoke runbook), also accept common prose descriptions — for
    example, "Session start hook" satisfies SessionStart.
    """
    prose_aliases = {
        "SessionStart": ("session start", "session-start"),
        "UserPromptSubmit": ("prompt submit", "user prompt submit", "user-prompt-submit"),
        "PreToolUse": ("pre-tool", "pre/post tool", "pre tool"),
        "PostToolUse": ("post-tool", "pre/post tool", "post tool"),
        "Stop": ("stop hook", "stop behavior", "session-end", "session end"),
    }
    lowered = text.lower()
    missing: List[str] = []
    for event, matcher in pairs:
        present = bool(
            re.search(rf"(?<![A-Za-z0-9_]){re.escape(event)}(?![A-Za-z0-9_])", text)
        )
        if not present and not strict:
            present = any(alias in lowered for alias in prose_aliases.get(event, ()))
        if not present:
            missing.append(f"{event}{('@' + matcher) if matcher else ''}")
    return missing


def hc_codex_hook_doc_drift(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    name = "HC-codex-hook-doc-drift"
    desc = "Codex hook docs describe the current matcher set"
    smoke = _doc_path(_SMOKE_DOC)
    parity = _doc_path(_PARITY_DOC)
    issues: List[str] = []
    if not smoke.exists():
        issues.append(f"missing: {_SMOKE_DOC}")
    if not parity.exists():
        issues.append(f"missing: {_PARITY_DOC}")
    if issues:
        rec.record(name, desc, "FAIL", "\n".join(issues))
        return

    smoke_text = smoke.read_text(encoding="utf-8", errors="ignore")
    parity_text = parity.read_text(encoding="utf-8", errors="ignore")

    # The parity map lists each event/matcher pair explicitly. The smoke
    # runbook describes hook-enhanced mode; require it to mention each event.
    parity_missing = _doc_describes_pairs(
        parity_text, _REQUIRED_HOOK_PAIRS, strict=True,
    )
    smoke_missing = _doc_describes_pairs(
        smoke_text, _REQUIRED_HOOK_PAIRS, strict=False,
    )
    if parity_missing:
        issues.append(
            f"{_PARITY_DOC} omits: " + ", ".join(parity_missing),
        )
    if smoke_missing:
        issues.append(
            f"{_SMOKE_DOC} omits: " + ", ".join(smoke_missing),
        )

    if issues:
        rec.record(name, desc, "FAIL", "\n".join(issues))
    else:
        rec.record(name, desc, "PASS", "Codex hook docs reference all matchers")
