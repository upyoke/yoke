"""A sealed native Claude window probe. Screen contents stay on the fixture.

The signed-in decision rests on the app's own authenticated state: an unexpired
claude.ai `sessionKey` cookie in the app's cookie store, read by name and expiry
only, never by value. With that session the probe passes once the window has
rendered and stayed off the first-run and Sign In screens for a settle period,
whatever the sidebar says, so an app update that renames sidebar text cannot
fail it. Without a readable session it falls back to sidebar OCR markers. The
first-run and Sign In screens are signed out either way, and a session dropped
while the app ran fails after quit. A window neither path classifies is an
unrecognized layout, not a reason to sign in again.

It only launches and quits the app; it never clicks or types. An `open` that
fails and an app that will not quit afterwards each exit with their own code:
a quit held open by a sheet means a previous session left the app running, not
that the app needs reinstalling.
"""

from __future__ import annotations


_AUTHENTICATION_SWIFT = r"""
func hasLabel(_ label: String, in labels: Set<String>) -> Bool {
    labels.contains { $0 == label || $0.hasSuffix(" " + label) }
}

func hasWord(_ word: String, in labels: Set<String>) -> Bool {
    labels.contains {
        $0.range(of: "\\b" + word + "\\b", options: [.regularExpression, .caseInsensitive]) != nil
    }
}

func isChatSidebar(_ sidebar: Set<String>) -> Bool {
    // Vision may include a leading icon glyph in a navigation label.
    hasLabel("projects", in: sidebar) && (
        (hasLabel("new", in: sidebar) && hasLabel("artifacts", in: sidebar))
            || (hasLabel("new chat", in: sidebar) && hasLabel("chats", in: sidebar))
    )
}

func isCodeSidebar(_ sidebar: Set<String>) -> Bool {
    // 6.6395.1 renamed the Code tab's Customize entry to Plugins; neither is required.
    ["new", "search", "artifacts"].allSatisfy { hasLabel($0, in: sidebar) }
}

func isCoworkSidebar(_ sidebar: Set<String>) -> Bool {
    hasLabel("new task", in: sidebar)
}

func hasModeSwitcher(_ text: Set<String>) -> Bool {
    // The Chat, Cowork and Code switcher renders only inside the signed-in app.
    ["chat", "cowork", "code"].allSatisfy { hasWord($0, in: text) }
}

func hasAccountFooter(_ footer: Set<String>) -> Bool {
    // Vision reads the account name and plan on one line, followed by the menu
    // chevron. Check the account/plan separator without assuming a user's name.
    let accountWithPlan = #"\p{L}[^\n]*\s*[·•]\s*(free|pro|max|ultra|team|enterprise)\b"#
    return footer.contains {
        $0.range(of: accountWithPlan, options: [.regularExpression, .caseInsensitive]) != nil
    }
}

func isSignedOutScreen(_ text: Set<String>) -> Bool {
    let signIn = text.contains("sign in")
        && !text.isDisjoint(with: ["continue with google", "continue with email"])
    let firstRun = text.contains("claude for mac") && text.contains("get started")
    return signIn || firstRun
}

let signedIn: Int32 = 0
let signedOut: Int32 = 10
let openFailed: Int32 = 11
let layoutUnrecognized: Int32 = 14
let quitBlocked: Int32 = 15
/// A signed-in verdict must hold this long, so a stored session the server has
/// revoked gets time to redirect to the Sign In screen first.
let settleSeconds: Double = 5

/// A loading window shows placeholder shapes; a rendered one shows text.
func isRendered(_ text: Set<String>) -> Bool { text.count >= 3 }

/// Classify one window frame; nil means no known layout yet, so keep looking.
/// The first-run and Sign In screens are signed out whatever else holds. With
/// the app's stored session, any other rendered window is signed in. Without
/// it, a tab's sidebar markers prove its layout and the account footer or the
/// mode switcher proves the account, so unreadable footer text cannot fail it.
func classify(
    session: Bool, text: Set<String>, sidebar: Set<String>, footer: () -> Set<String>
) -> Int32? {
    if isSignedOutScreen(text) { return signedOut }
    if session { return isRendered(text) ? signedIn : nil }
    guard isChatSidebar(sidebar) || isCodeSidebar(sidebar) || isCoworkSidebar(sidebar)
    else { return nil }
    return hasModeSwitcher(text) || hasAccountFooter(footer()) ? signedIn : nil
}

/// Folds frame verdicts over time: signed out ends at once, signed in only
/// after it held for the settle period, and anything else restarts the wait.
struct Verdicts {
    var signedInSince: Double? = nil
    mutating func add(_ outcome: Int32?, at now: Double) -> Int32? {
        guard outcome == signedIn else {
            signedInSince = nil
            return outcome
        }
        let since = signedInSince ?? now
        signedInSince = since
        return now - since >= settleSeconds ? signedIn : nil
    }
}
"""


_SWIFT = r"""
import AppKit
import CoreGraphics
import Darwin
import Foundation
import Vision

let appPath = "/Applications/Claude.app"
let bundleID = "com.anthropic.claudefordesktop"
let screenshot = URL(fileURLWithPath: CommandLine.arguments[1])
let session = CommandLine.arguments[2] == "session"
// The account footer sits at the bottom of the sidebar on every tab.
let footerRegion = CGRect(x: 0, y: 0, width: 0.32, height: 0.12)

func run(_ executable: String, _ arguments: [String]) -> Bool {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: executable)
    process.arguments = arguments
    process.standardOutput = FileHandle.nullDevice
    process.standardError = FileHandle.nullDevice
    do { try process.run() } catch { return false }
    process.waitUntilExit()
    return process.terminationStatus == 0
}

func claude() -> NSRunningApplication? {
    NSRunningApplication.runningApplications(withBundleIdentifier: bundleID).first {
        $0.bundleURL?.path == appPath && !$0.isTerminated
    }
}

func windowNumber(of app: NSRunningApplication) -> Int? {
    let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
    let windows = CGWindowListCopyWindowInfo(options, kCGNullWindowID)
        as? [[String: Any]] ?? []
    return windows.first {
        ($0[kCGWindowOwnerPID as String] as? Int32) == app.processIdentifier
            && ($0[kCGWindowLayer as String] as? Int) == 0
    }?[kCGWindowNumber as String] as? Int
}

struct Frame {
    let text: Set<String>
    let sidebar: Set<String>
    let footer: Set<String>
}

func frame(of window: Int) -> Frame? {
    try? FileManager.default.removeItem(at: screenshot)
    guard run("/usr/sbin/screencapture", ["-x", "-o", "-l", String(window), screenshot.path])
    else { return nil }
    guard let observations = recognizeText() else { return nil }
    let navigation = observations.filter {
        $0.boundingBox.midX < 0.32 && $0.boundingBox.midY > 0.60
    }
    let footer = observations.filter {
        $0.boundingBox.midX < 0.32 && $0.boundingBox.midY < footerRegion.height
    }
    return Frame(
        text: recognized(observations), sidebar: recognized(navigation), footer: recognized(footer)
    )
}

func recognizeText(in region: CGRect = CGRect(x: 0, y: 0, width: 1, height: 1))
    -> [VNRecognizedTextObservation]? {
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["en-US"]
    request.regionOfInterest = region
    let handler = VNImageRequestHandler(url: screenshot, options: [:])
    do { try handler.perform([request]) } catch { return nil }
    return request.results
}

func recognized(_ rows: [VNRecognizedTextObservation]) -> Set<String> {
    Set(rows.compactMap {
        $0.topCandidates(1).first?.string
            .trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    })
}
""" + _AUTHENTICATION_SWIFT + r"""

func observe() -> Int32 {
    guard FileManager.default.fileExists(atPath: appPath) else { return 12 }
    guard run("/usr/bin/open", ["-a", appPath]) else { return openFailed }
    let deadline = ProcessInfo.processInfo.systemUptime + 35
    var observedWindow = false
    var verdicts = Verdicts()
    while ProcessInfo.processInfo.systemUptime < deadline {
        if let app = claude(), let window = windowNumber(of: app), let frame = frame(of: window) {
            observedWindow = true
            // A second, cropped pass reads small footer text the full frame missed.
            let outcome = classify(session: session, text: frame.text, sidebar: frame.sidebar) {
                frame.footer.union(recognizeText(in: footerRegion).map(recognized) ?? [])
            }
            let now = ProcessInfo.processInfo.systemUptime
            if let outcome = verdicts.add(outcome, at: now) { return outcome }
        }
        Thread.sleep(forTimeInterval: 1)
    }
    return observedWindow ? layoutUnrecognized : 13
}

let outcome = observe()
if let app = claude() {
    _ = app.terminate()
    let deadline = ProcessInfo.processInfo.systemUptime + 15
    func stillRunning() -> Bool {
        kill(app.processIdentifier, 0) == 0 || errno != ESRCH
    }
    while stillRunning() && ProcessInfo.processInfo.systemUptime < deadline {
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.2))
    }
    if stillRunning() { exit(quitBlocked) }
}
exit(outcome)
"""


CLAUDE_DESKTOP_PROBE_PROGRAM = f"""
import pathlib, sqlite3, subprocess, sys, tempfile, time
def claude_session():
    # True or False from the app's cookie store; None when it cannot be read.
    # Reads only the cookie's name and expiry, never its value.
    store = pathlib.Path.home() / 'Library/Application Support/Claude/Cookies'
    if not store.exists():
        return False
    try:
        db = sqlite3.connect(store.as_uri() + '?mode=ro', uri=True, timeout=5)
        try:
            rows = db.execute(
                "SELECT expires_utc FROM cookies WHERE name = 'sessionKey'"
                " AND host_key IN ('.claude.ai', 'claude.ai')"
            ).fetchall()
        finally:
            db.close()
    except sqlite3.Error:
        return None
    # Chromium counts microseconds from 1601; zero marks a browser-session cookie.
    now = (time.time() + 11644473600) * 1000000
    return any(expires == 0 or expires > now for (expires,) in rows)
session = claude_session()
with tempfile.TemporaryDirectory(prefix='yoke-claude-desktop-') as workspace:
    script = pathlib.Path(workspace, 'probe.swift')
    script.write_text({_SWIFT!r}, encoding='utf-8')
    try:
        probe = subprocess.run(
            ['/usr/bin/swift', str(script), str(pathlib.Path(workspace, 'window.png')),
             'session' if session else 'no-session'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=100,
        )
    except subprocess.TimeoutExpired:
        sys.exit(EXIT['probe_request_timed_out'])
    except FileNotFoundError:
        sys.exit(EXIT['probe_executable_missing'])
    except OSError:
        sys.exit(EXIT['probe_launch_failed'])
    cause = {{
        10: 'probe_check_unmet',
        11: 'probe_app_open_failed',
        12: 'probe_executable_missing',
        13: 'probe_request_timed_out',
        14: 'probe_layout_unrecognized',
        15: 'probe_app_quit_blocked',
    }}
    if probe.returncode != 0:
        sys.exit(EXIT[cause.get(probe.returncode, 'probe_launch_failed')])
    # The app writes its cookies on quit: a session it dropped while running
    # (a revoked sign-in) means signed out, even if the window looked fine.
    sys.exit(EXIT['probe_check_unmet'] if session and claude_session() is False else 0)
"""
