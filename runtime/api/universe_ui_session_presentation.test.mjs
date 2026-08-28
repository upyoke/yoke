import assert from "node:assert/strict";
import test from "node:test";

import {
  presentationLabel,
  remotePresentationCount,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_session_presentation.js";


test("session presentation reports attachment without inventing a frontend", () => {
  const attached = {
    presentation_state: "attached",
    presentation_surface: "remote-control",
    presentation_mode: "bidirectional",
  };
  assert.equal(presentationLabel(attached), "Remote Control · bidirectional");
  assert.equal(presentationLabel({ presentation_state: "not-attached" }), "local only");
  assert.equal(presentationLabel({}), "");
  assert.equal(remotePresentationCount([attached, {}, attached]), 2);
});
