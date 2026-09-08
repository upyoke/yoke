import assert from "node:assert/strict";
import test from "node:test";

import {
  mountUniverseApp,
} from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
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

const FOUR_TITLES = [
  "GitHub App installations",
  "Personal GitHub authorization",
  "Project mappings with issue-sync",
  "Machine authentications",
];
const HOSTED_TITLES = [
  "Project mappings with issue-sync",
  "Machine authentications",
];

function boundStatusFixture(overrides = {}) {
  return {
    project: "yoke",
    github_repo: "example-org/example-repo",
    default_branch: "main",
    github_sync_mode: "enabled",
    bound: true,
    binding: {
      project_id: 1,
      installation_id: "inst-31",
      repository_id: "repo-9",
      api_url: "https://api.github.com",
      github_repo: "example-org/example-repo",
      default_branch: "main",
      status: "active",
      permissions: { contents: "write" },
      last_verified_at: "2026-07-01T10:00:00Z",
      last_error: "",
      last_sync_at: "2026-07-02T08:30:00Z",
      last_sync_outcome: "success",
      last_sync_error: "",
    },
    installation: {
      installation_id: "inst-31",
      api_url: "https://api.github.com",
      account_id: "acct-4",
      account_login: "example-org",
      account_type: "Organization",
      repository_selection: "selected",
      permissions: { contents: "write" },
      status: "active",
      last_verified_at: "2026-07-01T10:00:00Z",
      last_error: "",
    },
    permission_status: { status: "satisfied", missing: [] },
    automation: { available: true, reason: "bound" },
    ...overrides,
  };
}

function githubClient(statusResult, options = {}) {
  const requests = [];
  const machines = options.machines || [];
  return {
    requests,
    async call(request) {
      requests.push(request);
      if (request.function === "organizations.get") {
        return okEnvelope({ name: "Yoke" });
      }
      if (request.function === "projects.list") {
        return okEnvelope({
          rows: options.projects || [{ id: 1, slug: "yoke", name: "Yoke" }],
        });
      }
      if (request.function === "projects.github_binding.status") {
        return okEnvelope(statusResult);
      }
      if (request.function === "machine.list") {
        return okEnvelope({ machines, count: machines.length });
      }
      throw new Error(`unexpected function ${request.function}`);
    },
  };
}

async function mountGithub(t, client, options = {}) {
  const originalFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = originalFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.hash = options.hash || "#/github?project=1";
  const root = documentNode.createElement("div");
  const sections = typeof options.sections === "function"
    ? options.sections(documentNode) : options.sections;
  const mounted = mountUniverseApp(root, {
    client,
    capabilities: options.capabilities,
    sections,
  });
  await settle();
  return { root, mounted, documentNode };
}

function panelTitles(root, host = byClass(root, "view-host")[0]) {
  return allNodes(host)
    .filter((node) => node.tagName === "H2")
    .map((node) => node.textContent);
}

function viewText(root) {
  const view = byClass(root, "view-host")[0];
  return allNodes(view).map((node) => node.textContent || "").join(" ");
}

function pillTexts(root) {
  return byClass(root, "pill").map((node) => node.textContent);
}

function assertNoControls(root) {
  const view = byClass(root, "view-host")[0];
  assert.ok(!allNodes(view).some(
    (node) => ["SELECT", "INPUT", "BUTTON"].includes(node.tagName),
  ));
}

test("a bound project renders installations, mappings, and machine facts", async (t) => {
  const client = githubClient(boundStatusFixture(), {
    machines: [{
      machine_id: "m-1",
      name: "studio",
      owner_actor_id: 2,
      last_seen_at: "2026-07-03T12:00:00Z",
    }],
  });
  const { root, mounted } = await mountGithub(t, client);

  assert.deepEqual(
    client.requests.find(
      (request) => request.function === "projects.github_binding.status",
    ),
    {
      function: "projects.github_binding.status",
      payload: { project: "1" },
    },
  );
  assert.ok(client.requests.some(
    (request) => request.function === "machine.list",
  ));
  assert.deepEqual(panelTitles(root), FOUR_TITLES);

  const text = viewText(root);
  assert.ok(text.includes("example-org/example-repo"));
  assert.ok(text.includes("example-org"));
  assert.ok(text.includes("Organization"));
  assert.ok(text.includes("enabled"));
  assert.ok(text.includes("success"));
  assert.ok(text.includes("2026-07-02T08:30:00Z"));
  assert.ok(text.includes("bound"));
  assert.ok(text.includes("studio"));
  assert.ok(text.includes(
    "unavailable — this universe has no product read for a personal",
  ));

  const pills = pillTexts(root);
  assert.ok(pills.includes("satisfied"));
  assert.ok(pills.includes("available"));
  assert.ok(pills.includes("enabled"));
  assert.ok(pills.includes("unavailable"));
  assert.equal(pills.filter((text) => text === "unavailable").length, 2);

  assertNoControls(root);
  mounted.unmount();
});

test("an unbound project still maps the named repo, with no dead controls", async (t) => {
  const client = githubClient({
    project: "yoke",
    github_repo: "example-org/orphaned-repo",
    default_branch: "",
    github_sync_mode: "disabled",
    bound: false,
    binding: null,
    installation: null,
    permission_status: { status: "unknown", missing: [] },
    automation: { available: false, reason: "repo_not_bound" },
  });
  const { root, mounted } = await mountGithub(t, client);

  assert.deepEqual(panelTitles(root), FOUR_TITLES);
  const text = viewText(root);
  assert.ok(text.includes("example-org/orphaned-repo"));
  assert.ok(text.includes("repo_not_bound"));
  assert.ok(text.includes("no GitHub App installation backs a project"));

  const view = byClass(root, "view-host")[0];
  const codes = allNodes(view).filter((node) => node.tagName === "CODE");
  assert.deepEqual(
    codes.map((node) => node.textContent), ["example-org/orphaned-repo"],
  );

  assertNoControls(root);
  mounted.unmount();
});

test("a binding without an installation record renders honestly, not a crash", async (t) => {
  const client = githubClient(boundStatusFixture({
    installation: null,
    permission_status: {
      status: "unknown",
      missing: [],
      hint: "Reconnect the GitHub App so Yoke can verify its required " +
        "repository permissions.",
    },
    automation: { available: false, reason: "installation_missing" },
  }));
  const { root, mounted } = await mountGithub(t, client);

  assert.deepEqual(panelTitles(root), FOUR_TITLES);
  const text = viewText(root);
  assert.ok(text.includes(
    "the binding names installation inst-31, but no installation record " +
      "backs it",
  ));
  assert.ok(text.includes("installation_missing"));
  const pills = pillTexts(root);
  assert.ok(pills.includes("unknown"));
  assert.ok(pills.includes("unavailable"));

  assertNoControls(root);
  mounted.unmount();
});

test("hosted mode omits personal and installations so the host slot owns them", async (t) => {
  const client = githubClient(boundStatusFixture());
  let hostWrap;
  const { root, mounted } = await mountGithub(t, client, {
    capabilities: { data: { portability: { mode: "hosted" } } },
    sections(documentNode) {
      hostWrap = documentNode.createElement("div");
      for (const title of [
        "GitHub App installations", "Personal GitHub authorization",
      ]) {
        const panel = documentNode.createElement("section");
        const heading = documentNode.createElement("h2");
        heading.textContent = title;
        panel.appendChild(heading);
        hostWrap.appendChild(panel);
      }
      return { github: { content: hostWrap, placement: "beforeScope" } };
    },
  });

  assert.deepEqual(panelTitles(root), HOSTED_TITLES);
  const combined = allNodes(byClass(root, "content")[0])
    .filter((node) => node.tagName === "H2")
    .map((node) => node.textContent);
  assert.deepEqual(combined, FOUR_TITLES);
  assert.ok(!viewText(root).includes(
    "unavailable — this universe has no product read for a personal",
  ));
  assert.ok(allNodes(root).includes(hostWrap));
  assertNoControls(root);
  mounted.unmount();
});
