import assert from "node:assert/strict";
import test from "node:test";

import {
  titleLimitCard,
} from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_projects.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";

function context(call) {
  const documentNode = new FakeDocument();
  return { document: documentNode, client: { call } };
}

function saveButton(host) {
  return allNodes(host).find(
    (node) => node.tagName === "BUTTON" && node.textContent === "Save",
  );
}

test("the card shows the effective limit and saves the edited value", async () => {
  const calls = [];
  const ctx = context(async (request) => {
    calls.push(request);
    return { status: 200, envelope: { success: true, result: {} } };
  });
  const host = ctx.document.createElement("div");
  host.appendChild(titleLimitCard(ctx, "yoke", 100));

  assert.equal(byClass(host, "project-settings-title-limit-input")[0].value, "100");

  byClass(host, "project-settings-title-limit-input")[0].value = "42";
  saveButton(host).dispatchEvent(new Event("click"));
  await settle();

  assert.equal(calls.length, 1);
  assert.equal(calls[0].function, "projects.capability_settings.merge");
  assert.deepEqual(calls[0].payload, {
    project: "yoke",
    cap_type: "project-policy",
    assignments: { title_max_length: 42 },
  });
  assert.equal(
    byClass(host, "project-settings-title-limit-status")[0].textContent,
    "Saved.",
  );
  assert.equal(saveButton(host).disabled, false);
});

test("the input has a programmatic label naming the setting", async () => {
  const ctx = context(async () => ({ status: 200, envelope: { success: true } }));
  const host = ctx.document.createElement("div");
  host.appendChild(titleLimitCard(ctx, "yoke", 100));

  const input = byClass(host, "project-settings-title-limit-input")[0];
  const label = input.parentNode;
  assert.equal(label.tagName, "LABEL", "the input's parent must be a <label>");
  assert.match(label.textContent, /Title character limit/);
  assert.ok(
    !allNodes(label).includes(saveButton(host)),
    "Save must not be nested inside the input's label",
  );
});

test("a rejected save reports the server's message and re-enables Save", async () => {
  const ctx = context(async () => ({
    status: 422,
    envelope: {
      success: false,
      error: { message: "Title character limit must be at least 10 (got 9)." },
    },
  }));
  const host = ctx.document.createElement("div");
  host.appendChild(titleLimitCard(ctx, "yoke", 100));

  byClass(host, "project-settings-title-limit-input")[0].value = "9";
  saveButton(host).dispatchEvent(new Event("click"));
  await settle();

  assert.equal(
    byClass(host, "project-settings-title-limit-status")[0].textContent,
    "Title character limit must be at least 10 (got 9).",
  );
  assert.equal(saveButton(host).disabled, false);
});
