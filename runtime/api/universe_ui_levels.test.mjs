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

const CLAUDE_WEEKLY = { label: "Claude weekly · all models", left: 72, headroom: 177 };
const CODEX_WEEKLY = { label: "Codex weekly", left: 35, headroom: 79 };
const CURSOR_MODELS = { label: "Cursor Models", left: 9, headroom: 998 };
const CURSOR_OTHER = { label: "Cursor Other Models", left: 0, headroom: 0 };

function option(surface, model, display, effort, context, pools, now, extra = {}) {
  return {
    surface, model, display_name: display, native_selector: surface === "cursor-cli",
    reasoning_effort: effort, context_window_tokens: context, pools, now, ...extra,
  };
}

function canLaunch(pool) {
  return {
    state: "can_launch", via: null, via_display_name: null,
    machine_id: "m1", binding_pool: pool,
  };
}

const SPREAD_REASON =
  "level JUNIOR: spread rule: no live worker on cursor-cli and headroom " +
  "998% (Cursor Models) above 100%; chose cursor-cli grok-4.7-high high on m1";

const CAPACITY = {
  read_at: "2026-10-06T18:43:00Z",
  source: "universe",
  usable_machines: 1,
  live_workers: { "claude-cli": 8, "codex-cli": 0, "cursor-cli": 0 },
  levels: [
    {
      name: "JUNIOR",
      glyph: "🐥",
      launchable_surfaces: ["claude-cli", "codex-cli", "cursor-cli"],
      next_launches: [
        {
          project: "yoke", launchable: true, code: "selected", option_index: 0,
          fallback: false, surface: "cursor-cli", model: "grok-4.7-high",
          display_name: "Grok 4.7", machine_id: "m1", rule: "spread",
          reason: SPREAD_REASON,
        },
        {
          project: "buzz", launchable: false, code: "level_unknown",
          reason: "Level 'JUNIOR' is not defined",
        },
      ],
      options: [
        option(
          "cursor-cli", "grok-4.7-high", "Grok 4.7", "high", null,
          [CURSOR_MODELS], canLaunch(CURSOR_MODELS),
          {
            fallback: option(
              "cursor-cli", "claude-opus-5-5-medium", "Claude Opus 5.5",
              "medium", null, [CURSOR_OTHER], null,
            ),
          },
        ),
        option(
          "claude-cli", "claude-sonnet-5-5", "Claude Sonnet 5.5", "xhigh",
          1000000, [CLAUDE_WEEKLY], canLaunch(CLAUDE_WEEKLY),
        ),
      ],
    },
    {
      name: "PRINCIPAL",
      glyph: "🦅",
      launchable_surfaces: [],
      next_launches: [
        {
          project: "yoke", launchable: false, code: "level_no_capacity",
          reason: "No PRINCIPAL option has capacity",
        },
      ],
      options: [
        option(
          "codex-cli", "gpt-6-astra", "GPT-6 Astra", "xhigh", null,
          [{ ...CODEX_WEEKLY, left: 0, headroom: 0 }],
          {
            state: "blocked",
            blockers: [{ kind: "pool", label: "Codex weekly", left: 0 }],
          },
        ),
      ],
    },
  ],
  projects: [
    { project: "yoke", name: "Yoke", override: false, changes: [] },
    {
      project: "buzz", name: "Buzz", override: true,
      changes: [["SENIOR", "options changed"]],
    },
  ],
};

const PROJECT_ROW = {
  id: 1, slug: "yoke", name: "Yoke", emoji: "🐂", public_item_prefix: "YOK",
  default_branch: "main", github_repo: "upyoke/yoke",
  github_sync_mode: "disabled", created_at: "2026-03-08 18:27:33",
};

function client(handlers = {}, requests = []) {
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (handlers[request.function]) return handlers[request.function](request);
      if (request.function === "organizations.get") return ok({ name: "Yoke" });
      if (request.function === "projects.list") {
        return ok({ rows: [{ id: 1, slug: "yoke", name: "Yoke" }] });
      }
      if (request.function === "projects.get") return ok({ row: PROJECT_ROW });
      if (request.function === "universe.level_capacity.get") return ok(CAPACITY);
      if (request.function === "workflows.definition.get") {
        return ok({ title_max_length: 100 });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mount(t, path, apiClient) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = path;
  const root = documentNode.createElement("div");
  mountUniverseApp(root, { client: apiClient });
  await settle();
  return root;
}

function level(root, name) {
  return allNodes(root).find((node) => node.getAttribute?.("data-level") === name);
}

test("Levels sits in Settings directly under Universe", async (t) => {
  const root = await mount(t, "/levels", client());
  const labels = byClass(root, "nav-link").map((link) => visibleText(link, " ").trim());
  const universe = labels.indexOf("Universe");
  assert.ok(universe >= 0, `nav labels: ${labels}`);
  assert.equal(labels[universe + 1], "Levels");
});

test("the read line names capacity time, machines and live workers", async (t) => {
  const root = await mount(t, "/levels", client());
  assert.equal(
    byClass(root, "levels-read")[0].textContent,
    "Capacity read 2026-10-06 18:43 UTC · 1 usable machine · " +
      "live workers claude-cli 8 · codex-cli 0 · cursor-cli 0",
  );
  assert.ok(visibleText(root, "\n").includes("View only"));
});

test("a launchable level names its surfaces and each project's next launch", async (t) => {
  const root = await mount(t, "/levels", client());
  const junior = level(root, "JUNIOR");
  const text = visibleText(junior, " ");
  assert.equal(byClass(junior, "level-glyph")[0].textContent, "🐥");
  assert.ok(text.includes("2 options"));
  assert.deepEqual(
    byClass(junior, "pill").slice(0, 3).map((p) => p.textContent),
    ["claude-cli", "codex-cli", "cursor-cli"],
  );
  const next = byClass(junior, "level-next").map((line) => visibleText(line, ""));
  assert.deepEqual(next, [
    `Next launch in yoke → cursor-cli · Grok 4.7 (option 1) on m1: ${SPREAD_REASON}`,
    "Next launch in buzz → Refused level_unknown: Level 'JUNIOR' is not defined",
  ]);
  assert.ok(text.includes("Cursor Models exhausted →"));
  assert.ok(text.includes("claude-opus-5-5-medium"));
  assert.ok(text.includes("high / medium"));
  assert.ok(text.includes("Grok 4.7 · Cursor selector"));
  assert.ok(text.includes("Cursor Other Models"));
  assert.ok(text.includes("1M"));
  const now = byClass(junior, "level-now");
  assert.equal(byClass(now[0], "pill")[0].textContent, "Can launch");
  assert.equal(byClass(now[1], "pill")[0].textContent, "Can launch");
  assert.equal(
    visibleText(byClass(now[1], "level-headroom")[0], ""),
    "177% headroom · Claude weekly · all models, 72% left",
  );
});

test("a level with no capacity names each option's blocking pool", async (t) => {
  const root = await mount(t, "/levels", client());
  const principal = level(root, "PRINCIPAL");
  const summary = byClass(principal, "level-exhausted")[0];
  assert.ok(visibleText(summary, " ").includes("No capacity"));
  assert.ok(
    visibleText(summary, "").includes("codex-cli · GPT-6 Astra: Codex weekly 0% left"),
  );
  const now = byClass(principal, "level-now")[0];
  assert.equal(byClass(now, "pill")[0].textContent, "Blocked");
  assert.ok(visibleText(now, " ").includes("Codex weekly · 0% left"));
  assert.equal(
    visibleText(byClass(principal, "level-next")[0], ""),
    "Next launch in yoke → Refused level_no_capacity: No PRINCIPAL option has capacity",
  );
});

test("project overrides list each project and point at the override command", async (t) => {
  const root = await mount(t, "/levels", client());
  const panel = byClass(root, "levels-overrides-panel")[0];
  const text = visibleText(panel, "\n");
  assert.ok(text.includes("Project overrides"));
  assert.ok(text.includes("· 1"));
  assert.ok(text.includes("Universe default"));
  assert.ok(text.includes("Override"));
  assert.ok(visibleText(panel, "").includes("SENIOR · options changed"));
  assert.ok(text.includes("yoke projects capability-settings --cap-type session-routing"));
});

test("the page is read only", async (t) => {
  const root = await mount(t, "/levels", client());
  const stack = byClass(root, "levels")[0];
  assert.equal(
    allNodes(stack).filter((n) => ["BUTTON", "INPUT", "SELECT", "TEXTAREA", "FORM"]
      .includes(n.tagName)).length,
    0,
  );
});

test("a read failure names it instead of an empty page", async (t) => {
  const root = await mount(t, "/levels", client({
    "universe.level_capacity.get": () => ({
      status: 500,
      envelope: { success: false, error: { message: "levels read failed" } },
    }),
  }));
  const text = visibleText(root, "\n");
  assert.ok(text.includes("read failed"));
  assert.ok(text.includes("levels read failed"));
  assert.equal(byClass(root, "levels-overrides-panel").length, 0);
});

test("project settings no longer carries a levels table", async (t) => {
  const requests = [];
  const root = await mount(t, "/projects/1", client({}, requests));
  const text = visibleText(root, "\n");
  for (const fact of ["YOK", "main", "upyoke/yoke", "2026-03-08 18:27:33"]) {
    assert.ok(text.includes(fact), `missing project fact: ${fact}`);
  }
  assert.equal(byClass(root, "level-settings").length, 0);
  assert.ok(!requests.some((r) => r.function === "projects.level_summary.get"));
});
