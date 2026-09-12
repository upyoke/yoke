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
  visibleText,
} from "./universe_ui_dom_test_support.mjs";

function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

const CATALOG = [
  { id: "dash", label: "Dash", description: "Complete a small change." },
  { id: "polish", label: "Polish", description: "Review and finish work." },
  { id: "steer", label: "Steer", description: "Steer against a plan." },
];

const SUMMARY = {
  project: "yoke",
  project_id: 1,
  configured: true,
  action_catalog: CATALOG,
  unrouted_harnesses: [],
  harnesses: [
    { id: "claude-code", label: "Claude Code" },
    { id: "codex", label: "Codex" },
    { id: "cursor", label: "Cursor" },
  ],
  lanes: [
    {
      id: "DARIUS",
      label: "DARIUS",
      glyph: "🐎",
      actions: ["dash", "polish", "steer"],
      matches: [],
      default_for: ["Claude Code"],
    },
    {
      id: "ALTMAN",
      label: "SPECS",
      glyph: "👓",
      actions: ["polish"],
      matches: [
        { lane: "ALTMAN", harness: "cursor", model: "gpt-*" },
        { lane: "ALTMAN", harness: null, model: "claude-opus-5" },
      ],
      default_for: [],
    },
    {
      id: "MUSKY",
      label: "MUSKY",
      glyph: "🛸",
      actions: [],
      matches: [{ lane: "MUSKY", harness: "cursor", model: null }],
      default_for: ["Cursor"],
    },
  ],
};

const PROJECT_ROW = {
  id: 1,
  slug: "yoke",
  name: "Yoke",
  emoji: "🐂",
  public_item_prefix: "YOK",
  default_branch: "main",
  github_repo: "upyoke/yoke",
  github_sync_mode: "disabled",
  created_at: "2026-03-08 18:27:33",
};

function client(handlers = {}, requests = []) {
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") return ok({ name: "Yoke" });
      if (request.function === "projects.list") {
        return ok({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "projects.get") return ok({ row: PROJECT_ROW });
      if (handlers[request.function]) return handlers[request.function](request);
      if (request.function === "projects.lane_summary.get") return ok(SUMMARY);
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountProject(t, projectId, apiClient) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = `#/projects/${projectId}`;
  const root = documentNode.createElement("div");
  mountUniverseApp(root, { client: apiClient });
  await settle();
  return root;
}

function laneRow(root, laneId) {
  return allNodes(root).find(
    (node) => node.getAttribute?.("data-lane-row") === laneId,
  );
}

test("the lane summary keeps every production project fact", async (t) => {
  const root = await mountProject(t, 1, client());
  const text = visibleText(root, "\n");
  for (const fact of [
    "YOK", "main", "upyoke/yoke", "disabled", "2026-03-08 18:27:33",
    "All projects →", "Open repository ↗",
  ]) {
    assert.ok(text.includes(fact), `missing project fact: ${fact}`);
  }
});

test("each lane shows its glyph, label, matches, actions and defaults", async (t) => {
  const root = await mountProject(t, 1, client());

  const darius = laneRow(root, "DARIUS");
  assert.ok(darius, "DARIUS row missing");
  assert.equal(byClass(darius, "lane-glyph")[0].textContent, "🐎");
  // Presentation is the configured label; the identity stays DARIUS.
  const altman = laneRow(root, "ALTMAN");
  assert.ok(visibleText(altman, "\n").includes("SPECS"));

  // Several matches on one lane are alternatives, and all are shown.
  const matches = byClass(altman, "lane-match-summary");
  assert.equal(matches.length, 2);
  assert.ok(visibleText(matches[0], " ").includes("Cursor"));
  assert.ok(visibleText(matches[0], " ").includes("gpt-*"));
  assert.ok(visibleText(matches[1], " ").includes("Any harness"));

  assert.ok(visibleText(darius, "\n").includes("Claude Code"));
});

test("a full allowlist collapses and a subset names its actions", async (t) => {
  const root = await mountProject(t, 1, client());

  const dariusSummary = allNodes(laneRow(root, "DARIUS"))
    .find((node) => node.tagName === "SUMMARY");
  assert.equal(ownTextContent(dariusSummary), "All 3 actions");

  const altmanSummary = allNodes(laneRow(root, "ALTMAN"))
    .find((node) => node.tagName === "SUMMARY");
  assert.equal(ownTextContent(altmanSummary), "Polish");

  const single = await mountProject(t, 1, client({
    "projects.lane_summary.get": () => ok({
      ...SUMMARY,
      action_catalog: CATALOG.slice(0, 1),
      lanes: [{ ...SUMMARY.lanes[0], actions: ["dash"] }],
    }),
  }));
  const singleSummary = allNodes(laneRow(single, "DARIUS"))
    .find((node) => node.tagName === "SUMMARY");
  assert.equal(ownTextContent(singleSummary), "All 1 action");
});

test("an empty allowlist reads as None, never as all actions", async (t) => {
  const root = await mountProject(t, 1, client());
  const musky = visibleText(laneRow(root, "MUSKY"), "\n");
  assert.ok(musky.includes("None"));
  assert.ok(!musky.includes("All 3 actions"));
});

test("action descriptions are disclosed from the shared catalog", async (t) => {
  const root = await mountProject(t, 1, client());
  const text = visibleText(laneRow(root, "DARIUS"), "\n");
  for (const action of CATALOG) {
    assert.ok(text.includes(action.description), `missing ${action.id}`);
  }
});

test("the summary is read only and teaches the harness edit path", async (t) => {
  const root = await mountProject(t, 1, client());
  // Scoped to the settings content: the app shell's own navigation controls
  // are not part of what this screen offers an operator.
  const main = byClass(root, "lane-settings")[0].parentNode;
  assert.equal(
    allNodes(main).filter((n) => ["BUTTON", "INPUT", "SELECT", "TEXTAREA", "FORM"]
      .includes(n.tagName)).length,
    0,
    "the project settings screen must carry no write control",
  );
  const text = visibleText(main, "\n");
  assert.ok(text.includes("Edit with your harness"));
  assert.ok(text.includes("tell your agent to use"));
  assert.ok(text.includes("yoke projects capability-settings"));
  assert.ok(text.includes(
    "explicit override → harness + model → model → harness → default.",
  ));
  // Omitted by the approved design.
  assert.ok(!text.includes("Project lane settings"));
  assert.ok(!text.includes("Save"));
  assert.ok(!text.includes("Delivery defaults"));
  assert.ok(!text.includes("Architecture"));
});

test("the summary follows the opened project, not a remembered filter", async (t) => {
  const requests = [];
  await mountProject(t, 7, client({
    "projects.get": () => ok({ row: { ...PROJECT_ROW, id: 7 } }),
  }, requests));
  const summaryCall = requests.find(
    (request) => request.function === "projects.lane_summary.get",
  );
  assert.deepEqual(summaryCall.payload, { project: "7" });
});

test("a read failure says so rather than showing an empty settings table", async (t) => {
  const root = await mountProject(t, 1, client({
    "projects.lane_summary.get": () => ({
      status: 500,
      envelope: { success: false, error: { message: "routing read failed" } },
    }),
  }));
  const text = visibleText(root, "\n");
  assert.ok(text.includes("read failed"));
  assert.ok(text.includes("routing read failed"));
  assert.ok(!text.includes("No lanes configured"));
});

test("a harness that routes nowhere is named", async (t) => {
  const root = await mountProject(t, 1, client({
    "projects.lane_summary.get": () => ok({
      ...SUMMARY, unrouted_harnesses: ["Codex", "Cursor"],
    }),
  }));
  const notice = byClass(root, "lane-unrouted")[0];
  assert.ok(notice);
  assert.ok(notice.textContent.includes("Codex, Cursor"));
  assert.ok(notice.textContent.includes("cannot be routed"));
});
