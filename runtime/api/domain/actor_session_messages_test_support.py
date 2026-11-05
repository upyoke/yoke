# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from yoke_contracts.session_control.sender_surface import CLI_SENDER_SURFACE

from yoke_core.domain.actor_message_recipients import inbox_actor_messages

from yoke_core.domain.actor_permissions import (
    ROLE_OPERATOR,
    ROLE_VIEWER,
    grant_actor_org_role,
)

from yoke_core.domain.session_message_receipts import (
    acknowledge_actor_message,
    acknowledge_message,
)

from yoke_core.domain.session_message_service import preview_message, send_message

from yoke_core.domain.session_message_types import SessionMessageError

from runtime.api.domain.session_message_support_test_support import (
    NOW,
    message_connection,
    selector,
)


def _members():
    conn = message_connection()
    grant_actor_org_role(conn, actor_id=10, org_id=1, role_name=ROLE_OPERATOR)
    grant_actor_org_role(conn, actor_id=11, org_id=1, role_name=ROLE_VIEWER)
    conn.commit()
    return conn
