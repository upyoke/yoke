import assert from "node:assert/strict";
import test from "node:test";

import { renderTestMachineDetail } from
  "../../packages/yoke-core/src/yoke_core/ui/static/universe_view_test_machine.js";
import { machineSecretState } from
  "../../packages/yoke-core/src/yoke_core/ui/static/test_machine_settings_dialog.js";
import { allNodes, byClass } from "./universe_ui_dom_test_support.mjs";
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

test("desktop registration shows its route and secret reference without a value", async () => {
  const machine = structuredClone(detail);
  Object.assign(machine.settings, {
    desktop_route: "ssh-forward", desktop_protocol: "rdp",
    desktop_port: "3389", desktop_user: "Administrator",
    cloud_instance_id: "i-07b658cc018669344",
  });
  machine.secrets.push({ key: "desktop_password", cap_type: machine.capability_type, stored: null });
  const prepared = context([machine]);
  const main = prepared.documentNode.createElement("main");
  await renderTestMachineDetail(prepared.value, main, "yoke");
  assert.match(text(main), /rdp · ssh-forward · 127.0.0.1:3389 · Administrator/);
  assert.match(text(main), /i-07b658cc018669344/);
  const credential = byClass(main, "test-machine-secret").find(node => /desktop_password/.test(text(node)));
  assert.match(text(credential), /unknown on this browser/);
});

test("saving machine settings preserves optional desktop and browser baseline declarations", async () => {
  const machine = structuredClone(detail);
  Object.assign(machine.settings, {
    desktop_route: "direct", desktop_protocol: "vnc", desktop_port: "5900",
    desktop_user: "testy", browser_profile_baseline_path: "/Users/Shared/golden/profile",
  });
  const prepared = context([machine]);
  const main = prepared.documentNode.createElement("main");
  await renderTestMachineDetail(prepared.value, main, "yoke");
  allNodes(main).find(node => node.textContent === "Edit settings").dispatchEvent(new Event("click"));
  allNodes(main).find(node => node.textContent === "Save non-secret settings").dispatchEvent(new Event("click"));
  await new Promise(resolve => setImmediate(resolve));
  const write = prepared.requests.find(request => request.function === "test_machine.settings_replace");
  assert.deepEqual(write.payload.settings, machine.settings);
});
