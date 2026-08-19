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

function okEnvelope(result) {
  return { status: 200, envelope: { success: true, result } };
}

const FLOWS = [
  {
    id: "alpha-release", name: "Alpha Release", project: "alpha",
    status: "active", target_tier: "persistent", target_environment: "prod",
    on_failure: "halt", stage_names: ["build", "verify"],
  },
  {
    id: "alpha-legacy", name: "Alpha Legacy", project: "alpha",
    status: "disabled", target_tier: "persistent", target_environment: "stage",
    on_failure: "continue", stage_names: ["archive"],
  },
  {
    id: "beta-promote", name: "Beta Promote", project: "beta",
    status: "active", target_tier: "ephemeral", target_environment: null,
    on_failure: "halt", stage_names: ["package", "promote", "observe"],
  },
];

function flowClient(flows = FLOWS) {
  const requests = [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({ rows: [
          { id: 1, slug: "alpha", name: "Alpha" },
          { id: 2, slug: "beta", name: "Beta" },
        ] });
      }
      if (request.function === "workflows.definition.get") {
        const project = request.payload.project;
        const projectSlug = project === "1" ? "alpha" : project === "2" ? "beta" : null;
        return okEnvelope({
          flows: projectSlug
            ? flows.filter((row) => row.project === projectSlug)
            : flows,
        });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountFlows(t, client, hash = "#/delivery/flows") {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { documentNode, root, mounted };
}

function cardNames(root) {
  return byClass(root, "delivery-flow-card-name").map((node) => node.textContent);
}

function detailHeading(root) {
  const detail = byClass(root, "delivery-flow-detail")[0];
  return allNodes(detail).find((node) => node.tagName === "H3")?.textContent;
}

function keyEvent(key) {
  const event = new Event("keydown", { cancelable: true });
  Object.defineProperty(event, "key", { value: key });
  return event;
}

test("flow explorer is active-first and makes history and selection explicit", async (t) => {
  const client = flowClient();
  const { documentNode, root, mounted } = await mountFlows(t, client);

  assert.deepEqual(
    client.requests.filter((request) => request.function === "workflows.definition.get"),
    [{ function: "workflows.definition.get", payload: {} }],
  );
  assert.deepEqual(cardNames(root), ["Alpha Release", "Beta Promote"]);
  const history = byClass(root, "delivery-flow-history-toggle")[0];
  assert.equal(history.textContent, "Show history (1)");
  assert.equal(history.attributes.get("aria-pressed"), "false");
  assert.equal(byClass(root, "delivery-flow-result-summary")[0].textContent,
    "2 flows shown · 1 historical hidden");

  const list = byClass(root, "delivery-flow-list")[0];
  assert.equal(list.attributes.get("role"), "listbox");
  assert.deepEqual(
    byClass(root, "delivery-flow-project-group").map(
      (group) => group.children[0].textContent,
    ),
    ["alpha", "beta"],
  );
  assert.deepEqual(byClass(root, "delivery-flow-project-group").map(
    (group) => group.attributes.get("aria-label")), ["alpha", "beta"]);
  let cards = byClass(root, "delivery-flow-card");
  assert.deepEqual(cards.map((card) => card.attributes.get("role")), ["option", "option"]);
  assert.deepEqual(cards.map((card) => card.attributes.get("aria-selected")), ["true", "false"]);
  assert.deepEqual(cards.map((card) => card.tabIndex), [0, -1]);
  assert.equal(cards[0].classList.contains("selected"), true);
  assert.equal(cards[0].attributes.get("data-status"), "active");
  assert.equal(detailHeading(root), "Alpha Release");
  assert.deepEqual(
    byClass(root, "delivery-flow-stage-name").map((node) => node.textContent),
    ["build", "verify"],
  );
  assert.equal(
    byClass(root, "delivery-flow-card-shape")[0].attributes.get("aria-label"),
    "2 stages: build, verify",
  );

  cards[0].dispatchEvent(keyEvent("ArrowDown"));
  cards = byClass(root, "delivery-flow-card");
  assert.deepEqual(cards.map((card) => card.attributes.get("aria-selected")), ["false", "true"]);
  assert.equal(documentNode.activeElement, cards[1]);
  assert.equal(detailHeading(root), "Beta Promote");

  history.dispatchEvent(new Event("click"));
  assert.equal(history.textContent, "Hide history");
  assert.equal(history.attributes.get("aria-pressed"), "true");
  assert.deepEqual(cardNames(root), ["Alpha Release", "Alpha Legacy", "Beta Promote"]);
  cards = byClass(root, "delivery-flow-card");
  assert.equal(cards[1].attributes.get("data-status"), "disabled");
  cards[1].dispatchEvent(new Event("click"));
  cards = byClass(root, "delivery-flow-card");
  assert.equal(cards[1].classList.contains("selected"), true);
  assert.equal(detailHeading(root), "Alpha Legacy");
  assert.equal(
    byClass(root, "delivery-flow-detail-title")[0].children[1]
      .attributes.get("data-state"),
    "disabled",
  );
  history.dispatchEvent(new Event("click"));
  assert.deepEqual(cardNames(root), ["Alpha Release", "Beta Promote"]);
  assert.equal(detailHeading(root), "Alpha Release");

  const rawToggle = byClass(root, "raw-toggle")[0];
  const raw = byClass(root, "raw-json")[0];
  assert.equal(raw.hidden, true);
  rawToggle.dispatchEvent(new Event("click"));
  assert.equal(raw.hidden, false);
  mounted.unmount();
});

test("search covers project, target, and stage text with a recoverable no-result state", async (t) => {
  const { documentNode, root, mounted } = await mountFlows(t, flowClient());
  const search = allNodes(byClass(root, "delivery-flow-search")[0])
    .find((node) => node.tagName === "INPUT");
  assert.equal(search.attributes.get("aria-controls"), "delivery-flow-list");

  search.value = "promote";
  search.dispatchEvent(new Event("input"));
  assert.deepEqual(cardNames(root), ["Beta Promote"]);
  assert.equal(detailHeading(root), "Beta Promote");

  search.value = "nowhere";
  search.dispatchEvent(new Event("input"));
  assert.equal(byClass(root, "delivery-flow-card").length, 0);
  assert.equal(byClass(root, "delivery-flow-no-results")[0].children[1].textContent,
    "No matching flows");
  assert.equal(byClass(root, "delivery-flow-detail")[0].classList.contains("is-empty"), true);
  byClass(root, "delivery-flow-clear")[0].dispatchEvent(new Event("click"));
  assert.deepEqual(cardNames(root), ["Alpha Release", "Beta Promote"]);
  assert.equal(documentNode.activeElement, search);

  search.value = "archive";
  search.dispatchEvent(new Event("input"));
  assert.equal(byClass(root, "delivery-flow-card").length, 0);
  assert.match(byClass(root, "delivery-flow-no-results")[0].children[2].textContent,
    /Historical definitions remain hidden/);
  mounted.unmount();
});

test("project scoping stays server-side while each browse item names its project", async (t) => {
  const client = flowClient();
  const { root, mounted } = await mountFlows(
    t, client, "#/delivery/flows?project=2",
  );
  assert.deepEqual(
    client.requests.filter((request) => request.function === "workflows.definition.get"),
    [{ function: "workflows.definition.get", payload: { project: "2" } }],
  );
  assert.deepEqual(cardNames(root), ["Beta Promote"]);
  assert.equal(byClass(root, "delivery-flow-card-project")[0].textContent, "beta");
  assert.equal(byClass(root, "scope-bar").length, 1);
  mounted.unmount();
});

test("empty and history-only scopes explain what can happen next", async (t) => {
  const empty = await mountFlows(t, flowClient([]));
  assert.equal(byClass(empty.root, "delivery-flow-empty-scope").length, 1);
  assert.equal(byClass(empty.root, "delivery-flow-empty-scope")[0].children[1].textContent,
    "No deployment flows yet");
  empty.mounted.unmount();

  const historyOnly = await mountFlows(t, flowClient([FLOWS[1]]));
  assert.equal(byClass(historyOnly.root, "delivery-flow-card").length, 0);
  assert.equal(byClass(historyOnly.root, "delivery-flow-no-results")[0].children[1].textContent,
    "No active flows");
  const toggle = byClass(historyOnly.root, "delivery-flow-history-toggle")[0];
  assert.equal(toggle.textContent, "Show history (1)");
  toggle.dispatchEvent(new Event("click"));
  assert.deepEqual(cardNames(historyOnly.root), ["Alpha Legacy"]);
  assert.equal(detailHeading(historyOnly.root), "Alpha Legacy");
  historyOnly.mounted.unmount();
});
