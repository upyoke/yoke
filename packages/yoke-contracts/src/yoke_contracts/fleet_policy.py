"""Fleet timing and message limits shared by every universe and machine.

These are product policy, not organization settings. Add configuration only
when a work item identifies the person who needs to change a value.
"""

WAKE_AFTER_IDLE_SECONDS = 60
WAKE_ACK_GRACE_SECONDS = 300
STALE_ALIVE_PROBE_SECONDS = 900
MESSAGE_EXPIRY_HOURS = 24
MAX_WAKE_ATTEMPTS = 3
MAX_BODY_BYTES = 16384
BROADCAST_REQUIRES_CONFIRMATION = True
SURFACE_FALLBACK = False
LAUNCH_DEADLINE_MINUTES = 10
RELAY_POLL_SECONDS = 60
RELAY_IDLE_AFTER_MINUTES = 60
RELAY_IDLE_POLL_MINUTES = 5
