import assert from "node:assert/strict";
import test from "node:test";

import { renderTestMachineDetail } from
  "../../packages/yoke-core/src/yoke_core/ui/static/universe_view_test_machine.js";
import { byClass } from "./universe_ui_dom_test_support.mjs";

import {
  context,
  detail,
  text,
} from "./universe_ui_test_machine_test_support.mjs";

async function renderDetail() {
  const prepared = context();
  const main = prepared.documentNode.createElement("main");
  await renderTestMachineDetail(prepared.value, main, "yoke");
  return main;
}

test("the machine says which implementation drives it", async () => {
  const rendered = text(await renderDetail());

  assert.match(rendered, /Host kind/);
  assert.match(rendered, /mac-ssh/);
});

test("verification says in words what state it left the machine in", async () => {
  // Reaching both baselines in order leaves the launcher installed, and a
  // reader should not have to infer that from a baseline name.
  const rendered = text(await renderDetail());

  assert.match(rendered, /Machine was left/);
  assert.match(rendered, /it is NOT a fresh host/);
});

test("the last run of each operation is readable on the machine", async () => {
  const main = await renderDetail();
  const operations = byClass(main, "test-machine-operations-body")[0];

  assert.equal(byClass(operations, "test-machine-check").length, 1);
  assert.match(text(operations), /Reset to a named baseline/);
  assert.match(text(operations), /completed/);
});

test("a machine nothing has been done to says so instead of rendering empty", async () => {
  const prepared = context([{ ...detail, operations: [] }]);
  const main = prepared.documentNode.createElement("main");

  await renderTestMachineDetail(prepared.value, main, "yoke");

  const operations = byClass(main, "test-machine-operations-body")[0];
  assert.equal(byClass(operations, "test-machine-check").length, 0);
  assert.match(
    text(operations),
    /No reset, capture, or bridge diagnosis has run on this machine/,
  );
});
