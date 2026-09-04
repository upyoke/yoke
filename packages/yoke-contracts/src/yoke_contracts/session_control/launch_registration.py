"""Shared result and evidence names for launch-registration correlation."""

BACKGROUND_IDENTITY_MISSING_CODE = "background_identity_missing"
IDENTITY_LISTING_FAILED_CODE = "identity_listing_failed"
IDENTITY_LISTING_LAGGED_CODE = "identity_listing_lagged"
IDENTITY_LISTING_RESOLVED_CODE = "identity_listing_resolved"
IDENTITY_REGISTRATION_WAIT_CODE = "identity_registration_wait"
LAUNCH_ADAPTER_STARTED_CODE = "adapter_started"
# The native the relay started is gone and no session ever registered for
# it. Named separately from the registration deadline because the machine
# that started the native observed the exit, rather than the control plane
# waiting out a silence it could not explain.
NATIVE_EXITED_UNREGISTERED_CODE = "native_exited_unregistered"
REGISTERED_BUT_UNBOUND_CODE = "registered_but_unbound"
REGISTERED_SESSION_INVALID_CODE = "registered_session_invalid"
REGISTRATION_AMBIGUOUS_CODE = "registration_ambiguous"
SPAWN_WORKSPACE_MISSING_CODE = "spawn_workspace_missing"

NATIVE_LAUNCH_WORKSPACE_FIELD = "native_launch_workspace"
LAUNCH_DELIVERY_PENDING_STATUS = "launch_delivery_pending"


__all__ = [
    "BACKGROUND_IDENTITY_MISSING_CODE",
    "IDENTITY_LISTING_FAILED_CODE",
    "IDENTITY_LISTING_LAGGED_CODE",
    "IDENTITY_LISTING_RESOLVED_CODE",
    "IDENTITY_REGISTRATION_WAIT_CODE",
    "LAUNCH_ADAPTER_STARTED_CODE",
    "LAUNCH_DELIVERY_PENDING_STATUS",
    "NATIVE_EXITED_UNREGISTERED_CODE",
    "NATIVE_LAUNCH_WORKSPACE_FIELD",
    "REGISTERED_BUT_UNBOUND_CODE",
    "REGISTERED_SESSION_INVALID_CODE",
    "REGISTRATION_AMBIGUOUS_CODE",
    "SPAWN_WORKSPACE_MISSING_CODE",
]
