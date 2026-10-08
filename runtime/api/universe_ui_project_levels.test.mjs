import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  response,
  settle,
  visibleText,
} from "./universe_ui_dom_test_support.mjs";

function ok(result) {
  return { status: 200, envelope: { success: true, result } };
}

const SUMMARY = {
  project: "yoke",
  project_id: 1,
  configured: true,
  unrouted_harnesses: [],
  harnesses: [
    { id: "claude-code", label: "Claude Code" },
    { id: "codex", label: "Codex" },
    { id: "cursor", label: "Cursor" },
  ],
  levels: [
    {
      id: "DARIUS",
      label: "DARIUS",
      glyph: "🐎",
      matches: [],
      default_for: ["Claude Code"],
    },
    {
      id: "ALTMAN",
      label: "SPECS",
      glyph: "👓",
      matches: [
        { level: "ALTMAN", harness: "cursor", model: "gpt-*" },
        { level: "ALTMAN", harness: null, model: "claude-opus-5" },
      ],
      default_for: [],
    },
    {
      id: "MUSKY",
      label: "MUSKY",
      glyph: "🛸",
      matches: [{ level: "MUSKY", harness: "cursor", model: null }],
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
      if (request.function === "projects.level_summary.get") return ok(SUMMARY);
      if (request.function === "workflows.definition.get") {
        return ok({ title_max_length: 100 });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountProject(t, projectId, apiClient) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = `/projects/${projectId}`;
  const root = documentNode.createElement("div");
  mountUniverseApp(root, { client: apiClient });
  await settle();
  return root;
}

function levelRow(root, levelId) {
  return allNodes(root).find(
    (node) => node.getAttribute?.("data-level-row") === levelId,
  );
}

test("the level summary keeps every production project fact", async (t) => {
  const root = await mountProject(t, 1, client());
  const text = visibleText(root, "\n");
  for (const fact of [
    "YOK", "main", "upyoke/yoke", "disabled", "2026-03-08 18:27:33",
    "All projects →", "Open repository ↗",
  ]) {
    assert.ok(text.includes(fact), `missing project fact: ${fact}`);
  }
});

test("each level shows its glyph, label, matches and defaults", async (t) => {
  const root = await mountProject(t, 1, client());

  const darius = levelRow(root, "DARIUS");
  assert.ok(darius, "DARIUS row missing");
  assert.equal(byClass(darius, "level-glyph")[0].textContent, "🐎");
  // Presentation is the configured label; the identity stays DARIUS.
  const altman = levelRow(root, "ALTMAN");
  assert.ok(visibleText(altman, "\n").includes("SPECS"));

  // Several matches on one level are alternatives, and all are shown.
  const matches = byClass(altman, "level-match-summary");
  assert.equal(matches.length, 2);
  assert.ok(visibleText(matches[0], " ").includes("Cursor"));
  assert.ok(visibleText(matches[0], " ").includes("gpt-*"));
  assert.ok(visibleText(matches[1], " ").includes("Any harness"));

  assert.ok(visibleText(darius, "\n").includes("Claude Code"));
});

test("level rows contain three grouping columns", async (t) => {
  const root = await mountProject(t, 1, client());
  for (const level of SUMMARY.levels) {
    assert.equal(levelRow(root, level.id).children.length, 3);
  }
  const panelText = visibleText(byClass(root, "level-settings")[0], "\n");
  assert.ok(!panelText.includes("Allowed actions"));
});

test(
  "the summary is read only and teaches the harness edit path, except " +
  "the approved title-limit editor",
  async (t) => {
    const root = await mountProject(t, 1, client());
    // Scoped to the settings content: the app shell's own navigation
    // controls are not part of what this screen offers an operator.
    const main = byClass(root, "level-settings")[0].parentNode;
    const titleLimitCard = byClass(main, "project-settings-title-limit")[0];
    assert.ok(titleLimitCard, "the approved title-limit editor is missing");
    const titleLimitNodes = new Set(allNodes(titleLimitCard));

    assert.equal(
      allNodes(main).filter((n) => ["BUTTON", "INPUT", "SELECT", "TEXTAREA", "FORM"]
        .includes(n.tagName) && !titleLimitNodes.has(n)).length,
      0,
      "only the approved title-limit editor may carry a write control",
    );

    // Every other omission still holds outside the approved editor.
    const levelSettingsText = visibleText(byClass(main, "level-settings")[0], "\n");
    assert.ok(levelSettingsText.includes("Edit with your harness"));
    assert.ok(levelSettingsText.includes("tell your agent to use"));
    assert.ok(levelSettingsText.includes("yoke projects capability-settings"));
    assert.ok(levelSettingsText.includes(
      "explicit override → harness + model → model → harness → default.",
    ));
    assert.ok(!levelSettingsText.includes("Project level settings"));
    assert.ok(!levelSettingsText.includes("Save"));
    assert.ok(!levelSettingsText.includes("Delivery defaults"));
    assert.ok(!levelSettingsText.includes("Architecture"));
  },
);

test("the summary follows the opened project, not a remembered filter", async (t) => {
  const requests = [];
  await mountProject(t, 7, client({
    "projects.get": () => ok({ row: { ...PROJECT_ROW, id: 7 } }),
  }, requests));
  const summaryCall = requests.find(
    (request) => request.function === "projects.level_summary.get",
  );
  assert.deepEqual(summaryCall.payload, { project: "7" });
});

test("a read failure says so rather than showing an empty settings table", async (t) => {
  const root = await mountProject(t, 1, client({
    "projects.level_summary.get": () => ({
      status: 500,
      envelope: { success: false, error: { message: "routing read failed" } },
    }),
  }));
  const text = visibleText(root, "\n");
  assert.ok(text.includes("read failed"));
  assert.ok(text.includes("routing read failed"));
  assert.ok(!text.includes("No levels configured"));
});

test("a harness that routes nowhere is named", async (t) => {
  const root = await mountProject(t, 1, client({
    "projects.level_summary.get": () => ok({
      ...SUMMARY, unrouted_harnesses: ["Codex", "Cursor"],
    }),
  }));
  const notice = byClass(root, "level-unrouted")[0];
  assert.ok(notice);
  assert.ok(notice.textContent.includes("Codex, Cursor"));
  assert.ok(notice.textContent.includes("no configured level grouping"));
});
