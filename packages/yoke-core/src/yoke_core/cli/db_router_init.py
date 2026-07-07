"""Schema/domain bootstrap and missing-schema remediation for db_router.

Owns the explicit-bootstrap contract: ambient schema creation runs only
when an operator invokes ``db_router init`` or sets
``YOKE_DB_INIT_ALLOW=1``. Normal runtime commands resolve authority
and refuse with a concrete remediation message rather than silently
emitting ``CREATE TABLE`` as a side effect.

Also owns the small ``items get ... body --section "## Heading"``
dispatch helper. Sibling-file placement keeps :mod:`db_router` under
the 350-line authored-file cap.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import os
import sys
from pathlib import Path
from typing import List, Optional


#: Auto-init dispatch order — canonically owned by the environment
#: bootstrap module (the loud production form for empty-env init); this
#: alias keeps db_router's opportunistic auto-init on the same chain.
from yoke_core.domain.environment_bootstrap import (
    INIT_MODULE_CHAIN as _AUTO_INIT_MODULES,
)


#: Env flag used to opt a process into ambient bootstrap (tests,
#: interactive DB provisioning, cross-worktree setup).  Callers that set
#: this explicitly acknowledge that running the full init module chain
#: is intentional for this process.
_INIT_ALLOW_ENV = "YOKE_DB_INIT_ALLOW"

#: Idempotency marker — once set, every later call in this process
#: short-circuits init.  Not a contract for "init already ran"; it's
#: "someone asked for init to be treated as done."
_INIT_DONE_ENV = "YOKE_DB_INIT_DONE"


def _connected_postgres_authority_active(repo_root: Path) -> bool:
    """Return True when the checkout binding selects ambient Postgres."""
    from yoke_core.domain import db_backend, yoke_connected_env

    return (
        yoke_connected_env.connected_backend(start=repo_root)
        == db_backend.POSTGRES
    )


def _init_allowed() -> bool:
    """Return True when ambient bootstrap is explicitly opted into."""
    return os.environ.get(_INIT_ALLOW_ENV) == "1"


def _run_init_modules(repo_root: Path) -> None:
    """Run the full schema/domain bootstrap module chain.

    Called only when init is explicitly requested — by the ``init``
    subcommand or ``YOKE_DB_INIT_ALLOW=1``.  Never triggered by
    normal runtime commands.
    """
    try:
        from yoke_core.domain.schema import _check_sibling_state_collision, _resolve_db_root
        _resolved_root = _resolve_db_root()
        if _check_sibling_state_collision(_resolved_root):
            sibling_hint = "yoke/" if Path(_resolved_root).name == "data" else "data/"
            print(
                f"Warning: auto-init skipped — sibling-state collision detected. "
                f"Resolved state dir '{_resolved_root}' does not exist, but a live "
                f"yoke.db was found in sibling '{sibling_hint}'.",
                file=sys.stderr,
            )
            os.environ[_INIT_DONE_ENV] = "1"
            return
    except (ImportError, Exception):
        pass

    root_str = str(repo_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)

    devnull = io.StringIO()
    for modname in _AUTO_INIT_MODULES:
        try:
            mod = importlib.import_module(modname)
            try:
                with contextlib.redirect_stdout(devnull), contextlib.redirect_stderr(devnull):
                    mod.main(["init"])
            except SystemExit:
                pass
            except Exception:
                pass
        except Exception:
            pass

    os.environ[_INIT_DONE_ENV] = "1"


def _probe_schema_or_remediate(argv: List[str]) -> Optional[int]:
    """Return a non-zero exit code and print remediation when the DB is
    present but missing baseline schema.

    Runs only for runtime commands — never for ``init`` (which
    intentionally bootstraps) or ``help`` (which needs no DB).  The
    probe short-circuits when ``YOKE_DB_INIT_ALLOW=1`` is set because
    that process has already been granted bootstrap authority; the
    bootstrap path will create the missing tables itself.
    """
    if not argv:
        return None
    domain = argv[0]
    if domain in ("init", "help"):
        return None
    if _init_allowed():
        return None
    try:
        from yoke_core.domain import db_backend

        db_backend.resolve_pg_dsn()
        return None
    except Exception as exc:  # noqa: BLE001 - explicit authority diagnostic
        print(
            f"Error: backend authority resolution failed: {exc}",
            file=sys.stderr,
        )
        return 1


def _dispatch_items_get_section(item_args: List[str]) -> int:
    """Handle ``items get <id> <field> --section "<heading>"``.

    Routes the ``body`` field to :func:`render_body.render_section` so
    callers do not load the 25k-token full body when they only want one
    section. For stored structured text fields (``spec``, ``technical_plan``,
    etc.) reads the field directly and reuses
    :func:`render_body_section.extract_section`. Prints a usage error
    when ``--section`` is supplied without a value, with an unknown
    field, or with a scalar field that has no section structure.
    """
    if len(item_args) < 2:
        print(
            "Usage: items get <item-id> <field> --section \"## Heading\"",
            file=sys.stderr,
        )
        return 2
    item_id_raw, field = item_args[0], item_args[1]
    section: Optional[str] = None
    project: Optional[str] = None
    rest = list(item_args[2:])
    idx = 0
    while idx < len(rest):
        tok = rest[idx]
        if tok == "--section":
            if idx + 1 >= len(rest):
                print(
                    "Error: --section requires a heading argument",
                    file=sys.stderr,
                )
                return 2
            section = rest[idx + 1]
            idx += 2
            continue
        if tok == "--project":
            if idx + 1 >= len(rest):
                print(
                    "Error: --project requires a project slug",
                    file=sys.stderr,
                )
                return 2
            project = rest[idx + 1].strip() or None
            idx += 2
            continue
        print(
            f"Error: unknown argument '{tok}' for items get --section",
            file=sys.stderr,
        )
        return 2
    if not section:
        print(
            "Error: --section requires a heading argument", file=sys.stderr
        )
        return 2
    try:
        from yoke_core.domain.render_body import (
            render_section,
        )
        from yoke_core.api.service_client_items_parsing import (
            _QI_ALL_FIELDS,
            _QI_LARGE_TEXT_FIELDS,
            _QI_VIRTUAL_FIELDS,
        )
        from yoke_cli.commands._helpers import (
            client_project_context,
        )
        from yoke_core.domain.yok_n_parser import parse_item_id

        # db_router is the operator-debug local-postgres surface; local
        # resolution here is sanctioned (the relay-clean path is
        # `yoke items get <ref> <field> --section ...`).
        item_id = parse_item_id(
            item_id_raw,
            project=client_project_context(project),
            allow_bare_internal=False,
        )
    except (ImportError, ValueError):
        print(f"Error: invalid item id '{item_id_raw}'", file=sys.stderr)
        return 2
    if field not in _QI_ALL_FIELDS:
        print(
            f"Error: unknown field '{field}'. Valid: "
            f"{','.join(sorted(_QI_ALL_FIELDS))}",
            file=sys.stderr,
        )
        return 2
    if field in _QI_VIRTUAL_FIELDS:
        return render_section(item_id, section, out=sys.stdout, err=sys.stderr)
    if field in _QI_LARGE_TEXT_FIELDS:
        return _extract_structured_field_section(item_id, field, section)
    print(
        f"Error: --section is only supported on 'body' and structured "
        f"text fields, not scalar field '{field}'",
        file=sys.stderr,
    )
    return 2


def _extract_structured_field_section(
    item_id: int, field: str, section: str
) -> int:
    """Print one ``## <section>`` block from a stored structured field.

    Reuses :func:`render_body_section.extract_section` so the heading
    parser stays in one place. Returns 1 when the item is missing,
    0 otherwise — section absence is advisory on stderr.
    """
    from yoke_core.domain import db_backend
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.render_body_section import extract_section

    conn = connect(None)
    try:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            f"SELECT COALESCE(CAST({field} AS TEXT), '') FROM items "
            f"WHERE id = {p}",
            (item_id,),
        ).fetchone()
        if row is None:
            print(
                f"Error: item YOK-{item_id} not found", file=sys.stderr
            )
            return 1
        text = row[0] if row else ""
        content = extract_section(text, section)
        if content is None:
            print(
                f"Advisory: section '{section}' not found on "
                f"YOK-{item_id} field '{field}'",
                file=sys.stderr,
            )
            return 0
        if content:
            sys.stdout.write(content)
            if not content.endswith("\n"):
                sys.stdout.write("\n")
        return 0
    finally:
        conn.close()
