import assert from "node:assert/strict";
import test from "node:test";
import { renderGithubView } from "../../packages/yoke-core/src/yoke_core/ui/static/universe_views_github.js";
import { FakeDocument, allNodes, settle } from "./universe_ui_dom_test_support.mjs";
import {
  UNBOUND_STATUS, boundStatusFixture, buttons, click, githubClient,
  modeCapabilities, mountGithub, okEnvelope, viewText,
} from "./universe_ui_github_test_support.mjs";

function mappingClient() {
  let bound = true;
  const client = githubClient(null, { projects: [
    { id: 1, slug: "first", name: "First" },
    { id: 2, slug: "second", name: "Second" },
  ] });
  const originalCall = client.call.bind(client);
  client.call = async (request) => {
    if (request.function === "projects.github_binding.status") {
      client.requests.push(request);
      return okEnvelope(request.payload.project === "2" && bound
        ? boundStatusFixture() : { ...UNBOUND_STATUS, github_repo: "" });
    }
    if (request.function === "projects.github_binding.unbind") {
      client.requests.push(request);
      bound = false;
      return okEnvelope({ ...UNBOUND_STATUS, github_repo: "",
        sync_mode_notice: "Issue sync was turned off. To turn it back on, bind a repository again, " +
          "then run yoke projects update --slug first --name First --github-sync-mode enabled.",
      });
    }
    return originalCall(request);
  };
  return client;
}

test("single project view counts bindings outside the mapping scope", async (t) => {
  const client = mappingClient();
  const { root, mounted } = await mountGithub(t, client, {
    capabilities: modeCapabilities("hosted", {
      installations: [{ installationId: "31", boundProjects: 0 }],
      detachInstallation: { label: "Detach", onInvoke() { throw Error("must stay disabled"); } },
    }),
  });
  assert.deepEqual(client.requests.filter((r) => r.function.endsWith(".status"))
    .map((r) => r.payload.project), ["1", "2"]);
  assert.equal(buttons(root, "Detach")[0].disabled, true);
  assert.equal(buttons(root, "Unbind").length, 0);
  mounted.unmount();
});

test("Unbind confirms, removes the mapping, updates counts and teaches sync recovery", async (t) => {
  let bound = true;
  const client = githubClient(boundStatusFixture());
  const originalCall = client.call.bind(client);
  client.call = async (request) => {
    if (request.function === "projects.github_binding.status") {
      return okEnvelope(bound ? boundStatusFixture() : { ...UNBOUND_STATUS, github_repo: "" });
    }
    if (request.function === "projects.github_binding.unbind") {
      client.requests.push(request);
      bound = false;
      return okEnvelope({ ...UNBOUND_STATUS, github_repo: "",
        sync_mode_notice: "Issue sync was turned off. To turn it back on, bind a repository again, " +
          "then run yoke projects update --slug first --name First --github-sync-mode enabled.",
      });
    }
    return originalCall(request);
  };
  const { root, mounted } = await mountGithub(t, client, {
    capabilities: modeCapabilities("hosted", {
      installations: [{ installationId: "31", boundProjects: 1 }],
      detachInstallation: { label: "Detach", onInvoke() {} },
    }),
  });
  await click(buttons(root, "Unbind")[0]);
  assert.match(viewText(root), /capability and secrets/);
  assert.equal(client.requests.filter((r) => r.function.endsWith(".unbind")).length, 0);
  await click(buttons(root, "Cancel")[0]);
  assert.equal(buttons(root, "Confirm unbind").length, 0);
  await click(buttons(root, "Unbind")[0]);
  await click(buttons(root, "Confirm unbind")[0]);
  assert.deepEqual(client.requests.filter((r) => r.function.endsWith(".unbind")), [
    { function: "projects.github_binding.unbind", payload: { project: "1" } },
  ]);
  assert.equal(buttons(root, "Unbind").length, 0);
  assert.doesNotMatch(viewText(root), /example-org\/example-repo/);
  assert.match(viewText(root), /Issue sync was turned off/);
  assert.match(viewText(root), /bind a repository again/);
  assert.match(viewText(root), /--slug first --name First --github-sync-mode enabled/);
  assert.equal(buttons(root, "Detach")[0].disabled, false);
  mounted.unmount();
});


for (const scope of ["all", ["1"]]) {
  for (const hostRows of [[], [{ installationId: "99", accountLogin: "spare" }],
    [{ installationId: "31", accountLogin: "host-account", boundProjects: 0 }]]) {
    test(`hosted installation rows retain every binding: scope=${scope}, host=${hostRows.length ? hostRows[0].installationId : "empty"}`, async () => {
      const documentNode = new FakeDocument();
      const main = documentNode.createElement("main");
      const projects = [{ id: 1, name: "First" }, { id: 2, name: "Second" }];
      renderGithubView({
        document: documentNode, isMounted: () => true,
        projects: () => projects, client: githubClient(boundStatusFixture()),
        capabilities: modeCapabilities("hosted", {
          installations: hostRows,
          detachInstallation: { label: "Detach", onInvoke() { throw Error("bound"); } },
        }),
      }, main, scope);
      await settle();
      const rows = allNodes(main.children[0]).filter((node) => node.tagName === "TR");
      const boundRows = rows.filter((row) => allNodes(row.children[1] || row)
        .some((node) => node.textContent === "31"));
      assert.equal(boundRows.length, 1, "one card row per bound installation");
      const row = boundRows[0];
      assert.ok(allNodes(row.children[4]).some((node) => node.textContent === "2"),
        "card count includes both bindings even in one-project scope");
      assert.equal(allNodes(row).find((node) => node.tagName === "BUTTON" &&
        node.textContent === "Detach").disabled, true);
      const missing = !hostRows.some((host) => host.installationId === "31");
      assert.equal(allNodes(row).some((node) => node.textContent.includes(
        "absent from the hosted installation list")), missing);
      assert.equal(rows.length, 2 + (hostRows.some((host) => host.installationId === "99") ? 1 : 0));
    });
  }
}
