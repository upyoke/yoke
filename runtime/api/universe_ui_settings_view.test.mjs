import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";

// The two reads every mount makes; the settings view itself reads nothing.
function shellClient() {
  return {
    async call(request) {
      if (request.function === "organizations.get") {
        return { status: 200, envelope: { success: true, result: { name: "Local" } } };
      }
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: { rows: [] } } };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountSettings(options = {}) {
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/universe-settings";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, {
    client: shellClient(), ...options,
  });
  await settle();
  return { root, mounted };
}

test("without host actions the Portability panel is copyable text, not controls", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const { root, mounted } = await mountSettings();

  const panel = byClass(root, "panel")[0];
  assert.equal(byClass(panel, "panel-header")[0].children[0].textContent,
    "Portability");
  // The local UI server is a read-only allowlist, so nothing mounted this
  // way can move a universe: each command renders as a <code> element —
  // deliberately copyable text — and no control pretends otherwise.
  const view = byClass(root, "view-host")[0];
  const codes = allNodes(view).filter((node) => node.tagName === "CODE");
  assert.deepEqual(codes.map((node) => node.textContent), [
    "yoke universe export",
    "yoke universe validate <archive>",
  ]);
  assert.ok(!allNodes(view).some((node) => node.tagName === "BUTTON"));
  assert.equal(byClass(root, "capability-actions").length, 0);
  const text = allNodes(view).map((node) => node.textContent || "").join(" ");
  assert.ok(text.includes(
    "Importing into a local universe is not available yet",
  ));
  assert.ok(text.includes("hosted import lives in the host dashboard"));
  mounted.unmount();
});

test("an actions bag with nothing invocable falls back to the copyable text", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const { root, mounted } = await mountSettings({
    capabilities: { actions: [{ label: "Silent" }, null] },
  });

  // An action without an onInvoke handler cannot act, and a button that
  // cannot act is a lie — the panel keeps the honest command text instead.
  const view = byClass(root, "view-host")[0];
  assert.ok(!allNodes(view).some((node) => node.tagName === "BUTTON"));
  assert.ok(allNodes(view).some((node) => node.tagName === "CODE"));
  mounted.unmount();
});

test("a failing host action reports through console.error and keeps the screen", async (t) => {
  const originalFetch = globalThis.fetch;
  const originalError = globalThis.console.error;
  t.after(() => {
    globalThis.fetch = originalFetch;
    globalThis.console.error = originalError;
  });
  globalThis.fetch = () => response(200, {});
  const reported = [];
  globalThis.console.error = (...args) => { reported.push(args); };

  const { root, mounted } = await mountSettings({
    capabilities: {
      actions: [
        { label: "Throws", onInvoke: () => { throw new Error("sync failure"); } },
        {
          label: "Rejects",
          onInvoke: async () => { throw new Error("async failure"); },
        },
      ],
    },
  });

  const buttons = byClass(root, "capability-action");
  assert.deepEqual(buttons.map((node) => node.textContent),
    ["Throws", "Rejects"]);
  buttons[0].dispatchEvent(new Event("click"));
  buttons[1].dispatchEvent(new Event("click"));
  await settle();
  assert.equal(reported.length, 2);
  assert.ok(reported.every(
    (args) => args[0] === "universe capability action failed",
  ));
  // The failed invocations changed nothing on screen: both buttons stand.
  assert.equal(byClass(root, "capability-action").length, 2);
  mounted.unmount();
});
