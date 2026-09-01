import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  displaySessionModel,
  servedSessionModelFacts,
} from "../../packages/yoke-core/src/yoke_core/ui/static/session_model_display.js";

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

test("session model facts show only provider-attested served values", () => {
  assert.deepEqual(
    servedSessionModelFacts({
      reasoning_effort: "max",
      context_window_tokens: 258_400,
      requested_reasoning_effort: "low",
      requested_context_window_tokens: 8_192,
    }),
    [
      { kind: "reasoning-effort", label: "MAX" },
      { kind: "context-window", label: "258k" },
    ],
  );
  assert.deepEqual(
    servedSessionModelFacts({ reasoning_effort: "xhigh" }),
    [{ kind: "reasoning-effort", label: "XHIGH" }],
  );
  assert.deepEqual(
    servedSessionModelFacts({
      reasoning_effort: null,
      context_window_tokens: null,
      requested_reasoning_effort: "high",
      requested_context_window_tokens: 200_000,
    }),
    [],
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
});
