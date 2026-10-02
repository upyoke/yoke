import assert from "node:assert/strict";
import test from "node:test";

import {
  renderMachinesPanel,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_machines_panel.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";

// The guidance each reason class earns, as the server composes it beside the
// window. The card draws what it is given and adds no advice of its own.
const CREDENTIAL =
  "the CLI's stored sign-in is missing or was rejected by the vendor; "
  + "re-authenticate the CLI on that machine";
const THROTTLED =
  "the vendor throttled the limits check; the surface is not known to be "
  + "signed out; it retries on the next refresh";
const READ_FAILED = "the limits read failed; it retries on the next refresh";

function unreadableWindow(reason, guidance) {
  const window = {
    status: "unknown",
    window_kind: "unknown",
    scope: "all",
    meter: "unknown",
    remaining_percent: null,
    resets_at: null,
    reason,
  };
  if (guidance !== undefined) window.guidance = guidance;
  return window;
}

function noteFor(window) {
  const documentNode = new FakeDocument();
  const host = documentNode.createElement("div");
  renderMachinesPanel({ document: documentNode }, host, [{
    machine_id: "machine-1",
    hostname: "laptop",
    state: "active",
    liveness: "connected",
    last_seen_at: new Date().toISOString(),
    surface_versions: { "claude-cli": "2.1" },
    surface_policies: [],
    capacity: { live_lanes: 0, max_worker_lanes: 4, summary: "lanes 0/4" },
    plan_limits: {
      "claude-cli": {
        plan_tier: null,
        observed_at: new Date().toISOString(),
        windows: [window],
      },
    },
  }], {});
  const notes = byClass(host, "machine-limit-note");
  assert.equal(notes.length, 1);
  assert.equal(byClass(host, "machine-limit-name")[0].textContent, "no reading");
  return notes[0].textContent;
}

test("a rejected or missing sign-in says to re-authenticate the CLI", () => {
  assert.equal(
    noteFor(unreadableWindow("stale_credential", CREDENTIAL)),
    `stale_credential — ${CREDENTIAL}`,
  );
});

test("a throttled read says it was throttled and never to sign in again", () => {
  const note = noteFor(unreadableWindow("http_429", THROTTLED));
  assert.equal(note, `http_429 — ${THROTTLED}`);
  assert.doesNotMatch(note, /re-authenticate/);
  assert.doesNotMatch(note, /launches still attempt and fail/);
});

test("another http code and a failed read say the read failed and retries", () => {
  for (const reason of ["http_503", "http_read_failed_TimeoutError"]) {
    const note = noteFor(unreadableWindow(reason, READ_FAILED));
    assert.equal(note, `${reason} — ${READ_FAILED}`);
    assert.doesNotMatch(note, /re-authenticate/);
    assert.doesNotMatch(note, /launches/);
  }
});

test("a window served without guidance shows its reason and no advice", () => {
  assert.equal(noteFor(unreadableWindow("http_429")), "http_429");
});
