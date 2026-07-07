"""HC-tier-cli-shape-bleed — Tier 0/2/4/5 surfaces must teach live CLI shapes.

Three argparse-help-driven checks over Tier 0/2/4/5 surfaces:

* Check A — CLI shape drift. Invocations whose cited ``--<flag>`` is
  not in ``python3 -m <module> [<sub>] --help`` output. Lines whose
  text contains any :data:`RETAINED_TERMINAL_BOUNDARIES` surface
  substring (or any :data:`NEGATIVE_EXAMPLE_MARKERS` substring) are
  exempted before Stage 2 introspection.
* Check B — bare Doctor scope. Start-of-line (or ``$ ``/``> `` prefixed)
  ``python3 -m yoke_core.engines.doctor`` without ``--quick``,
  ``--full``, ``--only``, ``--list-checks``, or ``--help``.
* Check C — stale subcommand help. When ``<module> <sub> --help`` fails,
  consult ``<module> --help``: subcommand listed but broken-help = stale
  finding; subcommand not listed = confabulation finding.

Severity WARN in v0; findings truncated to ``_MAX_FINDINGS``.
"""

from __future__ import annotations

import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

from yoke_core.domain.function_inventory_data import RETAINED_TERMINAL_BOUNDARIES
from yoke_core.engines.doctor_registry_tier_discipline import (
    TIER_6_ARCHIVE_PREFIXES,
    iter_tier_paths,
)
from yoke_core.engines.doctor_report import (
    DoctorArgs,
    RecordCollector,
    _resolve_repo_root,
)


HC_SLUG = "HC-tier-cli-shape-bleed"
HC_LABEL = (
    "Tier 0/2/4/5 surface teaches drifted CLI shape, bare Doctor "
    "invocation, or stale subcommand help"
)
_MAX_FINDINGS = 40
_HELP_TIMEOUT_SECONDS = 10


# Substrings that mark a line as a deliberately-quoted wrong shape (so
# the HC doesn't fire on parent specs' own teaching surface, nor on
# anti-pattern docs). Case-sensitive substring match.
NEGATIVE_EXAMPLE_MARKERS: Tuple[str, ...] = (
    "Anti-pattern", "DO NOT use", "WRONG:", "Negative example", "fails:",
    "rejects:", "deprecated:", "anti-example", "(formerly)", "legacy:",
)

# Scope flags whose presence on a bare-Doctor line exempts it.
_DOCTOR_SCOPE_FLAGS: Tuple[str, ...] = (
    "--quick", "--full", "--only", "--list-checks", "--help",
)


# Module dotted path, optional subcommand, remaining flags
# (up to next newline or `|` pipe). The subcommand token must start
# with a letter so `--flag` tokens are not mistaken for a subcommand.
# Bare-Doctor regex (Check B) is start-of-line anchored with optional
# `$ ` / `> ` prefix.
_INVOCATION_RE = re.compile(
    r"^[\s$>]*python3 -m (?P<module>[\w.]+)"
    r"(?:\s+(?P<sub>[A-Za-z][\w-]*))?"
    r"(?P<flags>[^\n|]*)"
)
_DOCTOR_LINE_RE = re.compile(
    r"^\s*[\$>]?\s*python3 -m "
    r"(?:runtime\.api\.engines|yoke_core\.engines)\.doctor(\s|$)"
)
_CITED_LONG_OPTION_RE = re.compile(r"(--[a-z][a-z0-9-]*)")
# `\B` lets the help-stdout pattern match indented option-table lines
# and inline usage tokens like `[--quick]`.
_LONG_OPTION_FROM_HELP_RE = re.compile(r"\B(--[a-z][a-z0-9-]*)")
# Subcommand extractors — argparse `{a,b,c}` braces, one-per-line
# indented bodies (Yoke's hand-rolled help renderers), and the
# Commands-line comma-list shape (service_client's hand-rolled help).
_USAGE_SUBCOMMAND_BRACE_RE = re.compile(r"\{([a-z][a-z0-9_,-]+)\}")
_SUBCOMMAND_TOKEN_RE = re.compile(r"^\s+([a-z][a-z0-9-]*)\s*(?:$|\s{2,})")
_COMMANDS_LINE_RE = re.compile(r"^\s*Commands:\s*(.+)$", re.MULTILINE)
_COMMA_TOKEN_RE = re.compile(r"\b([a-z][a-z0-9-]*)\b")


def _surface_match(line: str) -> bool:
    """True when `line` contains any retained-boundary discriminative prefix.

    The HC reads `RetainedBoundary.surface` ONLY (never indexes by
    module/sub). Surface labels may carry trailing parentheticals;
    the prefix before the first ``(`` is the discriminative portion
    that appears in real invocation lines.
    """

    for boundary in RETAINED_TERMINAL_BOUNDARIES:
        prefix = boundary.surface.split("(", 1)[0].strip() if boundary.surface else ""
        if prefix and prefix in line:
            return True
    return False


def _is_negative_example(line: str) -> bool:
    return any(marker in line for marker in NEGATIVE_EXAMPLE_MARKERS)


def _check_b_bare_doctor(line: str) -> bool:
    """True if `line` is a bare Doctor invocation needing a scope flag."""
    if not _DOCTOR_LINE_RE.match(line) or _is_negative_example(line):
        return False
    head = line.split("|", 1)[0]
    return not any(flag in head for flag in _DOCTOR_SCOPE_FLAGS)


HelpCache = Dict[Tuple[str, Optional[str]], Tuple[int, str]]


def _run_help(repo_root: Path, module: str, sub: Optional[str]) -> Tuple[int, str]:
    """Run ``python3 -m <module> [<sub>] --help``; return (rc, combined output)."""
    # Bounded by `_HELP_TIMEOUT_SECONDS`; on timeout / OS error returns
    # (1, "") so Check A/C routes cleanly rather than crashing.
    cmd = ["python3", "-m", module] + ([sub] if sub else []) + ["--help"]
    try:
        completed = subprocess.run(  # noqa: S603 — argv from constants.
            cmd,
            cwd=str(repo_root),
            timeout=_HELP_TIMEOUT_SECONDS,
            capture_output=True,
            text=True,
        )
    except (subprocess.TimeoutExpired, OSError):
        return 1, ""
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def _cached_help(repo_root, module, sub, cache: HelpCache) -> Tuple[int, str]:
    if (module, sub) not in cache:
        cache[(module, sub)] = _run_help(repo_root, module, sub)
    return cache[(module, sub)]


def _extract_long_options(help_stdout: str) -> Set[str]:
    return set(_LONG_OPTION_FROM_HELP_RE.findall(help_stdout))


def _extract_subcommands(parent_help_stdout: str) -> Set[str]:
    subs: Set[str] = set()
    for brace in _USAGE_SUBCOMMAND_BRACE_RE.findall(parent_help_stdout):
        subs.update(tok for tok in brace.split(",") if tok)
    for raw in parent_help_stdout.splitlines():
        match = _SUBCOMMAND_TOKEN_RE.match(raw)
        if match:
            subs.add(match.group(1))
    for line in _COMMANDS_LINE_RE.findall(parent_help_stdout):
        subs.update(_COMMA_TOKEN_RE.findall(line))
    return subs


def _check_a_or_c(
    rel: str,
    lineno: int,
    module: str,
    sub: Optional[str],
    cited_flags: List[str],
    repo_root: Path,
    cache: HelpCache,
) -> List[str]:
    """Stage-2 introspection on one invocation; return finding lines."""
    rc, stdout = _cached_help(repo_root, module, sub, cache)
    if rc != 0 and sub:
        parent_rc, parent_stdout = _cached_help(repo_root, module, None, cache)
        if parent_rc == 0 and sub in _extract_subcommands(parent_stdout):
            return [
                f"- {rel}:{lineno}: stale subcommand help: `{sub}` is listed "
                f"in `python3 -m {module} --help` but its own --help fails"
            ]
        return [
            f"- {rel}:{lineno}: `python3 -m {module} {sub}` not found in "
            f"`python3 -m {module} --help` (confabulated subcommand)"
        ]
    if rc != 0:
        return [
            f"- {rel}:{lineno}: `python3 -m {module} --help` exits non-zero "
            "(module path may be confabulated)"
        ]
    valid_long_options = _extract_long_options(stdout)
    findings: List[str] = []
    for flag in cited_flags:
        if flag not in valid_long_options:
            sub_repr = f" {sub}" if sub else ""
            findings.append(
                f"- {rel}:{lineno}: flag `{flag}` not found in `python3 -m "
                f"{module}{sub_repr} --help`"
            )
    return findings


def _scan_file(rel: str, text: str, repo_root: Path, cache: HelpCache) -> List[str]:
    findings: List[str] = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip("\n")
        # Check B (regex only) runs first; Check A/C is per-invocation.
        if _check_b_bare_doctor(line):
            findings.append(
                f"- {rel}:{lineno}: bare `python3 -m yoke_core.engines.doctor` "
                "without --quick/--full/--only/--list-checks/--help scope"
            )
        match = _INVOCATION_RE.match(line)
        if not match or _surface_match(line) or _is_negative_example(line):
            continue
        sub = match.group("sub")
        cited = _CITED_LONG_OPTION_RE.findall(match.group("flags") or "")
        if not cited and sub is None:
            continue
        findings.extend(
            _check_a_or_c(rel, lineno, match.group("module"), sub, cited, repo_root, cache)
        )
    return findings


def _collect_help_keys(
    repo_root: Path, tiers: Iterable[int]
) -> Tuple[List[Tuple[str, str]], Set[Tuple[str, Optional[str]]]]:
    """Walk Tier 0/2/4/5 once; return (payloads, unique help keys).

    Payloads are (rel, text) tuples (avoids re-reading on the second
    pass). Keys cover every (module, sub) pair that survives Stage 1
    plus the parent (module, None) when sub is set (Check C).
    """
    payloads: List[Tuple[str, str]] = []
    keys: Set[Tuple[str, Optional[str]]] = set()
    for _tier, abs_path in iter_tier_paths(repo_root, tiers=tiers):
        rel = abs_path.relative_to(repo_root).as_posix()
        if any(rel.startswith(prefix) for prefix in TIER_6_ARCHIVE_PREFIXES):
            continue
        try:
            text = abs_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        payloads.append((rel, text))
        for raw in text.splitlines():
            match = _INVOCATION_RE.match(raw.rstrip("\n"))
            if not match or _surface_match(raw) or _is_negative_example(raw):
                continue
            sub = match.group("sub")
            cited = _CITED_LONG_OPTION_RE.findall(match.group("flags") or "")
            if not cited and sub is None:
                continue
            module = match.group("module")
            keys.add((module, sub))
            if sub:
                keys.add((module, None))
    return payloads, keys


def _scan_all(repo_root: Path, tiers: Iterable[int] = (0, 2, 4, 5)) -> List[str]:
    """Two-pass scan: collect payloads + help keys, prewarm cache in
    parallel, then run per-file Check A/B/C with cache-hits only.
    """
    payloads, keys = _collect_help_keys(repo_root, tiers)
    cache: HelpCache = {}
    if keys:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for key, result in ex.map(
                lambda k: (k, _run_help(repo_root, k[0], k[1])), keys
            ):
                cache[key] = result
    findings: List[str] = []
    for rel, text in payloads:
        findings.extend(_scan_file(rel, text, repo_root, cache))
    return findings


def _format_detail(findings: List[str]) -> str:
    if len(findings) <= _MAX_FINDINGS:
        return "\n".join(findings)
    truncated = findings[:_MAX_FINDINGS]
    extra = len(findings) - _MAX_FINDINGS
    truncated.append(f"… {extra} more references")
    return "\n".join(truncated)


def hc_tier_cli_shape_bleed(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-tier-cli-shape-bleed: argparse-help-driven CLI-shape drift scan."""

    repo_root = _resolve_repo_root()
    if not repo_root:
        rec.record(HC_SLUG, HC_LABEL, "PASS", "repo root not resolvable (skip)")
        return
    findings = _scan_all(Path(repo_root))
    result = "WARN" if findings else "PASS"
    rec.record(HC_SLUG, HC_LABEL, result, _format_detail(findings) if findings else "")


__all__ = ["hc_tier_cli_shape_bleed", "HC_SLUG", "HC_LABEL", "NEGATIVE_EXAMPLE_MARKERS"]
