"""Size the Mac fixture's console display from its signed-in GUI session."""

from yoke_harness.desktop_geometry import (
    MINIMUM_HEIGHT, MINIMUM_RESOLUTION, MINIMUM_WIDTH, is_desktop_resolution,
)
from yoke_harness.ssh_mac_gui_session import run_terminal_app_command

_CHANGE_MODE = r"""
import CoreGraphics
import Foundation

func fail(_ reason: String) -> Never {
    FileHandle.standardError.write(Data(("macos_desktop_resolution_unavailable: " + reason
        + "; select a mode of at least MINIMUM_RESOLUTION in System Settings > Displays, "
        + "or attach a display adapter that offers it, then retry\n").utf8))
    exit(69)
}
let display = CGMainDisplayID()
func largeEnough(_ mode: CGDisplayMode) -> Bool {
    return mode.width >= MINIMUM_WIDTH && mode.height >= MINIMUM_HEIGHT
}
guard var current = CGDisplayCopyDisplayMode(display) else {
    fail("the signed-in console has no display mode")
}
if !largeEnough(current) {
    let modes = CGDisplayCopyAllDisplayModes(display, nil).map { $0 as NSArray as! [CGDisplayMode] } ?? []
    let candidates = modes.filter { $0.isUsableForDesktopGUI() && largeEnough($0) }
    guard let best = candidates.min(by: { $0.width * $0.height < $1.width * $1.height }) else {
        fail("no full-HD mode for the \(current.width)x\(current.height) display")
    }
    var configuration: CGDisplayConfigRef?
    let begin = CGBeginDisplayConfiguration(&configuration)
    guard begin == .success, let configuration = configuration else {
        fail("cannot begin display configuration (Core Graphics status \(begin.rawValue))")
    }
    let change = CGConfigureDisplayWithDisplayMode(configuration, display, best, nil)
    if change != .success {
        CGCancelDisplayConfiguration(configuration)
        fail("cannot stage the full-HD mode (Core Graphics status \(change.rawValue))")
    }
    let commit = CGCompleteDisplayConfiguration(configuration, .forSession)
    guard commit == .success, let observed = CGDisplayCopyDisplayMode(display), largeEnough(observed) else {
        fail("the display did not switch to full HD (Core Graphics status \(commit.rawValue))")
    }
    current = observed
}
print("\(current.width)x\(current.height)")
""".replace("MINIMUM_RESOLUTION", MINIMUM_RESOLUTION).replace(
    "MINIMUM_WIDTH", str(MINIMUM_WIDTH)
).replace("MINIMUM_HEIGHT", str(MINIMUM_HEIGHT))

_ENSURE = "/usr/bin/swift - <<'YOKE_DISPLAY_SWIFT'\n" + _CHANGE_MODE + "YOKE_DISPLAY_SWIFT\n"


def desktop_argv(argv):
    """Ensure geometry in the same GUI context before executing the walker command."""
    command = 'set -e\n{\n' + _ENSURE + '} >&2\nexec "$@"'
    return ("/bin/sh", "-c", command, "yoke-desktop", *argv)


def ensure_mac_desktop(run):
    """Return the resolution measured in the console that Screen Sharing mirrors."""
    result = run_terminal_app_command(
        run, argv=("/bin/sh", "-c", _ENSURE), timeout=45,
    )
    resolution = result.stdout.strip()
    if not result.returncode and is_desktop_resolution(resolution):
        return resolution
    raise RuntimeError(
        f"macos_desktop_resolution_unavailable: {result.stderr.strip() or resolution or 'no display receipt'}; "
        "check the console display and Command Line Tools, then retry"
    )
