"""Doctor HC for enum coverage of ``HarnessToolCallDenied`` emitter outcomes.

Two scans gate the report:

* **Source scan** — AST-walk every Python module under
  ``runtime/api/`` and ``runtime/harness/`` (excluding tests and this
  HC's own test fixture file). For each ``emit_denial_event(...)`` call,
  resolve the ``outcome=...`` keyword arg. Literal strings are checked
  directly; bare ``Name`` references are traced to local assignments in
  the same function body. Every resolved literal must be a member of
  :data:`yoke_core.domain.events_tool_call_outcome.OUTCOMES`.

* **Live-events scan** — query the ``events`` ledger for
  ``HarnessToolCallDenied`` rows in the last 3 days whose
  ``event_outcome`` is not in :data:`OUTCOMES`. A drifted row indicates
  an emitter exists that the source scan missed (dynamic value, runtime
  reflection, etc.) or that ``OUTCOMES`` was tightened without sweeping
  historical rows.

Verdicts:

* **FAIL** — at least one source literal or live row carries a
  non-enum value.
* **PASS** — both scans clean.
* **SKIP** — the events table is missing (minimal-schema fixture
  install).
"""

from __future__ import annotations

from yoke_core.domain import db_backend
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, List, Optional, Set, Tuple

from yoke_core.domain.events_tool_call_outcome import OUTCOMES
from yoke_core.domain.schema_common import _table_exists
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


HC_ID = "event-outcome-enum-coverage"
HC_NAME = "Tool-call outcome enum coverage for HarnessToolCallDenied emitters"

_TARGET_EVENT_NAME = "HarnessToolCallDenied"
_SCAN_ROOTS = ("runtime/api", "runtime/harness")
_EMITTER_NAME = "emit_denial_event"


def _resolve_repo_root_for_hc(args: DoctorArgs) -> Path:
    """Return the doctor's target repo root.

    Falls back to ``git rev-parse --show-toplevel`` via
    :func:`doctor_report._resolve_repo_root`; tests pin this resolver
    directly via ``mock.patch.object``.
    """
    from yoke_core.engines.doctor_report import _resolve_repo_root

    git_root = _resolve_repo_root()
    if git_root:
        return Path(git_root)
    from yoke_core.api.repo_root import find_repo_root

    return find_repo_root(Path(__file__))


def _iter_source_files(repo_root: Path) -> Iterable[Path]:
    """Yield every Python source file under the scan roots."""
    for rel in _SCAN_ROOTS:
        base = repo_root / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            name = path.name
            if name.startswith("test_") or name.endswith("_test.py"):
                continue
            yield path


def _trace_local_string_literals(
    func_node: ast.AST, var_name: str
) -> Optional[Set[str]]:
    """Return the set of string literals ``var_name`` may carry in
    *func_node*, or ``None`` when the variable is not bound to a known
    set of literals (e.g. function-call result, attribute access).
    """
    seen: Set[str] = set()
    found_any = False
    for node in ast.walk(func_node):
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        else:
            continue
        if not any(
            isinstance(t, ast.Name) and t.id == var_name for t in targets
        ):
            continue
        found_any = True
        for literal in _expression_literals(node.value):
            if literal is None:
                return None
            seen.add(literal)
    if not found_any:
        return None
    return seen


def _expression_literals(expr: ast.AST) -> List[Optional[str]]:
    """Return the list of string literals ``expr`` may evaluate to.

    Returns ``[None]`` when any branch is untraceable (function call,
    attribute access, etc.). Handles bare ``ast.Constant`` strings and
    ``ast.IfExp`` (ternary expressions) commonly used as
    ``"suppression_attempted" if suppression_seen else "denied"``.
    """
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return [expr.value]
    if isinstance(expr, ast.IfExp):
        return _expression_literals(expr.body) + _expression_literals(
            expr.orelse
        )
    return [None]


def _scan_call_outcome(
    call: ast.Call, enclosing_func: Optional[ast.AST]
) -> Optional[Set[str]]:
    """Return the set of literals ``call``'s ``outcome=`` kwarg may carry.

    ``None`` means the literal could not be resolved (a dynamic value the
    HC must surface as an "unresolved" finding).
    """
    outcome_arg: Optional[ast.AST] = None
    for kw in call.keywords:
        if kw.arg == "outcome":
            outcome_arg = kw.value
            break
    if outcome_arg is None:
        return set()
    if isinstance(outcome_arg, ast.Constant) and isinstance(
        outcome_arg.value, str
    ):
        return {outcome_arg.value}
    if isinstance(outcome_arg, ast.IfExp):
        literals = _expression_literals(outcome_arg)
        if None in literals:
            return None
        return {lit for lit in literals if lit is not None}
    if isinstance(outcome_arg, ast.Name) and enclosing_func is not None:
        return _trace_local_string_literals(enclosing_func, outcome_arg.id)
    return None


def _scan_file(path: Path) -> List[Tuple[int, Optional[Set[str]]]]:
    """Return ``[(lineno, literals_or_None), ...]`` for each
    ``emit_denial_event(...)`` call in *path*. ``literals_or_None`` is
    ``None`` when the literal could not be resolved."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    findings: List[Tuple[int, Optional[Set[str]]]] = []
    enclosing_stack: List[ast.AST] = []

    class _Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            enclosing_stack.append(node)
            self.generic_visit(node)
            enclosing_stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

        def visit_Call(self, node: ast.Call) -> None:
            if _is_emit_denial_call(node):
                enclosing = enclosing_stack[-1] if enclosing_stack else None
                literals = _scan_call_outcome(node, enclosing)
                findings.append((node.lineno, literals))
            self.generic_visit(node)

    _Visitor().visit(tree)
    return findings


def _is_emit_denial_call(call: ast.Call) -> bool:
    """Return True when *call* invokes :func:`emit_denial_event`."""
    func = call.func
    if isinstance(func, ast.Name) and func.id == _EMITTER_NAME:
        return True
    if isinstance(func, ast.Attribute) and func.attr == _EMITTER_NAME:
        return True
    return False


def _source_scan(repo_root: Path) -> Tuple[List[str], List[str]]:
    """Walk the source tree and partition findings.

    Returns ``(non_enum_findings, unresolved_findings)`` — both lists of
    human-readable ``relpath:line — <detail>`` strings.
    """
    non_enum: List[str] = []
    unresolved: List[str] = []
    for source_path in _iter_source_files(repo_root):
        try:
            rel = source_path.relative_to(repo_root)
        except ValueError:
            rel = source_path
        for lineno, literals in _scan_file(source_path):
            if literals is None:
                unresolved.append(
                    f"{rel}:{lineno} — outcome= value could not be "
                    "resolved to a string literal (dynamic expression)"
                )
                continue
            offenders = [lit for lit in literals if lit not in OUTCOMES]
            if offenders:
                non_enum.append(
                    f"{rel}:{lineno} — outcome literal(s) "
                    f"{sorted(offenders)!r} not in OUTCOMES"
                )
    return non_enum, unresolved


def _live_events_scan(conn: Any) -> List[Tuple[str, str, int]]:
    """Return ``[(event_outcome, sample_event_id, count), ...]`` for any
    ``HarnessToolCallDenied`` rows in the 3-day window whose
    ``event_outcome`` is outside OUTCOMES."""
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    placeholders = ",".join(p for _ in OUTCOMES)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=3)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    params: Tuple = (_TARGET_EVENT_NAME, *sorted(OUTCOMES), cutoff)
    sql = (
        "SELECT event_outcome, MIN(event_id) AS sample, COUNT(*) AS n "
        "FROM events "
        f"WHERE event_name = {p} "
        f"AND event_outcome NOT IN ({placeholders}) "
        f"AND created_at > {p} "
        "GROUP BY event_outcome ORDER BY n DESC"
    )
    return list(conn.execute(sql, params).fetchall())


def _events_table_exists(conn: Any) -> bool:
    return _table_exists(conn, "events")


def hc_event_outcome_enum_coverage(
    conn: Any, args: DoctorArgs, rec: RecordCollector
) -> None:
    if not _events_table_exists(conn):
        rec.record(
            f"HC-{HC_ID}",
            HC_NAME,
            "SKIP",
            "events table not present on this DB",
        )
        return

    repo_root = _resolve_repo_root_for_hc(args)
    non_enum, unresolved = _source_scan(repo_root)

    try:
        live_findings = _live_events_scan(conn)
    except db_backend.database_error_types(conn) as exc:
        rec.record(
            f"HC-{HC_ID}",
            HC_NAME,
            "SKIP",
            f"events read failed: {exc}",
        )
        return

    if non_enum or live_findings:
        lines: List[str] = []
        if non_enum:
            lines.append(
                f"{len(non_enum)} source literal(s) outside OUTCOMES:"
            )
            lines.extend(f"- {entry}" for entry in non_enum[:10])
            if len(non_enum) > 10:
                lines.append(f"- ... +{len(non_enum) - 10} more")
        if live_findings:
            lines.append(
                f"{len(live_findings)} non-enum outcome(s) in the "
                f"last 3 days of HarnessToolCallDenied rows:"
            )
            for outcome, sample, count in live_findings:
                lines.append(
                    f"- outcome={outcome!r} count={count} "
                    f"sample_event_id={sample}"
                )
        if unresolved:
            lines.append(
                f"({len(unresolved)} unresolved outcome= expression(s) "
                "not counted as failures)"
            )
        rec.record(f"HC-{HC_ID}", HC_NAME, "FAIL", "\n".join(lines))
        return

    detail = (
        f"All emit_denial_event(outcome=...) literals resolved to "
        f"members of OUTCOMES; no non-enum HarnessToolCallDenied rows "
        f"in the last 3 days. ({len(unresolved)} unresolved dynamic "
        "expressions noted but not failing.)"
        if unresolved
        else (
            "All emit_denial_event(outcome=...) literals resolved to "
            "members of OUTCOMES; no non-enum HarnessToolCallDenied "
            "rows in the last 3 days."
        )
    )
    rec.record(f"HC-{HC_ID}", HC_NAME, "PASS", detail)


__all__ = ["HC_ID", "HC_NAME", "hc_event_outcome_enum_coverage"]
