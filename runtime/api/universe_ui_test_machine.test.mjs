import assert from "node:assert/strict";
import test from "node:test";

import { renderTestMachineDetail } from
  "../../packages/yoke-core/src/yoke_core/ui/static/universe_view_test_machine.js";
import { machineRelativeAge } from
  "../../packages/yoke-core/src/yoke_core/ui/static/test_machine_view_primitives.js";
import {
  FakeDocument,
  allNodes,
  byClass,
  settle,
} from "./universe_ui_dom_test_support.mjs";

import {
  context,
  detail,
  text,
} from "./universe_ui_test_machine_test_support.mjs";

test("machine timestamps use compact prototype-relative labels", () => {
  const now = Date.parse("2026-07-26T16:11:00Z");
  assert.equal(machineRelativeAge("2026-07-26T16:00:00Z", now), "11m");
  assert.equal(machineRelativeAge("2026-07-26T15:00:00Z", now), "1h");
  assert.equal(machineRelativeAge("2026-07-24T15:00:00Z", now), "2d");
  assert.equal(machineRelativeAge(null, now), "recently");
});

test("Test Mac detail matches capability, lease, method, and receipt prototype", async () => {
  const prepared = context();
  const main = prepared.documentNode.createElement("main");
  await renderTestMachineDetail(prepared.value, main, "yoke");

  const rendered = text(main);
  const header = byClass(main, "test-machine-head")[0];
  assert.equal(header.classList.contains("page-head"), true);
  assert.equal(byClass(header, "title")[0].textContent, "Test Mac");
  assert.equal(
    byClass(header, "test-machine-actions")[0]
      .classList.contains("head-actions"),
    true,
  );
  assert.equal(
    byClass(main, "test-machine-columns")[0].classList.contains("split"),
    true,
  );
  assert.match(rendered, /test-machine:mac-mini-lab · composite · yoke/);
  assert.match(rendered, /Terminal\.app · PTY · screenshots · post-install shell/);
  assert.match(rendered, /fresh-host · shell-preconfigured/);
  assert.match(
    rendered,
    /run inside the lease; each verifies the branch-determining state it promises/,
  );
  assert.match(rendered, /1 · serial/);
  assert.match(rendered, /3 \/ 3 checks/);
  assert.match(rendered, /YOK-2001/);
  assert.doesNotMatch(rendered, /Prove the installer campaign/);
  assert.doesNotMatch(rendered, /session-machine/);
  assert.equal(
    byClass(byClass(main, "test-machine-availability-state")[0], "run").length,
    1,
  );
  const availability = byClass(
    main, "test-machine-availability-state",
  )[0];
  assert.equal(availability.classList.contains("lease"), true);
  assert.equal(
    byClass(availability, "test-machine-lease-bar")[0]
      .classList.contains("bar"),
    true,
  );
  assert.equal(
    byClass(main, "test-machine-availability-body")[0]
      .classList.contains("stack"),
    true,
  );
  assert.match(rendered, /Terminal check/);
  assert.match(rendered, /Terminal inspection/);
  assert.match(rendered, /Machine state check/);
  assert.match(rendered, /Credential references/);
  assert.doesNotMatch(rendered, /top-secret/);
  // Scoped to its panel: the operations panel reuses the row class for the
  // same timeline treatment, so a page-wide count drifts as receipts land.
  const receiptBody = byClass(main, "test-machine-receipt-body")[0];
  assert.equal(byClass(receiptBody, "test-machine-check").length, 4);
  assert.match(rendered, /SSH \+ runner materialization/);
  assert.match(rendered, /sample artifact discarded after verification/);
  assert.match(rendered, /Host baselines reached \+ verified/);
  assert.match(
    rendered,
    /asserted the branch-determining state itself, never a proxy/,
  );
  assert.equal(byClass(receiptBody, "timeline-dot").length, 4);
  assert.equal(byClass(main, "test-machine-stat").length, 3);
  assert.equal(
    byClass(main, "test-machine-stats")[0].classList.contains("mini-grid"),
    true,
  );
  for (const card of byClass(main, "test-machine-stat")) {
    assert.equal(card.classList.contains("mini"), true);
    assert.equal(byClass(card, "mh").length, 1);
    assert.equal(byClass(card, "mv").length, 1);
  }
  assert.equal(
    byClass(main, "test-machine-methods-body")[0]
      .classList.contains("stack"),
    true,
  );
  for (const method of byClass(main, "test-machine-method")) {
    assert.equal(method.classList.contains("doc-link"), true);
    assert.equal(
      byClass(method, "test-machine-method-icon")[0]
        .classList.contains("cc-ico"),
      true,
    );
    assert.equal(byClass(method, "dl-main").length, 1);
    assert.equal(byClass(method, "dl-title").length, 1);
    assert.equal(byClass(method, "dl-sub").length, 1);
  }
  assert.equal(
    byClass(main, "test-machine-receipt-body")[0]
      .classList.contains("timeline"),
    true,
  );
  for (const receipt of byClass(main, "test-machine-check")) {
    assert.equal(receipt.classList.contains("tl"), true);
  }
  assert.deepEqual(
    byClass(main, "test-machine-method").map((node) =>
      text(byClass(node, "pill")[0])),
    ["ready", "ready", "ready"],
  );
  assert.deepEqual(
    byClass(main, "test-machine-secret").map((node) =>
      text(byClass(node, "mono")[0])),
    ["ssh_private_key"],
  );
  assert.deepEqual(
    byClass(main, "test-machine-kv").flatMap((node) =>
      byClass(node, "mono").map((value) => value.textContent)),
    [
      "test-mac.local",
      "yoke-test",
      "mac-ssh",
      "fresh-host",
      "shell-preconfigured",
      "host_control",
    ],
  );
  assert.match(
    rendered,
    /passed verification without returning secret values/,
  );
  assert.deepEqual(
    byClass(main, "test-machine-method").map((node) => node.href),
    [
      "#/qa-methods/terminal-check?project=1",
      "#/qa-methods/terminal-inspection?project=1",
      "#/qa-methods/machine-state-check?project=1",
    ],
  );
});

test("availability mirrors verification state instead of lease presence alone", async () => {
  const prepared = context();
  const main = prepared.documentNode.createElement("main");
  const original = detail.verification.status;
  const originalLease = detail.active_lease;
  detail.verification.status = "configured_unverified";
  detail.active_lease = null;
  try {
    await renderTestMachineDetail(prepared.value, main, "yoke");
    const availability = text(byClass(
      main, "test-machine-availability-state",
    )[0]);
    assert.match(availability, /configured \(unverified\)/);
    assert.doesNotMatch(availability, /\bready\b/);
    assert.equal(
      byClass(
        byClass(main, "test-machine-availability-state")[0],
        "warn",
      ).length,
      1,
    );
  } finally {
    detail.verification.status = original;
    detail.active_lease = originalLease;
  }
});

test("verification errors use the critical callout treatment", async () => {
  const prepared = context();
  const main = prepared.documentNode.createElement("main");
  const original = detail.verification.status;
  detail.verification.status = "error";
  try {
    await renderTestMachineDetail(prepared.value, main, "yoke");
    const callout = byClass(main, "test-machine-callout")[0];
    assert.equal(callout.classList.contains("error"), true);
    assert.equal(callout.classList.contains("warn"), false);
    assert.match(text(callout), /Verification failed/);
  } finally {
    detail.verification.status = original;
  }
});

test("a rejected Test Mac read renders an error instead of loading forever", async () => {
  const documentNode = new FakeDocument();
  const main = documentNode.createElement("main");
  await renderTestMachineDetail({
    document: documentNode,
    isMounted: () => true,
    client: {
      async call() {
        throw new Error("network unavailable");
      },
    },
  }, main, "yoke");

  const rendered = text(main);
  assert.match(rendered, /read failed \(HTTP 0\): Error: network unavailable/);
  assert.doesNotMatch(rendered, /loading Test Mac/);
});

test("settings modal keeps secrets terminal-only and invalidates through typed write", async () => {
  const prepared = context();
  const main = prepared.documentNode.createElement("main");
  await renderTestMachineDetail(prepared.value, main, "yoke");
  const edit = allNodes(main).find((node) => node.textContent === "Edit settings");
  edit.dispatchEvent(new Event("click"));

  assert.equal(byClass(main, "test-machine-dialog").length, 1);
  const dialog = byClass(main, "test-machine-dialog")[0];
  assert.equal(
    dialog.attributes.get("aria-label"),
    "Edit Test Mac mac-mini-lab settings",
  );
  const rendered = text(main);
  assert.match(rendered, /Secret values never enter the browser/);
  assert.match(
    rendered,
    /The SSH key is the only credential/,
  );
  assert.match(
    rendered,
    /macOS Automation and Screen Recording are host permissions, not tokens/,
  );
  assert.match(
    rendered,
    /capability secret set --project yoke --cap-type test-machine/,
  );
  assert.match(rendered, /--key ssh_private_key --value-stdin/);
  assert.match(rendered, /runner subprocess only/);
  assert.doesNotMatch(rendered, /sudo_password/);
  assert.doesNotMatch(rendered, /screen_control_token/);
  assert.match(rendered, /stored/);
  assert.match(rendered, /registered runner operations/);
  assert.equal(byClass(main, "test-machine-command").length, 1);
  assert.equal(
    byClass(byClass(main, "test-machine-command")[0], "good").length,
    1,
  );

  const save = allNodes(main).find(
    (node) => node.textContent === "Save non-secret settings",
  );
  save.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(
    prepared.requests.some(
      (request) => request.function === "test_machine.settings_replace" &&
        request.payload.machine === "mac-mini-lab",
    ),
    true,
  );
});

test("Test Mac fleet chooser opens the selected machine", async () => {
  const second = structuredClone(detail);
  second.machine = "mac-studio-lab";
  second.capability_type = "test-machine:mac-studio-lab";
  second.display_name = "Test Mac · mac-studio-lab";
  second.settings.resource_name = second.machine;
  second.settings.host = "mac-studio-lab.local";
  const prepared = context([detail, second]);
  const main = prepared.documentNode.createElement("main");
  await renderTestMachineDetail(prepared.value, main, "yoke");

  assert.match(text(main), /Choose a machine to inspect/);
  const choose = byClass(main, "test-machine-method")[1];
  choose.dispatchEvent(new Event("click"));
  await settle();
  assert.match(text(main), /mac-studio-lab\.local/);
  assert.equal(
    prepared.requests.some((request) =>
      request.function === "test_machine.get" &&
      request.payload.machine === second.machine),
    true,
  );
});

test("settings modal closes from its overlay", async () => {
  const prepared = context();
  const main = prepared.documentNode.createElement("main");
  await renderTestMachineDetail(prepared.value, main, "yoke");
  const edit = allNodes(main).find((node) => node.textContent === "Edit settings");
  edit.dispatchEvent(new Event("click"));

  const overlay = byClass(main, "test-machine-overlay")[0];
  overlay.dispatchEvent(new Event("click"));
  assert.equal(byClass(main, "test-machine-dialog").length, 0);
});

test("Verify now calls the registered verifier, never a browser-side recipe", async () => {
  const prepared = context();
  const main = prepared.documentNode.createElement("main");
  await renderTestMachineDetail(prepared.value, main, "yoke");
  const verify = allNodes(main).find((node) => node.textContent === "Verify now");
  verify.dispatchEvent(new Event("click"));
  await settle();
  assert.equal(
    prepared.requests.some(
      (request) => request.function === "test_machine.verify",
    ),
    true,
  );
});

test("Verify now announces a rejected verifier call and recovers", async () => {
  const prepared = context();
  const main = prepared.documentNode.createElement("main");
  await renderTestMachineDetail(prepared.value, main, "yoke");
  prepared.value.client.call = async (request) => {
    if (request.function === "test_machine.verify") {
      throw new Error("verification transport unavailable");
    }
    throw new Error(`unexpected function ${request.function}`);
  };
  const verify = allNodes(main).find((node) => node.textContent === "Verify now");
  verify.dispatchEvent(new Event("click"));
  await settle();

  const status = byClass(main, "test-machine-action-status")[0];
  assert.equal(status.attributes.get("role"), "alert");
  assert.equal(status.attributes.get("aria-live"), "assertive");
  assert.match(status.textContent, /verification transport unavailable/);
  assert.equal(verify.disabled, false);
  assert.equal(verify.attributes.get("aria-busy"), "false");
  assert.equal(verify.textContent, "Verify now");
});
