import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  displaySessionModel,
  REQUESTED_LABEL,
  sessionModelFactTags,
  sessionModelIsRequested,
} from "../../packages/yoke-core/src/yoke_core/ui/static/session_model_display.js";
import {
  sessionCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_sessions.js";
import {
  FakeDocument,
  byClass,
} from "./universe_ui_dom_test_support.mjs";

test("session cards render the stored model name verbatim", () => {
  assert.equal(
    displaySessionModel({
      executor_surface: "cursor-cli",
      model: "cursor-grok-4.6-xhigh",
    }),
    "cursor-grok-4.6-xhigh",
  );
  assert.equal(
    displaySessionModel({ executor: "cursor", model: "cursor-grok-4.6-xhigh" }),
    "cursor-grok-4.6-xhigh",
  );
  assert.equal(
    displaySessionModel({ executor: "codex", model: "gpt-5.6-sol" }),
    "gpt-5.6-sol",
  );
  assert.equal(
    displaySessionModel({ executor: "claude-code", model: "claude-opus-4-8" }),
    "claude-opus-4-8",
  );
  assert.equal(displaySessionModel({ model: "" }), "model not reported");
  assert.equal(displaySessionModel({}, "—"), "—");
});

test("a served model hides the requested name and is not labelled as an ask", () => {
  assert.equal(
    displaySessionModel({
      model: "claude-opus-5",
      requested_model: "claude-opus-5[1m]",
    }),
    "claude-opus-5",
  );
  assert.equal(
    sessionModelIsRequested({
      model: "claude-opus-5",
      requested_model: "claude-opus-5[1m]",
    }),
    false,
  );
});

test("an unattested model renders the labelled ask", () => {
  assert.equal(
    displaySessionModel({ requested_model: "claude-opus-5[1m]" }),
    `claude-opus-5[1m]${REQUESTED_LABEL}`,
  );
  assert.equal(
    sessionModelIsRequested({ requested_model: "claude-opus-5[1m]" }),
    true,
  );
  assert.equal(sessionModelIsRequested({}), false);
});

test("session model facts show served values and hide a matching request", () => {
  assert.deepEqual(
    sessionModelFactTags({
      reasoning_effort: "max",
      context_window_tokens: 258_400,
      requested_reasoning_effort: "low",
      requested_context_window_tokens: 8_192,
    }),
    [
      { kind: "reasoning-effort", label: "MAX", requested: false },
      { kind: "context-window", label: "258k", requested: false },
    ],
  );
  assert.deepEqual(
    sessionModelFactTags({ reasoning_effort: "xhigh" }),
    [{ kind: "reasoning-effort", label: "XHIGH", requested: false }],
  );
});

test("requested-only facts render labelled; both-null renders nothing", () => {
  assert.deepEqual(
    sessionModelFactTags({
      reasoning_effort: null,
      context_window_tokens: null,
      requested_reasoning_effort: "high",
      requested_context_window_tokens: 1_000_000,
    }),
    [
      {
        kind: "reasoning-effort",
        label: `HIGH${REQUESTED_LABEL}`,
        requested: true,
      },
      {
        kind: "context-window",
        label: `1m${REQUESTED_LABEL}`,
        requested: true,
      },
    ],
  );
  assert.deepEqual(
    sessionModelFactTags({
      reasoning_effort: null,
      context_window_tokens: null,
      requested_reasoning_effort: null,
      requested_context_window_tokens: null,
    }),
    [],
  );
});

test("a served effort sits beside a requested-only context tag", () => {
  assert.deepEqual(
    sessionModelFactTags({
      reasoning_effort: "high",
      requested_context_window_tokens: 1_000_000,
    }),
    [
      { kind: "reasoning-effort", label: "HIGH", requested: false },
      {
        kind: "context-window",
        label: `1m${REQUESTED_LABEL}`,
        requested: true,
      },
    ],
  );
});

test("session cards paint requested facts in the labelled tag style", () => {
  const card = sessionCard(new FakeDocument(), {
    session_id: "session-1",
    liveness: "active",
    executor: "claude-code",
    requested_model: "claude-opus-5[1m]",
    reasoning_effort: "high",
    requested_context_window_tokens: 1_000_000,
    claims: [],
  }, () => {});
  assert.equal(
    byClass(card, "session-model")[0].textContent,
    `claude-opus-5[1m]${REQUESTED_LABEL}`,
  );
  assert.ok(byClass(card, "session-model")[0].className.includes("is-requested"));
  assert.deepEqual(
    byClass(card, "session-model-tag").map(
      (tag) => [
        tag.textContent,
        tag.getAttribute("data-model-fact"),
        tag.className.includes("is-requested"),
      ],
    ),
    [
      ["HIGH", "reasoning-effort", false],
      [`1m${REQUESTED_LABEL}`, "context-window", true],
    ],
  );
});

test("session model facts stay on the compact model line", () => {
  const css = readFileSync(new URL(
    "../../packages/yoke-core/src/yoke_core/ui/static/universe_sessions.css",
    import.meta.url,
  ), "utf8");
  assert.match(
    css,
    /\.session-model-line \{[^}]*display: flex;[^}]*white-space: nowrap;/,
  );
  assert.match(css, /\.session-model-tag \{[^}]*padding: 1px 5px;/);
  assert.match(
    css,
    /\.session-model-tag\.is-requested \{[^}]*border: 1px dashed/,
  );
});
