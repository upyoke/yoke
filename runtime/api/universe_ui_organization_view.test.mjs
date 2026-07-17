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

// The shell's own two reads, plus the org card the Identity panel reads.
// `organizations.get` serves both, so it answers a full card here.
function shellClient() {
  return {
    async call(request) {
      if (request.function === "organizations.get") {
        return {
          status: 200,
          envelope: {
            success: true,
            result: {
              name: "Local", slug: "local", created_at: "2026-01-01T00:00:00Z",
            },
          },
        };
      }
      if (request.function === "projects.list") {
        return { status: 200, envelope: { success: true, result: { rows: [] } } };
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountOrganization(options = {}) {
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = "#/organization";
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, {
    client: shellClient(), ...options,
  });
  await settle();
  return { root, mounted };
}

function panelTitles(root) {
  return byClass(root, "panel-header")
    .map((header) => header.children[0].textContent);
}

// Portability is the second panel. Identity's raw-JSON toggle is a button of
// its own, so an assertion about controls has to name this panel rather than
// sweep the whole view.
function portabilityPanel(root) {
  return byClass(root, "panel")[1];
}

test("the Identity panel names the organization from the served card", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const { root, mounted } = await mountOrganization();

  // Identity leads: the screen is named for the org, so it says which one.
  assert.deepEqual(panelTitles(root), ["Identity", "Portability"]);
  const cells = allNodes(byClass(root, "panel")[0])
    .filter((node) => node.tagName === "TD")
    .map((node) => node.textContent);
  // The engine's org card is a name, a slug, and a stamp — nothing more, so
  // nothing more shows.
  assert.deepEqual(cells, ["Local", "local", "2026-01-01T00:00:00Z"]);
  mounted.unmount();
});

test("without host actions the Portability panel is copyable text, not controls", async (t) => {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});

  const { root, mounted } = await mountOrganization();

  // The local UI server is a read-only allowlist, so nothing mounted this
  // way can move a universe: each command renders as a <code> element —
  // deliberately copyable text — and no control pretends otherwise.
  const panel = portabilityPanel(root);
  const codes = allNodes(panel).filter((node) => node.tagName === "CODE");
  assert.deepEqual(codes.map((node) => node.textContent), [
    "yoke universe export",
    "yoke universe validate <archive>",
  ]);
  assert.ok(!allNodes(panel).some((node) => node.tagName === "BUTTON"));
  assert.equal(byClass(root, "capability-actions").length, 0);
  const text = allNodes(panel).map((node) => node.textContent || "").join(" ");
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

  const { root, mounted } = await mountOrganization({
    capabilities: { actions: [{ label: "Silent" }, null] },
  });

  // An action without an onInvoke handler cannot act, and a button that
  // cannot act is a lie — the panel keeps the honest command text instead.
  const panel = portabilityPanel(root);
  assert.ok(!allNodes(panel).some((node) => node.tagName === "BUTTON"));
  assert.ok(allNodes(panel).some((node) => node.tagName === "CODE"));
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

  const { root, mounted } = await mountOrganization({
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
