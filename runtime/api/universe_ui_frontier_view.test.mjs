import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  ownTextContent,
  response,
  settle,
} from "./universe_ui_dom_test_support.mjs";
import {
  claimingSession,
  descendantText,
  recentIso,
  workbenchClient,
} from "./universe_ui_workbench_test_support.mjs";

function stubFetch(t) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
}

async function mountAt(hash, client) {
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = hash;
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client });
  await settle();
  return { documentNode, root, mounted };
}

const band = (root, key) => byClass(root, `work-band-${key}`)[0];

test("Frontier is five bands of work under one page heading", async (t) => {
  stubFetch(t);
  const client = workbenchClient();
  const { root, mounted } = await mountAt("#/frontier?project=1", client);

  // One heading, from the destination itself, and no count in it: the bands
  // under it carry their own.
  assert.equal(byClass(root, "page-head")[0].hidden, false);
  assert.equal(byClass(root, "title")[0].textContent, "Frontier");
  assert.deepEqual(
    byClass(root, "work-band-title").map(ownTextContent),
    ["Waiting", "Ready", "Active", "Release", "Done (24h)"],
  );
  // Shipping is its own page; the Frontier does not draw run cards.
  assert.equal(byClass(root, "shipping-run-card").length, 0);

  const called = new Set(client.requests.map((request) => request.function));
  for (const functionId of [
    "items.overview.list", "frontier.list", "sessions.list",
    "deployment_runs.list",
  ]) assert.ok(called.has(functionId), functionId);
  assert.deepEqual(
    client.requests.find((request) => request.function === "items.overview.list").payload,
    { relevance: "overview" },
  );
  assert.deepEqual(
    client.requests.find((request) => request.function === "sessions.list").payload,
    { per_project: true, open: true },
  );
  mounted.unmount();
});

test("an item card is readable text with its own links and controls", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountAt("#/frontier?project=1", workbenchClient());

  // Not one card-wide anchor: the card carries controls, and an interactive
  // control inside a link is neither keyboard-reachable nor clickable
  // without also navigating.
  assert.deepEqual(
    byClass(root, "work-item-card").map((node) => node.tagName),
    ["ARTICLE", "ARTICLE", "ARTICLE"],
  );
  assert.deepEqual(
    byClass(root, "work-item-card-ref").map((node) => node.href),
    ["#/items/7?project=1", "#/items/9?project=1", "#/items/6?project=1"],
  );
  assert.deepEqual(
    byClass(root, "overview-card-link").map((node) => node.href),
    ["#/items/7?project=1", "#/items/9?project=1", "#/items/6?project=1"],
  );
  assert.equal(
    allNodes(root).filter(
      (node) => node.tagName === "BUTTON"
        && allNodes(node).some((child) => child.tagName === "A"),
    ).length,
    0,
    "no control wraps a link",
  );
  mounted.unmount();
});

test("a condition is a pill; its whole reason is one press away", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountAt("#/frontier?project=1", workbenchClient());

  const pills = byClass(root, "item-status-pill");
  assert.deepEqual(
    pills.map((pill) => pill.children.at(-1).textContent),
    ["Frozen", "Ready"],
  );
  assert.ok(pills[0].classList.contains("is-frozen"));
  assert.ok(pills[1].classList.contains("is-ready"));
  // The reason is carried in full rather than trimmed to card width.
  const details = byClass(root, "item-status-detail");
  assert.match(descendantText(details[0]), /Waiting for a product decision\./);
  assert.match(
    descendantText(details[1]),
    /No blockers; specification and plan are current\./,
  );
  // Closed until asked for, and the pill says so.
  assert.equal(details[0].hidden, true);
  assert.equal(pills[0].getAttribute("aria-expanded"), "false");
  pills[0].dispatchEvent(new Event("click"));
  assert.equal(details[0].hidden, false);
  assert.equal(pills[0].getAttribute("aria-expanded"), "true");
  // Only one at a time.
  pills[1].dispatchEvent(new Event("click"));
  assert.equal(details[0].hidden, true);
  assert.equal(details[1].hidden, false);
  mounted.unmount();
});

test("Done says its lifecycle once and names where the work went", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountAt("#/frontier?project=1", workbenchClient());

  const done = band(root, "done");
  const text = descendantText(done);
  // The lifecycle pill in the card head is the one statement of it: no
  // "Complete" condition beside it, and no "done ·" in the meta line.
  assert.equal(byClass(done, "item-status-pill").length, 0);
  assert.doesNotMatch(text, /done ·/);
  assert.match(text, /finished/);

  // Real carried membership, with the run's own completion as the time.
  const deployment = byClass(done, "item-deployment")[0];
  assert.ok(deployment);
  assert.equal(deployment.href, "#/deployments/runs/run-0?project=1");
  assert.match(descendantText(deployment), /succeeded/);
  assert.match(descendantText(deployment), /stage/);
  assert.match(descendantText(deployment), /Deployed/);
  mounted.unmount();
});

test("Done names the selected-flow release, not a newer ancillary success", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountAt(
    "#/frontier?project=1",
    workbenchClient({
      "deployment_runs.list": { rows: [{
        id: "run-stage",
        project: "yoke",
        flow: "yoke-hosted-preview",
        target_environment: "preview",
        status: "succeeded",
        created_at: recentIso(1),
        completed_at: recentIso(1),
        stages: [{ name: "deploy", state: "complete" }],
        member_items: [{ id: 106, ref: "YOK-6", title: "Land the release" }],
      }, {
        id: "run-0",
        project: "yoke",
        flow: "yoke-hosted-stage",
        target_environment: "stage",
        status: "succeeded",
        created_at: recentIso(3),
        completed_at: recentIso(2),
        stages: [{ name: "deploy", state: "complete" }],
        member_items: [{ id: 106, ref: "YOK-6", title: "Land the release" }],
      }] },
    }),
  );

  const deployment = byClass(band(root, "done"), "item-deployment")[0];
  assert.ok(deployment);
  assert.equal(deployment.href, "#/deployments/runs/run-0?project=1");
  assert.doesNotMatch(descendantText(deployment), /preview/);
  mounted.unmount();
});

test("Active is claimed work, and Ready omits what a session holds", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountAt(
    "#/frontier?project=1",
    workbenchClient({ "sessions.list": { rows: [claimingSession()] } }),
  );

  // Active renders the ITEM, not the session card: the grid holds item
  // cards, and the only session card in the band is the one a claimant
  // preview reveals.
  assert.deepEqual(
    byClass(band(root, "active"), "work-card-grid")[0].children
      .map((node) => node.className),
    ["work-item-card"],
  );
  for (const card of byClass(band(root, "active"), "session-card")) {
    assert.ok(card.parentNode.classList.contains("item-claimant-preview"));
  }
  assert.deepEqual(
    byClass(band(root, "active"), "work-item-card-ref").map(ownTextContent),
    ["YOK-9"],
  );
  assert.equal(byClass(band(root, "active"), "work-band-count")[0].textContent, "1");
  assert.deepEqual(
    byClass(band(root, "ready"), "work-item-card").map((node) => node.href), [],
  );
  assert.deepEqual(
    byClass(band(root, "ready"), "work-band-count")[0].textContent, "0",
  );

  // The claimant rides the card as a compact control that reveals the whole
  // session, drawn by the same renderer Sessions uses.
  const claimant = byClass(root, "item-claimant-mini")[0];
  assert.ok(claimant);
  assert.match(descendantText(claimant), /codex/);
  const preview = byClass(root, "item-claimant-preview")[0];
  assert.equal(preview.hidden, true);
  assert.equal(byClass(preview, "session-card").length, 1);
  claimant.dispatchEvent(new Event("click"));
  assert.equal(preview.hidden, false);
  mounted.unmount();
});

test("work whose only claimant is gone waits, and says whose fault that is", async (t) => {
  stubFetch(t);
  const gone = {
    ...claimingSession(),
    native_process: { state: "gone" },
  };
  const { root, mounted } = await mountAt(
    "#/frontier?project=1",
    workbenchClient({ "sessions.list": { rows: [gone] } }),
  );

  // Not Active: nothing is running against it. Not Ready either: the claim
  // is still held, so it is not free to pick up.
  assert.deepEqual(
    byClass(band(root, "active"), "work-item-card").map(ownTextContent), [],
  );
  assert.deepEqual(
    byClass(band(root, "ready"), "work-item-card").map(ownTextContent), [],
  );
  const waiting = descendantText(band(root, "waiting"));
  assert.match(waiting, /YOK-9/);
  assert.match(waiting, /Owner unavailable/);
  mounted.unmount();
});

// An item between merge and deployment is the one case a lifecycle status
// decides outright. The other live bands read work claims and gate rows, so
// the same item can satisfy several of them at once — which is exactly how a
// release item used to be drawn twice.
function releasingClient() {
  const releasing = {
    public_ref: "YOK-11",
    internal_id: 111,
    title: "Land the release band",
    project: "yoke",
    project_id: 1,
    project_sequence: 11,
    workflow_id: "issue",
    status: "release",
    created_at: recentIso(12),
    updated_at: recentIso(1),
    merged_at: recentIso(1),
  };
  return workbenchClient({
    "items.overview.list": { rows: [releasing] },
    "frontier.list": {
      ready_rows: [{
        ...releasing,
        item_id: "YOK-11",
        why_ready: "No blocker is holding this item.",
        run_command: "yoke advance YOK-11",
      }],
      blocked_rows: [],
    },
    "sessions.list": { rows: [{
      ...claimingSession(),
      current_item: "YOK-11",
      current_item_title: "Land the release band",
      claims: [{ target_kind: "item", public_ref: "YOK-11", target: "YOK-11" }],
    }] },
  });
}

test("a release item is drawn once, and only in Release", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountAt("#/frontier?project=1", releasingClient());

  assert.deepEqual(
    byClass(root, "work-item-card").map(
      (card) => byClass(card, "work-item-card-ref")[0].textContent,
    ),
    ["YOK-11"],
  );
  assert.deepEqual(
    byClass(band(root, "release"), "work-item-card-ref").map(
      (node) => node.textContent,
    ),
    ["YOK-11"],
  );
  assert.equal(byClass(band(root, "release"), "work-band-count")[0].textContent, "1");
  // The readings that would otherwise have claimed it: a live session holds
  // its work claim, and the frontier still calls it ready to pick up.
  for (const key of ["waiting", "ready", "active", "done"]) {
    assert.equal(byClass(band(root, key), "work-item-card").length, 0, key);
  }
  mounted.unmount();
});

test("Release sits between Active and Done", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountAt("#/frontier?project=1", releasingClient());

  const keys = ["waiting", "ready", "active", "release", "done"];
  const bands = byClass(root, "work-band");
  assert.deepEqual(
    bands.map((node) => node.getAttribute("data-fold")),
    keys.map((key) => `band:${key}`),
  );
  mounted.unmount();
});

test("Release says what an empty one means", async (t) => {
  stubFetch(t);
  const { root, mounted } = await mountAt("#/frontier?project=1", workbenchClient());

  assert.equal(
    byClass(band(root, "release"), "work-band-empty")[0].textContent,
    "Nothing is waiting to ship.",
  );
  mounted.unmount();
});
