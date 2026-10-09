// Profile's Sign out: shown only when the host names where its browser
// session ends; clicking it posts there and leaves for the sign-in page.

import assert from "node:assert/strict";
import test from "node:test";

import { mountUniverseApp } from "../../packages/yoke-core/src/yoke_core/ui/static/app.js";
import { FakeDocument, allNodes, settle } from "./universe_ui_dom_test_support.mjs";

const PROFILE = {
  actor: { id: 2, kind: "human", name: "Ben" },
  identity: {},
  roles: { org: [], projects: [] },
  tokens: [],
  preferences: { time_zone: "" },
  onboarding: { hidden_count: 0 },
};

const client = {
  async call(request) {
    const results = {
      "organizations.get": { name: "Acme", slug: "acme" },
      "projects.list": { rows: [] },
      "profile.get": PROFILE,
    };
    if (!(request.function in results)) throw new Error(`unexpected function ${request.function}`);
    return { status: 200, envelope: { success: true, result: results[request.function] } };
  },
};

function signOutButton(root) {
  return allNodes(root).find((node) => node.tagName === "BUTTON" && node.textContent === "Sign out");
}

async function mountProfile(capabilities) {
  const documentNode = new FakeDocument();
  const view = documentNode.defaultView;
  view.location.href = "/profile";
  const posts = [], assigned = [];
  view.fetch = async (url, options = {}) => {
    if (options.method === "POST") posts.push(url);
    return { ok: true, json: async () => ({}) };
  };
  view.location.assign = (url) => assigned.push(url);
  const root = documentNode.createElement("div");
  const mounted = mountUniverseApp(root, { client, capabilities });
  await settle();
  await settle();
  return { root, mounted, posts, assigned };
}

test("a host holding a browser session offers Sign out, which ends it and leaves", async () => {
  const { root, mounted, posts, assigned } = await mountProfile(
    { data: { session: { signOutPath: "/v1/auth/sign-out" } } },
  );
  try {
    signOutButton(root).dispatchEvent(new Event("click"));
    await settle();
    assert.deepEqual(posts, ["/v1/auth/sign-out"]);
    assert.deepEqual(assigned, ["/"]);
  } finally { mounted.unmount(); }
});

test("a host without a browser session shows no Sign out", async () => {
  const { root, mounted } = await mountProfile({});
  try { assert.equal(signOutButton(root), undefined); } finally { mounted.unmount(); }
});
