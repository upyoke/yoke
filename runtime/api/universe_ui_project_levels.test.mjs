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
  source: "universe",
  configured: false,
  levels: [
    {
      name: "JUNIOR",
      glyph: "🐥",
      options: [
        {
          surface: "cursor-cli",
          model: "grok-4.7-high",
          reasoning_effort: "high",
          context_window_tokens: null,
          fallback: {
            surface: "cursor-cli",
            model: "claude-opus-5-5-medium",
            reasoning_effort: "medium",
            context_window_tokens: null,
          },
        },
        {
          surface: "claude-cli",
          model: "claude-sonnet-5-5",
          reasoning_effort: "xhigh",
          context_window_tokens: 1000000,
        },
      ],
    },
    {
      name: "SENIOR",
      glyph: "🦉",
      options: [
        {
          surface: "claude-cli",
          model: "claude-opus-5-5",
          reasoning_effort: "medium",
          context_window_tokens: 1000000,
        },
      ],
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

test("each level shows its glyph, name, and ordered options", async (t) => {
  const root = await mountProject(t, 1, client());

  const junior = levelRow(root, "JUNIOR");
  assert.ok(junior, "JUNIOR row missing");
  assert.equal(byClass(junior, "level-glyph")[0].textContent, "🐥");
  assert.ok(visibleText(junior, "\n").includes("JUNIOR"));

  const options = byClass(junior, "level-option");
  assert.equal(options.length, 3, "two options plus one fallback");
  assert.ok(visibleText(options[0], " ").includes("grok-4.7-high"));
  assert.ok(visibleText(options[0], " ").includes("high · default context"));
  assert.ok(options[1].className.includes("level-fallback"));
  assert.ok(visibleText(options[1], " ").includes("claude-opus-5-5-medium"));
  assert.ok(visibleText(options[2], " ").includes("1,000,000 tokens"));
});

test("level rows contain a level and an options column", async (t) => {
  const root = await mountProject(t, 1, client());
  for (const level of SUMMARY.levels) {
    assert.equal(levelRow(root, level.name).children.length, 2);
  }
});

test("the source of the levels is named", async (t) => {
  const universe = await mountProject(t, 1, client());
  assert.ok(visibleText(universe, "\n").includes("Universe levels"));
  const override = await mountProject(t, 1, client({
    "projects.level_summary.get": () => ok({
      ...SUMMARY, source: "project", configured: true,
    }),
  }));
  assert.ok(visibleText(override, "\n").includes("This project's override"));
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

    const levelSettingsText = visibleText(byClass(main, "level-settings")[0], "\n");
    assert.ok(levelSettingsText.includes("Edit with your harness"));
    assert.ok(levelSettingsText.includes("tell your agent to use"));
    assert.ok(levelSettingsText.includes("yoke universe levels set"));
    assert.ok(levelSettingsText.includes("yoke projects capability-settings"));
    assert.ok(!levelSettingsText.includes("Save"));
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
      envelope: { success: false, error: { message: "levels read failed" } },
    }),
  }));
  const text = visibleText(root, "\n");
  assert.ok(text.includes("read failed"));
  assert.ok(text.includes("levels read failed"));
});
