"""A sealed native Claude window probe. Screen contents stay on the fixture."""

from __future__ import annotations


_SWIFT = r"""
import AppKit
import CoreGraphics
import Darwin
import Foundation
import Vision

let appPath = "/Applications/Claude.app"
let bundleID = "com.anthropic.claudefordesktop"
let screenshot = URL(fileURLWithPath: CommandLine.arguments[1])

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

func labels(in window: Int) -> (text: Set<String>, sidebar: Set<String>)? {
    try? FileManager.default.removeItem(at: screenshot)
    guard run("/usr/sbin/screencapture", ["-x", "-o", "-l", String(window), screenshot.path])
    else { return nil }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["en-US"]
    let handler = VNImageRequestHandler(url: screenshot, options: [:])
    do { try handler.perform([request]) } catch { return nil }
    let observations = request.results ?? []
    func recognized(_ rows: [VNRecognizedTextObservation]) -> Set<String> {
        Set(rows.compactMap {
            $0.topCandidates(1).first?.string
                .trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        })
    }
    let navigation = observations.filter {
        $0.boundingBox.midX < 0.32 && $0.boundingBox.midY > 0.60
    }
    return (recognized(observations), recognized(navigation))
}

func isSignedInChat(_ sidebar: Set<String>) -> Bool {
    func hasLabel(_ label: String) -> Bool {
        sidebar.contains { $0 == label || $0.hasSuffix(" " + label) }
    }
    // The current desktop renders New, Projects and Artifacts. Vision may
    // include a leading icon glyph in a navigation label.
    return hasLabel("projects") && (
        (hasLabel("new") && hasLabel("artifacts"))
            || (hasLabel("new chat") && hasLabel("chats"))
    )
}

func observe() -> Int32 {
    guard FileManager.default.fileExists(atPath: appPath) else { return 12 }
    guard run("/usr/bin/open", ["-a", appPath]) else { return 11 }
    let deadline = ProcessInfo.processInfo.systemUptime + 35
    var observedWindow = false
    while ProcessInfo.processInfo.systemUptime < deadline {
        if let app = claude(), let window = windowNumber(of: app), let frame = labels(in: window) {
            observedWindow = true
            if frame.text.contains("sign in")
                && !frame.text.isDisjoint(with: ["continue with google", "continue with email"]) {
                return 10
            }
            if frame.text.contains("claude for mac") && frame.text.contains("get started") { return 10 }
            if isSignedInChat(frame.sidebar) { return 0 }
        }
        Thread.sleep(forTimeInterval: 1)
    }
    return observedWindow ? 10 : 13
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
    }}
    sys.exit(0 if probe.returncode == 0 else EXIT[cause.get(probe.returncode, 'probe_launch_failed')])
"""
