"""Conservative settled agent-message and launch graph cleanup."""

from datetime import timedelta

from yoke_core.domain.retention_table_policies import Cleanup


def agent_origin(alias):
    # A human owning the sending harness is not human authorship. Legacy
    # NULL origins stay protected; direct CLI/dashboard authorship stays too.
    return f"({alias}.sender_surface='harness_session' AND {alias}.sender_session_id IS NOT NULL)"


def policies(policy, cutoff):
    message_cutoff = cutoff - timedelta(days=policy.windows["agent_messages"])
    launch_cutoff = cutoff - timedelta(days=policy.windows["launches"])
    message_where = (
        f"{agent_origin('t')} AND t.created_at<%s "
        "AND NOT EXISTS (SELECT 1 FROM actor_message_recipients a WHERE a.message_id=t.message_id) "
        "AND NOT EXISTS (SELECT 1 FROM session_launches l WHERE l.message_id=t.message_id) "
        "AND NOT EXISTS (SELECT 1 FROM session_message_recipients r WHERE r.message_id=t.message_id AND ("
        "r.state NOT IN ('acknowledged','cancelled','expired') OR "
        "COALESCE(r.acknowledged_at,r.cancelled_at,r.expired_at)>=%s OR "
        "COALESCE(r.acknowledged_at,r.cancelled_at,r.expired_at) IS NULL OR "
        "r.injection_lease_id IS NOT NULL)) "
        "AND NOT EXISTS (SELECT 1 FROM session_message_attempts a WHERE a.message_id=t.message_id "
        "AND (a.completed_at IS NULL OR a.completed_at>=%s)) "
        "AND EXISTS (SELECT 1 FROM harness_sessions s WHERE s.session_id=t.sender_session_id AND s.ended_at<%s) "
        "AND NOT EXISTS (SELECT 1 FROM session_message_recipients r JOIN work_claims w ON w.session_id=r.session_id "
        "WHERE r.message_id=t.message_id AND w.released_at IS NULL) "
        "AND NOT EXISTS (SELECT 1 FROM work_claims w WHERE w.session_id=t.sender_session_id AND w.released_at IS NULL)"
    )
    messages = Cleanup(
        "session_messages",
        ("message_id",),
        message_where,
        (message_cutoff,) * 4,
        children=(
            ("session_message_attempts", "message_id", "message_id"),
            ("session_message_recipients", "message_id", "message_id"),
        ),
        reason="human/uncertain origins, actor recipients, references, live holds and unsettled graphs are protected",
    )
    launches = Cleanup(
        "session_launches",
        ("launch_id",),
        "t.state IN ('succeeded','cancelled') AND t.completed_at<%s "
        "AND EXISTS (SELECT 1 FROM session_messages m WHERE m.message_id=t.message_id AND "
        f"{agent_origin('m')} AND NOT EXISTS (SELECT 1 FROM actor_message_recipients a WHERE a.message_id=m.message_id)) "
        "AND NOT EXISTS (SELECT 1 FROM session_termination_reaps r WHERE r.launch_id=t.launch_id) "
        "AND NOT EXISTS (SELECT 1 FROM session_message_recipients r WHERE r.message_id=t.message_id AND (r.state NOT IN ('acknowledged','cancelled','expired') OR COALESCE(r.acknowledged_at,r.cancelled_at,r.expired_at) IS NULL OR COALESCE(r.acknowledged_at,r.cancelled_at,r.expired_at)>=%s OR r.injection_lease_id IS NOT NULL)) "
        "AND NOT EXISTS (SELECT 1 FROM session_message_attempts a WHERE a.message_id=t.message_id AND (a.completed_at IS NULL OR a.completed_at>=%s)) "
        "AND NOT EXISTS (SELECT 1 FROM session_launch_attempts a WHERE a.launch_id=t.launch_id AND (a.completed_at IS NULL OR a.completed_at>=%s)) "
        "AND (t.registered_session_id IS NULL OR EXISTS (SELECT 1 FROM harness_sessions s WHERE s.session_id=t.registered_session_id AND s.ended_at<%s)) "
        "AND (t.requester_session_id IS NULL OR EXISTS (SELECT 1 FROM harness_sessions s WHERE s.session_id=t.requester_session_id AND s.ended_at<%s)) "
        "AND NOT EXISTS (SELECT 1 FROM work_claims w WHERE w.session_id IN (t.requester_session_id,t.registered_session_id) AND w.released_at IS NULL)",
        (launch_cutoff,) * 6,
        children=(("session_launch_attempts", "launch_id", "launch_id"),),
        reason="human graphs, live references and failed/expired/unknown launches stay actionable and protected",
    )
    # Launches first; a settled message becomes unreferenced on the next pass.
    return [launches, messages]
