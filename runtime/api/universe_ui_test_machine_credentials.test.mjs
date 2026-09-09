import assert from "node:assert/strict";
import test from "node:test";

import { renderTestMachineDetail } from
  "../../packages/yoke-core/src/yoke_core/ui/static/universe_view_test_machine.js";
import { machineSecretState } from
  "../../packages/yoke-core/src/yoke_core/ui/static/test_machine_settings_dialog.js";
import { byClass } from "./universe_ui_dom_test_support.mjs";
import {
  context,
  detail,
  text,
} from "./universe_ui_test_machine_test_support.mjs";

test("browser preserves unknown executing-machine credential state", async () => {
  const unknown = structuredClone(detail);
  unknown.secrets = [{
    key: "ssh_private_key",
    stored: null,
    scope: "executing_machine",
  }];
  const prepared = context([unknown]);
  const main = prepared.documentNode.createElement("main");

  await renderTestMachineDetail(prepared.value, main, "yoke");

  const credential = byClass(main, "test-machine-secret")[0];
  assert.match(text(credential), /unknown on this browser/);
  assert.doesNotMatch(text(credential), /missing/);
  assert.match(text(main), /executing-machine presence only/);
});

test("credential state distinguishes stored, missing, and unknown", () => {
  assert.deepEqual(
    machineSecretState({ stored: true }),
    { state: "stored", label: "stored" },
  );
  assert.deepEqual(
    machineSecretState({ stored: false }),
    { state: "missing", label: "missing" },
  );
  assert.deepEqual(
    machineSecretState({ stored: null }),
    { state: "unknown", label: "unknown on this browser" },
  );
});
