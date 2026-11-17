"""Named upgrade floors for protocol names removed by governed history."""

RETIRED_FUNCTION_FAMILIES = {
    "ouroboros.entry": ("insert", "list", "get"),
    "ouroboros.reflection": ("capture",),
}
RETIRED_HOOKS = ("yoke_core.domain.reflection_capture_hook",)
RETIRED_EVENTS = (
    "ReflectionCaptureHookFired",
    "ReflectionCaptureHookUnhandled",
    "ReflectionCapturePersistFailed",
    "ReflectionMarkerParseFailed",
)

RETIREMENT_FLOOR = "0.2.0.202610291830"


RETIRED_SURFACE_FLOORS = {
    ("function", "test_machine.host_rebind"): "next-release",
    ("event", "test_machine.host_rebound"): "next-release",
}


def retired_surface_reason(kind, name):
    floors = {
        ("function", family + "." + operation): RETIREMENT_FLOOR
        for family, operations in RETIRED_FUNCTION_FAMILIES.items()
        for operation in operations
    }
    floors.update({("hook", name): RETIREMENT_FLOOR for name in RETIRED_HOOKS})
    floors.update({("event", name): RETIREMENT_FLOOR for name in RETIRED_EVENTS})
    floors.update(RETIRED_SURFACE_FLOORS)
    floor = floors.get((kind, name))
    if floor is None:
        return None
    repair = (
        f"Run yoke update --version {floor}, then yoke project refresh in "
        "each registered checkout and use the current command from yoke --help."
    )
    return f"protocol_surface_removed: {kind} {name!r} was removed; required client floor {floor}. {repair}"


def unregistered_function_error(function_id):
    reason = retired_surface_reason("function", function_id)
    return (
        ("function_version_skew", reason)
        if reason
        else (
            "function_not_registered",
            f"function id {function_id!r} is not registered",
        )
    )
