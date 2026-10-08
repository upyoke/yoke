import assert from "node:assert/strict";
import test from "node:test";
import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { FakeDocument, allNodes, byClass, response, settle } from "./universe_ui_dom_test_support.mjs";
import { multiProjectWorkbenchClient } from "./universe_ui_workbench_test_support.mjs";

async function navigate(documentNode, href) {
  documentNode.defaultView.location.href = href;
  documentNode.defaultView.dispatchEvent(new Event("popstate"));
  await settle();
}
function setup(t, href, sections, universeId) {
  const previousFetch = globalThis.fetch;
  t.after(() => { globalThis.fetch = previousFetch; });
  globalThis.fetch = () => response(200, {});
  const documentNode = new FakeDocument();
  documentNode.defaultView.location.href = href;
  const root = documentNode.createElement("div");
  const contexts = [], nodes = [];
  const factory = (context) => {
    contexts.push(context);
    const node = documentNode.createElement("aside");
    node.textContent = JSON.stringify(context.scope);
    nodes.push(node);
    return node;
  };
  const client = multiProjectWorkbenchClient();
  const call = client.call.bind(client);
  client.call = async (request, init) => {
    const result = await call(request, init);
    if (request.function === "projects.list") result.envelope.result.rows.push({ id: 3, slug: "third", name: "Third" });
    return result;
  };
  const mounted = mountUniverseApp(root, {
    universeId, client, sections: sections(factory, documentNode),
  });
  return { documentNode, root, contexts, nodes, mounted };
}

test("section factories follow All, multi selection, held rescope, routes and unmount", async (t) => {
  const state = setup(t, "/frontier?project=1", (factory) => ({ frontier: factory, github: factory }), "selected-universe");
  const { documentNode, root, contexts, nodes, mounted } = state;
  assert.equal(contexts.length, 0, "factory waits for resolved scope");
  await settle();
  assert.equal(contexts[0].universeId, "selected-universe");
  assert.deepEqual(contexts[0].scope, ["1"]);
  assert.deepEqual(contexts[0].projectSelection, ["1"]);
  for (const [href, scope] of [["/frontier?project=1,2", ["1", "2"]], ["/frontier?project=all", "all"], ["/github?project=2", ["2"]]]) {
    const prior = contexts.at(-1), priorNode = nodes.at(-1);
    await navigate(documentNode, href);
    assert.equal(prior.signal.aborted, true);
    assert.deepEqual(contexts.at(-1).scope, scope);
    assert.equal(contexts.at(-1).signal.aborted, false);
    assert.equal(priorNode.parentNode, null);
    assert.ok(allNodes(root).includes(nodes.at(-1)));
  }
  mounted.unmount();
  assert.equal(contexts.at(-1).signal.aborted, true);
  assert.equal(nodes.at(-1).parentNode, null);
});

test("beforeScope factories receive selection and can return the same reusable node", async (t) => {
  let shared;
  const state = setup(t, "/frontier", (factory, documentNode) => {
    shared = documentNode.createElement("aside");
    return { frontier: { placement: "beforeScope", content(context) { factory(context); return shared; } } };
  });
  await settle();
  assert.equal(state.contexts[0].universeId, null);
  assert.equal(state.contexts[0].scope, "all");
  await navigate(state.documentNode, "/frontier?project=2");
  assert.deepEqual(state.contexts.at(-1).projectSelection, ["2"]);
  assert.ok(allNodes(state.root).includes(shared));
  assert.ok(!allNodes(byClass(state.root, "view-host")[0]).includes(shared));
  state.mounted.unmount();
  assert.equal(shared.parentNode, null);
});

test("unscoped host-fed sections cancel on universe remount", async (t) => {
  const state = setup(t, "/members", (factory) => ({ members: factory }), "first");
  await settle();
  assert.equal(state.contexts[0].scope, null);
  state.mounted.unmount();
  const next = mountUniverseApp(state.root, {
    universeId: "second", client: multiProjectWorkbenchClient(),
    sections: { members(context) { state.contexts.push(context); return state.documentNode.createElement("aside"); } },
  });
  await settle();
  assert.equal(state.contexts[0].signal.aborted, true);
  assert.equal(state.contexts.at(-1).universeId, "second");
  next.unmount();
  assert.equal(state.contexts.at(-1).signal.aborted, true);
});

test("null sections can appear after in-place scope changes and failures teach recovery", async (t) => {
  let fail = false;
  const state = setup(t, "/frontier", (factory) => ({ frontier(context) {
    factory(context);
    if (fail) throw new Error("panel unavailable");
    return context.scope === "all" ? null : factory(context);
  } }));
  await settle();
  await navigate(state.documentNode, "/frontier?project=1");
  assert.ok(allNodes(state.root).includes(state.nodes.at(-1)));
  fail = true;
  await navigate(state.documentNode, "/frontier?project=2");
  assert.match(byClass(state.root, "error-banner").at(-1).textContent, /host_section_render_failed.*panel unavailable.*reload/);
  assert.equal(state.contexts.at(-1).signal.aborted, true);
  state.mounted.unmount();
});
