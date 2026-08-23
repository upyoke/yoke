import assert from "node:assert/strict";
import test from "node:test";

import {
  waiverDialog,
} from "../../packages/yoke-core/src/yoke_core/ui/static/qa_plan_actions.js";
import {
  machineSettingsDialog,
} from "../../packages/yoke-core/src/yoke_core/ui/static/test_machine_settings_dialog.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function rejectedContext(message) {
  const documentNode = new FakeDocument();
  return {
    documentNode,
    value: {
      document: documentNode,
      client: {
        async call() {
          throw new Error(message);
        },
      },
    },
  };
}

test("a rejected waiver keeps its rationale and restores confirmation", async () => {
  const prepared = rejectedContext("Waiver service is unreachable.");
  const host = prepared.documentNode.createElement("div");
  let reloads = 0;
  const overlay = waiverDialog(
    prepared.value,
    {
      case_key: "checkout-flow",
      last_result: { requirement_id: 32 },
    },
    () => { reloads += 1; },
  );
  host.appendChild(overlay);
  byClass(host, "qa-waiver-rationale")[0].value =
    "Equivalent external proof was reviewed.";
  const confirm = allNodes(host).find(
    (node) => node.tagName === "BUTTON" &&
      node.textContent === "Waive case",
  );

  confirm.dispatchEvent(new Event("click"));
  assert.equal(confirm.disabled, true);
  assert.equal(confirm.textContent, "Waiving…");
  await settle();

  assert.equal(confirm.disabled, false);
  assert.equal(confirm.textContent, "Waive case");
  assert.equal(reloads, 0);
  assert.equal(byClass(host, "qa-action-overlay").length, 1);
  assert.equal(
    byClass(host, "qa-waiver-rationale")[0].value,
    "Equivalent external proof was reviewed.",
  );
  assert.deepEqual(
    byClass(host, "qa-action-error").map((node) => node.textContent),
    ["Waiver service is unreachable."],
  );
});

test("a rejected Test Mac save restores its label and reports retryable state", async () => {
  const prepared = rejectedContext("Settings service is unreachable.");
  const host = prepared.documentNode.createElement("div");
  let closes = 0;
  let saves = 0;
  host.appendChild(machineSettingsDialog(
    prepared.value,
    {
      project: "yoke",
      settings: {
        resource_name: "mac-mini-lab",
        host: "test-mac.local",
        user: "yoke-test",
        operating_notes: "Keep Terminal unobscured.",
      },
      settings_token: "{\"host\":\"test-mac.local\"}",
      secrets: [],
    },
    () => { closes += 1; },
    () => { saves += 1; },
  ));
  const save = allNodes(host).find(
    (node) => node.tagName === "BUTTON" &&
      node.textContent === "Save non-secret settings",
  );

  save.dispatchEvent(new Event("click"));
  assert.equal(save.disabled, true);
  assert.equal(save.textContent, "Saving…");
  await settle();

  assert.equal(save.disabled, false);
  assert.equal(save.textContent, "Save non-secret settings");
  assert.equal(closes, 0);
  assert.equal(saves, 0);
  const errors = byClass(host, "test-machine-settings-error");
  assert.equal(errors.length, 1);
  assert.equal(errors[0].hidden, false);
  assert.equal(errors[0].attributes.get("role"), "alert");
  assert.equal(errors[0].textContent, "Settings service is unreachable.");
});
