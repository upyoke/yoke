import assert from "node:assert/strict";
import test from "node:test";
import { byClass, settle } from "./universe_ui_dom_test_support.mjs";
import { classText } from "./universe_ui_workflows_test_support.mjs";
import {
  buttonByText, checkboxRows, mountPanel, toggle,
} from "./universe_ui_instruction_test_support.mjs";

const point = (host, name) => byClass(host, `instruction-${name}`)[0].children[0];
const buckets = (host) => checkboxRows(host, "instruction-stage-bucket-checkbox");
const chooseBucket = (host, name, checked = true) => toggle(
  buckets(host).find((row) => row.label === name).input, checked,
);
const writeRequests = (client) => client.requests.filter(
  (request) => request.function !== "workflow.execution_instruction.list",
);

test("new instructions default to creation and read delivery with disabled buckets", async () => {
  const { host } = await mountPanel();
  buttonByText(host, "New instruction").dispatchEvent(new Event("click"));
  assert.equal(point(host, "before-creation").checked, true);
  assert.equal(point(host, "on-every-read").checked, true);
  assert.equal(point(host, "when-entering-stage").checked, false);
  assert.deepEqual(buckets(host).map((row) => row.label), [
    "idea", "planning", "refined", "implementing", "reviewing", "implemented", "release",
  ]);
  assert.ok(buckets(host).every((row) => row.input.disabled && !row.input.checked));
});

test("invalid delivery sends no writes and the editor teaches how to recover", async () => {
  const { host, client } = await mountPanel();
  buttonByText(host, "New instruction").dispatchEvent(new Event("click"));
  toggle(point(host, "before-creation"), false);
  toggle(point(host, "on-every-read"), false);
  const save = buttonByText(host, "Create instruction");
  save.dispatchEvent(new Event("click"));
  await settle();
  const error = byClass(host, "instruction-editor-error")[0];
  assert.match(error.textContent, /delivery_point_required: select/);
  assert.equal(error.hidden, false);
  assert.equal(save.disabled, false);
  assert.deepEqual(writeRequests(client), []);

  toggle(point(host, "when-entering-stage"), true);
  assert.ok(buckets(host).every((row) => !row.input.disabled));
  save.dispatchEvent(new Event("click"));
  await settle();
  assert.match(error.textContent, /stage_bucket_required: select at least one/);
  assert.deepEqual(writeRequests(client), []);

  chooseBucket(host, "implementing");
  chooseBucket(host, "reviewing");
  const content = byClass(host, "instruction-content-input")[0];
  content.value = "Check the candidate.";
  content.dispatchEvent(new Event("input"));
  save.dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(writeRequests(client)[0].payload, {
    content: "Check the candidate.",
    before_creation: false, on_every_read: false, when_entering_stage: true,
    stage_buckets: ["implementing", "reviewing"],
  });
  assert.deepEqual(classText(host, "workflow-instruction-delivery"), [
    "When entering stage: implementing, reviewing",
  ]);
});

test("editing loads delivery, retains disabled buckets, and saves replacements", async () => {
  const { host, client } = await mountPanel({ seed: [{
    id: 24, content: "Check the release.",
    before_creation: false, on_every_read: false, when_entering_stage: true,
    stage_buckets: ["implemented", "release"],
  }] });
  assert.deepEqual(classText(host, "workflow-instruction-delivery"), [
    "When entering stage: implemented, release",
  ]);
  buttonByText(host, "Edit").dispatchEvent(new Event("click"));
  assert.equal(point(host, "before-creation").checked, false);
  assert.equal(point(host, "on-every-read").checked, false);
  assert.equal(point(host, "when-entering-stage").checked, true);
  toggle(point(host, "when-entering-stage"), false);
  assert.ok(buckets(host).every((row) => row.input.disabled));
  assert.deepEqual(buckets(host).filter((row) => row.input.checked).map((row) => row.label), [
    "implemented", "release",
  ]);
  toggle(point(host, "when-entering-stage"), true);
  chooseBucket(host, "implemented", false);
  chooseBucket(host, "planning");
  toggle(point(host, "before-creation"), true);
  buttonByText(host, "Save instruction").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(writeRequests(client)[0].payload, {
    instruction_id: 24, content: "Check the release.",
    before_creation: true, on_every_read: false, when_entering_stage: true,
    stage_buckets: ["release", "planning"],
  });
  buttonByText(host, "Edit").dispatchEvent(new Event("click"));
  assert.deepEqual(buckets(host).filter((row) => row.input.checked).map((row) => row.label), [
    "planning", "release",
  ]);
  toggle(point(host, "when-entering-stage"), false);
  buttonByText(host, "Save instruction").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(classText(host, "workflow-instruction-delivery"), ["Before creation"]);
  assert.deepEqual(writeRequests(client)[2].payload.stage_buckets, ["release", "planning"]);
});

test("server save refusals stay in the editor with draft delivery intact", async () => {
  const { host, client } = await mountPanel({ seed: [{
    id: 10, content: "Read guidance.", before_creation: true, on_every_read: true,
    when_entering_stage: false, stage_buckets: [],
  }] });
  const call = client.call.bind(client);
  client.call = async (request) => request.function === "workflow.execution_instruction.update"
    ? { status: 400, envelope: { success: false, error: {
      message: "delivery_invalid: select at least one stage bucket",
    } } } : call(request);
  buttonByText(host, "Edit").dispatchEvent(new Event("click"));
  toggle(point(host, "when-entering-stage"), true);
  chooseBucket(host, "idea");
  buttonByText(host, "Save instruction").dispatchEvent(new Event("click"));
  await settle();
  const error = byClass(host, "instruction-editor-error")[0];
  assert.equal(error.hidden, false);
  assert.match(error.textContent, /delivery_invalid/);
  assert.equal(buttonByText(host, "Save instruction").disabled, false);
  assert.equal(point(host, "when-entering-stage").checked, true);
  assert.equal(buckets(host)[0].input.checked, true);
  assert.deepEqual(writeRequests(client), []);
});

test("the editor offers the served stage buckets and new-instruction defaults", async () => {
  const { host, client } = await mountPanel({ deliveryOptions: {
    stage_buckets: ["triage", "shipping"],
    defaults: {
      before_creation: false, on_every_read: false, when_entering_stage: true,
      stage_buckets: ["shipping"],
    },
  } });
  buttonByText(host, "New instruction").dispatchEvent(new Event("click"));
  assert.equal(point(host, "before-creation").checked, false);
  assert.equal(point(host, "on-every-read").checked, false);
  assert.equal(point(host, "when-entering-stage").checked, true);
  assert.deepEqual(buckets(host).map((row) => [row.label, row.input.checked]), [
    ["triage", false], ["shipping", true],
  ]);
  const content = byClass(host, "instruction-content-input")[0];
  content.value = "Ship it.";
  content.dispatchEvent(new Event("input"));
  buttonByText(host, "Create instruction").dispatchEvent(new Event("click"));
  await settle();
  assert.deepEqual(writeRequests(client)[0].payload, {
    content: "Ship it.", before_creation: false, on_every_read: false,
    when_entering_stage: true, stage_buckets: ["shipping"],
  });
});

test("a list without delivery options disables editing and names the recovery", async () => {
  const { host } = await mountPanel({
    seed: [{ id: 3, content: "Read guidance.", before_creation: true }],
    deliveryOptions: null,
  });
  assert.equal(buttonByText(host, "New instruction").disabled, true);
  assert.equal(buttonByText(host, "Edit").disabled, true);
  assert.deepEqual(classText(host, "workflow-instruction-delivery"), ["Before creation"]);
  assert.match(classText(host, "error")[0], /^delivery_options_unavailable: .*Deploy a Yoke build/);
});
