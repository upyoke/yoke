"""Named upgrade floors for protocol names removed by governed history."""

from importlib import import_module

_HISTORY = "0095_feedback_categories"


def retirement_floor():
    from yoke_contracts.engine_version import advertised_engine_version
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.schema_common import _table_exists
    from yoke_core.domain.project_identity import placeholder
    try:
        with connect() as conn:
            if _table_exists(conn, "applied_migrations"):
                row = conn.execute("SELECT minimum_serving_version FROM applied_migrations "
                    f"WHERE migration_name={placeholder(conn)}", (_HISTORY,)).fetchone()
                if row and row[0]:
                    return str(row[0])
    except Exception:
        pass  # An unavailable ledger cannot turn a removed surface back on.
    module = import_module("yoke_core.domain.migrations." + _HISTORY)
    return advertised_engine_version() or module.MINIMUM_SERVING_VERSION


def retired_surface_reason(kind, name):
    history = import_module("yoke_core.domain.migrations." + _HISTORY)
    if kind == "function":
        names = {family + "." + operation for family, operations in
                 history.RETIRED_FUNCTION_FAMILIES.items() for operation in operations}
    else:
        names = history.RETIRED_HOOKS if kind == "hook" else history.RETIRED_EVENTS
    if name not in names:
        return None
    floor = retirement_floor()
    repair = (f"Run yoke update --version {floor}, then yoke project refresh in "
              "each registered checkout and use the current command from yoke --help.") if floor != "next-release" else (
              "Ask the release operator for the carrying release, then update the CLI and refresh each project.")
    return f"protocol_surface_removed: {kind} {name!r} was removed; required client floor {floor}. {repair}"



def unregistered_function_error(function_id):
    reason = retired_surface_reason("function", function_id)
    return (("function_version_skew", reason) if reason else
            ("function_not_registered", f"function id {function_id!r} is not registered"))
