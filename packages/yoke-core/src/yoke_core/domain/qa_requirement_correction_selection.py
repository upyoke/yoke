"""Resolve an exact failed obligation before correction cases fan out."""

from yoke_core.domain.qa_deployment_case_content_refresh import base_case_key
from yoke_core.domain.qa_requirement_replacement import QaReplacementError, _row


def resolve_correction_selection(conn, declarations):
    resolved, scopes = [], {}
    seen = set()
    for value in declarations:
        entry = dict(value)
        failed_id = int(entry["requirement_id"])
        if failed_id in seen:
            raise QaReplacementError(
                f"requirement {failed_id} is declared twice; name each failed requirement once"
            )
        seen.add(failed_id)
        failed = _row(conn, failed_id)
        if failed is None:
            raise QaReplacementError(
                f"requirement {failed_id} not found; inspect the failed requirement"
            )
        if entry.get("case_key") is None:
            if not failed.get("plan_case_key"):
                raise QaReplacementError(
                    f"requirement {failed_id} has no plan case key; inspect the failed "
                    "requirement and use --replaces CASE_KEY=REQUIREMENT_ID instead."
                )
            key = base_case_key(failed["plan_case_key"])
            entry.update(case_key=key, exact_scope=True)
        scopes.setdefault(entry["case_key"], []).append(failed)
        resolved.append(entry)
    return resolved, scopes
