"""A sealed native Claude window probe. Screen contents stay on the fixture.

The probe passes on any signed-in tab (Chat, Code or Cowork), reports the
first-run and Sign In screens as signed out, and names a window it cannot
classify as an unrecognized layout rather than telling the operator to sign in.
It only launches and quits the app; it never clicks or types.
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
    ["new", "search", "artifacts", "customize"].allSatisfy { hasLabel($0, in: sidebar) }
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
let layoutUnrecognized: Int32 = 14

/// Classify one window frame; nil means no known layout yet, so keep looking.
/// A tab's sidebar markers prove its layout; the account footer or the mode
/// switcher proves the account, so unreadable footer text alone cannot fail it.
func classify(text: Set<String>, sidebar: Set<String>, footer: () -> Set<String>) -> Int32? {
    if isSignedOutScreen(text) { return signedOut }
    guard isChatSidebar(sidebar) || isCodeSidebar(sidebar) || isCoworkSidebar(sidebar)
    else { return nil }
    return hasModeSwitcher(text) || hasAccountFooter(footer()) ? signedIn : nil
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
    guard run("/usr/bin/open", ["-a", appPath]) else { return 11 }
    let deadline = ProcessInfo.processInfo.systemUptime + 35
    var observedWindow = false
    while ProcessInfo.processInfo.systemUptime < deadline {
        if let app = claude(), let window = windowNumber(of: app), let frame = frame(of: window) {
            observedWindow = true
            // A second, cropped pass reads small footer text the full frame missed.
            let outcome = classify(text: frame.text, sidebar: frame.sidebar) {
                frame.footer.union(recognizeText(in: footerRegion).map(recognized) ?? [])
            }
            if let outcome { return outcome }
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
    if stillRunning() { exit(11) }
}
exit(outcome)
"""


CLAUDE_DESKTOP_PROBE_PROGRAM = f"""
import pathlib, subprocess, sys, tempfile
with tempfile.TemporaryDirectory(prefix='yoke-claude-desktop-') as workspace:
    script = pathlib.Path(workspace, 'probe.swift')
    script.write_text({_SWIFT!r}, encoding='utf-8')
    try:
        probe = subprocess.run(
            ['/usr/bin/swift', str(script), str(pathlib.Path(workspace, 'window.png'))],
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
        12: 'probe_executable_missing',
        13: 'probe_request_timed_out',
        14: 'probe_layout_unrecognized',
    }}
    sys.exit(0 if probe.returncode == 0 else EXIT[cause.get(probe.returncode, 'probe_launch_failed')])
"""
