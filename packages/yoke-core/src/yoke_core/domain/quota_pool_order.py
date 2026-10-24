"""Universe-wide consumption order of Cursor's two monthly quota pools.

An absent ``universe_settings`` row reads :data:`DEFAULT_CURSOR_QUOTA_ORDER`.
Use ``yoke settings unset cursor_quota_order`` to follow shipped defaults.
"""

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.session_control.plan_limits import (
    cursor_scope_for_model,
)
from yoke_contracts.settings_catalog import UNIVERSE_SETTING_KEYS
from yoke_contracts.timestamps import utc_now

from yoke_core.domain import json_helper
from yoke_core.domain.db_helpers import instant_parameter
from yoke_core.domain.machine_registry import marker

KEY = "cursor_quota_order"

DEFAULT_CURSOR_QUOTA_ORDER = tuple(UNIVERSE_SETTING_KEYS[KEY].default)


class QuotaPoolOrderError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def validate_cursor_quota_order(pools):
    if (
        not isinstance(pools, list)
        or len(pools) != 2
        or not all(isinstance(pool, str) for pool in pools)
        or set(pools) != set(DEFAULT_CURSOR_QUOTA_ORDER)
    ):
        raise QuotaPoolOrderError(
            "cursor_quota_order_invalid",
            compose_refusal(
                "Use exactly Cursor Models and Other Models, once each.",
                recovery='yoke settings set cursor_quota_order \'["Cursor Models", "Other Models"]\'.',
            ),
        )
    return tuple(pools)


def read_pool_order(conn):
    row = conn.execute(
        f"SELECT value FROM universe_settings WHERE key = {marker(conn)}", (KEY,)
    ).fetchone()
    if row is None:
        return DEFAULT_CURSOR_QUOTA_ORDER
    try:
        return validate_cursor_quota_order(json_helper.loads_text(str(row[0])))
    except (TypeError, ValueError) as exc:
        if isinstance(exc, QuotaPoolOrderError):
            raise
        raise QuotaPoolOrderError(
            "cursor_quota_order_unreadable",
            compose_refusal(
                "Stored Cursor order is invalid JSON.",
                recovery="set a valid order with yoke settings set cursor_quota_order.",
            ),
        ) from exc


def pool_preference(pools, *, model):
    return tuple(pools).index(cursor_scope_for_model(model))


def set_pool_order(conn, *, pools, actor_id=None):
    p = marker(conn)
    if pools is None:
        conn.execute(f"DELETE FROM universe_settings WHERE key={p}", (KEY,))
        conn.commit()
        return DEFAULT_CURSOR_QUOTA_ORDER
    ordered = validate_cursor_quota_order(pools)
    conn.execute(
        "INSERT INTO universe_settings (key,value,updated_at,updated_by_actor_id) "
        f"VALUES ({p},{p},{p},{p}) ON CONFLICT (key) DO UPDATE SET "
        "value=excluded.value,updated_at=excluded.updated_at,updated_by_actor_id=excluded.updated_by_actor_id",
        (
            KEY,
            json_helper.dumps_compact(list(ordered)),
            instant_parameter(conn, utc_now()),
            actor_id,
        ),
    )
    conn.commit()
    return ordered
