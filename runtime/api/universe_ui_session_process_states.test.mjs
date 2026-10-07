import assert from "node:assert/strict";
import test from "node:test";

import {
  sessionHealthState,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_diagnostics.js";

// A recorded native exit is not a dead worker: a headless worker's process
// exits between turns and the next message resumes it from its transcript.
// The card names which state a claim holder is in and never offers
// termination for one a message would bring back.

function holder(nativeProcess) {
  return {
    session_id: "session-1",
    liveness: "active",
    executor: "claude-code",
    claims: [{ target_kind: "item", target: "YOK-1" }],
    activity_at: "2026-08-22T11:00:00Z",
    stale_eligible_at: "2026-08-22T12:30:00Z",
    native_process: nativeProcess,
  };
}

const NOW = Date.parse("2026-08-22T12:00:00Z");

test("an exited worker a message resumes reads exited, never terminate", () => {
  const exited = sessionHealthState(holder({
    state: "gone",
    observed_at: "2026-08-22T11:59:00Z",
    resumable_from_transcript: true,
  }), NOW);
  assert.equal(exited.state, "process-exited");
  assert.match(exited.detail, /message it to resume from transcript/);
  assert.doesNotMatch(exited.detail, /terminate/);

  const resuming = sessionHealthState(holder({
    state: "resuming",
    observed_at: "2026-08-22T11:50:00Z",
    resume_started_at: "2026-08-22T11:59:00Z",
  }), NOW);
  assert.equal(resuming.state, "resuming");
  assert.doesNotMatch(resuming.detail, /terminate/);
});

test("an exit no message can resume keeps the deliberate-terminate wording", () => {
  const gone = sessionHealthState(holder({
    state: "gone",
    observed_at: "2026-08-22T11:59:00Z",
    resumable_from_transcript: false,
  }), NOW);
  assert.equal(gone.state, "process-gone");
  assert.match(gone.detail, /cannot resume by message/);
});
