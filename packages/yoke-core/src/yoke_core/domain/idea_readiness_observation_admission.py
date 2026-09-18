"""What a readiness host may believe from a machine it does not control.

The four file-reading checks can run on a machine that holds the item
project's checkout and report back. That machine is not the control
plane, and its report is caller-supplied data on the way to consequences:
a reported issue becomes an issue the run blocks on, and the claim
repair turns an issue's ``context.path`` into a path-claim amendment.
So nothing here trusts the report's shape or its content.

Admission is a whitelist in both directions.

*Codes* — only what the four checks can emit is accepted. The
claim-coverage codes that drive widen and narrow are decided from the
path-claim tables and never from reading a file, so they are not on the
list and an observation asserting one is dropped rather than acted on.

*Context* — every admitted issue is re-derived against the spec the
control plane holds. A sizing code must name a path this item's File
Budget actually lists, a function-owner code must name a reference the
spec actually makes, and a rehearsal-command code must name a command
the item actually declared. An observing machine can therefore report
only findings about surfaces the control plane already knows this item
touches; it cannot introduce a new one by asserting it.

Rejections are returned rather than raised. A machine reporting one bad
issue among good ones is far more likely to be a version skew than an
attack, and the run says what it discarded instead of failing opaquely.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from yoke_core.domain.idea_readiness_results import (
    FILE_BUDGET_SIZING_CODES,
    FUNCTION_OWNER_CODES,
    Issue,
)

CODE_NOT_OBSERVABLE = "code_not_observable"
CONTEXT_NOT_IN_SPEC = "context_not_in_spec"


def _attestation_code() -> str:
    from yoke_core.domain.attestation_rehearsal_command_shape import (
        ATTESTATION_REHEARSAL_COMMAND_FAILED,
    )

    return ATTESTATION_REHEARSAL_COMMAND_FAILED


def _advisory_code() -> str:
    from yoke_core.domain.idea_readiness_symlink_advisory import ADVISORY_CODE

    return ADVISORY_CODE


def observable_issue_codes() -> Set[str]:
    """Every issue code a file read on another machine could have produced."""
    return set(FUNCTION_OWNER_CODES) | set(FILE_BUDGET_SIZING_CODES) | {
        _attestation_code(),
    }


def _budget_paths(spec_text: str) -> Set[str]:
    from yoke_core.domain.file_budget_paths import extract_file_budget_paths_set

    return set(extract_file_budget_paths_set(spec_text))


def _spec_references(spec_text: str) -> Set[str]:
    from yoke_core.domain.idea_readiness_check_refs import function_refs_to_verify

    return {ref for ref, _func in function_refs_to_verify(spec_text)}


def _context_is_grounded(
    code: str,
    context: Dict[str, Any],
    *,
    spec_text: str,
    rehearsal_commands: Iterable[str],
) -> bool:
    """Is this finding about something the control plane knows the item touches?"""
    if code in FILE_BUDGET_SIZING_CODES:
        return str(context.get("path") or "") in _budget_paths(spec_text)
    if code in FUNCTION_OWNER_CODES:
        return str(context.get("reference") or "") in _spec_references(spec_text)
    if code == _attestation_code():
        return str(context.get("command") or "") in set(rehearsal_commands)
    return False


def admit_issues(
    payloads: Optional[Iterable[Dict[str, Any]]],
    *,
    spec_text: str,
    rehearsal_commands: Iterable[str] = (),
) -> Tuple[List[Issue], List[Dict[str, Any]]]:
    """Split reported issues into the admissible ones and the discarded ones."""
    admitted: List[Issue] = []
    rejected: List[Dict[str, Any]] = []
    observable = observable_issue_codes()
    commands = set(rehearsal_commands)
    for payload in payloads or ():
        if not isinstance(payload, dict):
            rejected.append({"reason": CODE_NOT_OBSERVABLE, "code": ""})
            continue
        code = str(payload.get("code") or "")
        context = dict(payload.get("context") or {})
        if code not in observable:
            rejected.append({"reason": CODE_NOT_OBSERVABLE, "code": code})
            continue
        if not _context_is_grounded(
            code, context, spec_text=spec_text, rehearsal_commands=commands,
        ):
            rejected.append({
                "reason": CONTEXT_NOT_IN_SPEC, "code": code, "context": context,
            })
            continue
        admitted.append(Issue(
            code=code,
            message=str(payload.get("message") or ""),
            remediation=str(payload.get("remediation") or ""),
            context=context,
        ))
    return admitted, rejected


def admit_advisories(
    payloads: Optional[Iterable[Dict[str, Any]]], *, spec_text: str,
) -> List[Dict[str, Any]]:
    """Keep only symlink hints naming a path this item's File Budget lists."""
    advisory_code = _advisory_code()
    budget_paths = _budget_paths(spec_text)
    kept: List[Dict[str, Any]] = []
    for payload in payloads or ():
        if not isinstance(payload, dict):
            continue
        if str(payload.get("code") or "") != advisory_code:
            continue
        context = dict(payload.get("context") or {})
        if str(context.get("symlink_path") or "") not in budget_paths:
            continue
        kept.append(dict(payload))
    return kept


__all__ = [
    "CODE_NOT_OBSERVABLE",
    "CONTEXT_NOT_IN_SPEC",
    "admit_advisories",
    "admit_issues",
    "observable_issue_codes",
]
