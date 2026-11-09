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


def retirement_floor():
    return RETIREMENT_FLOOR


def retired_surface_reason(kind, name):
    if kind == "function":
        names = {
            family + "." + operation
            for family, operations in RETIRED_FUNCTION_FAMILIES.items()
            for operation in operations
        }
    else:
        names = RETIRED_HOOKS if kind == "hook" else RETIRED_EVENTS
    if name not in names:
        return None
    floor = retirement_floor()
    repair = (
        (
            f"Run yoke update --version {floor}, then yoke project refresh in "
            "each registered checkout and use the current command from yoke --help."
        )
        if floor != "next-release"
        else (
            "Ask the release operator for the carrying release, then update the CLI and refresh each project."
        )
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
