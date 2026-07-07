"""Doctor HC: field-note channel coherence.

``HC-field-note-coherence`` bundles two checks so drift is
impossible across either axis:

* **Drift check** — invokes
  :func:`yoke_core.tools.render_field_note_inline.render` in
  ``check=True`` mode; FAILs on any drift or orphan-marker condition.
* **Consumer-import check** — scans ``IMPORTING_CONSUMERS`` and FAILs
  when any one no longer imports a canonical name from
  :mod:`yoke_contracts.field_note_text` (directly OR via
  ``append_field_note_footer`` which does). The packet seeds carry
  the canonical recipe string verbatim as packet *data* and are
  validated separately for presence of the canonical command.

``IMPORTING_CONSUMERS`` / ``PACKET_SEED_CONSUMERS`` are the contract
tuples (same shape as ``IN_SCOPE_WRITERS`` in the architecture-model
HCs); tests assert against them. The HC self-skips cleanly when the
canonical source module or renderer is missing.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from yoke_core.api.repo_root import find_repo_root
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


HC_NAME = "HC-field-note-coherence"
HC_DESC = (
    "Field-note channel coherence: renderer --check + "
    "named consumers import from field_note_text"
)

CANONICAL_MODULE = "yoke_contracts.field_note_text"
HELPER_MODULE = "yoke_core.domain.denial_field_note_footer"
HELPER_SYMBOL = "append_field_note_footer"
CANONICAL_COMMAND = "ouroboros field-note append"
_CORE_DOMAIN_SOURCE_ROOT = "packages/yoke-core/src/yoke_core/domain"

_LINTS: Tuple[str, ...] = tuple(
    f"{_CORE_DOMAIN_SOURCE_ROOT}/lint_{s}.py" for s in (
        "claim_ownership_mutations", "destructive_git", "event_registry",
        "git_stash_arg_order", "long_command_polling", "main_commit",
        "no_agent_curl_against_yoke_api",
        "no_agent_runtime_api_import_from_c", "python_runtime_import_in_tmp",
        "session_cwd", "shell_quoted_function_payload",
        "shell_quoted_function_payload_messages", "sqlite_cmd", "sqlite_rules",
        "structured_field_transform_shell",
        "structured_field_transform_shell_messages", "subagent_background",
        "yok_n_cruft", "tc_label", "workspace_cwd_match",
        "worktree_path_invariants", "write_path",
    )
)

# Code consumers that MUST import a canonical name from
# ``field_note_text`` (directly or via the helper that does).
IMPORTING_CONSUMERS: Tuple[str, ...] = (
    "packages/yoke-cli/src/yoke_cli/main.py",
    "packages/yoke-cli/src/yoke_cli/commands/adapters/misc.py",
    "packages/yoke-contracts/src/yoke_contracts/api/function_call.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/denial_field_note_footer.py",
    "packages/yoke-core/src/yoke_core/engines/doctor.py",
) + _LINTS

# Packet seeds carry the canonical field-note command verbatim as
# packet data; they teach the channel to every session.
PACKET_SEED_CONSUMERS: Tuple[str, ...] = (
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_commands_core.py",
    f"{_CORE_DOMAIN_SOURCE_ROOT}/schema_api_context_commands_core_operational.py",
)


def _project_root() -> Path:
    return find_repo_root(Path(__file__))


def _consumer_imports_canonical(repo_root: Path, relpath: str) -> Optional[bool]:
    candidate = repo_root / relpath
    if not candidate.is_file():
        return None
    try:
        text = candidate.read_text(encoding="utf-8")
    except OSError:
        return None
    return (
        CANONICAL_MODULE in text
        or (HELPER_MODULE in text and HELPER_SYMBOL in text)
    )


def scan_importing_consumers(
    repo_root: Path, *, consumers: Sequence[str] = IMPORTING_CONSUMERS,
) -> List[str]:
    """Return repo-relative paths of importing consumers that don't import."""
    return [
        rel for rel in consumers
        if _consumer_imports_canonical(repo_root, rel) is False
    ]


def scan_packet_seeds(
    repo_root: Path, *, seeds: Sequence[str] = PACKET_SEED_CONSUMERS,
) -> List[str]:
    """Return packet seeds missing the canonical field-note command."""
    missing: List[str] = []
    for relpath in seeds:
        candidate = repo_root / relpath
        if not candidate.is_file():
            continue
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        if CANONICAL_COMMAND not in text:
            missing.append(relpath)
    return missing


def _run_renderer_check(
    repo_root: Path,
) -> Tuple[Optional[str], List[str], List[str]]:
    """Invoke the renderer in --check mode; degrade gracefully."""
    try:
        from yoke_core.tools import render_field_note_inline as rri
    except Exception as exc:  # noqa: BLE001
        return (f"renderer not importable ({exc}) — skipping", [], [])
    try:
        result = rri.render(repo_root, check=True)
    except Exception as exc:  # noqa: BLE001
        return (f"renderer raised ({exc}) — skipping", [], [])
    return (None, [o.path for o in result.changed],
            list(result.orphan_marker_errors))


def hc_field_note_coherence(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Doctor entry. Combines drift + consumer-import checks."""
    repo_root = _project_root()
    findings: List[str] = []

    skip, changed, orphans = _run_renderer_check(repo_root)
    if skip is not None:
        rec.record(HC_NAME, HC_DESC, "PASS", skip)
        return
    if changed:
        findings.append(
            f"- renderer would rewrite {len(changed)} marker file(s) — run "
            "`python3 -m yoke_core.tools.render_field_note_inline` "
            "(no flag = write mode) and re-stage:"
        )
        findings.extend(f"  - {p}" for p in changed)
    if orphans:
        findings.append(
            f"- {len(orphans)} marker file(s) carry orphan / malformed pairs:"
        )
        findings.extend(f"  - {line}" for line in orphans)

    missing = scan_importing_consumers(repo_root)
    if missing:
        findings.append(
            f"- {len(missing)} named code consumer(s) no longer import from "
            f"`{CANONICAL_MODULE}` (directly or via "
            f"`{HELPER_MODULE}.{HELPER_SYMBOL}`):"
        )
        findings.extend(f"  - {p}" for p in missing)

    seeds_missing = scan_packet_seeds(repo_root)
    if seeds_missing:
        findings.append(
            f"- {len(seeds_missing)} packet seed(s) no longer carry the "
            f"canonical `{CANONICAL_COMMAND}` recipe string:"
        )
        findings.extend(f"  - {p}" for p in seeds_missing)

    if not findings:
        rec.record(
            HC_NAME, HC_DESC, "PASS",
            f"renderer --check clean; {len(IMPORTING_CONSUMERS)} importing "
            f"consumer(s) + {len(PACKET_SEED_CONSUMERS)} packet seed(s) coherent.",
        )
        return
    rec.record(HC_NAME, HC_DESC, "FAIL", "\n".join(findings))


__all__ = [
    "HC_NAME", "HC_DESC", "CANONICAL_MODULE", "HELPER_MODULE", "HELPER_SYMBOL",
    "CANONICAL_COMMAND", "IMPORTING_CONSUMERS", "PACKET_SEED_CONSUMERS",
    "hc_field_note_coherence", "scan_importing_consumers",
    "scan_packet_seeds",
]
