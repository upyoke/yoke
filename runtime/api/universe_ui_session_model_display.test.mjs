import assert from "node:assert/strict";
import test from "node:test";

import { displaySessionModel } from "../../packages/yoke-core/src/yoke_core/ui/static/session_model_display.js";

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
