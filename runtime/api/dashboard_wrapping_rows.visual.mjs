// Render the real dashboard styles and Delivery primitive in Chromium.
// Usage: node dashboard_wrapping_rows.visual.mjs PLAYWRIGHT_MODULE OUTPUT_DIR
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const [playwrightModule, outputDir] = process.argv.slice(2);
assert(playwrightModule && outputDir, "Name PLAYWRIGHT_MODULE and OUTPUT_DIR.");
const { chromium } = createRequire(import.meta.url)(playwrightModule);
const staticRoot = fileURLToPath(new URL(
  "../../packages/yoke-core/src/yoke_core/ui/static/", import.meta.url,
));
const entry = await readFile(path.join(staticRoot, "index.html"), "utf8");
const styles = [...entry.matchAll(/href="(?:\.\/|\/)assets\/([^\"]+\.css)"/g)]
  .map((match) => match[1]);
assert(styles.length, "Source index must declare its stylesheet roster.");
const flowName = "yoke-hosted-production-release-qa";
const rows = [
  ["Session identity", "session-top", "session-operator"],
  ["Machine fact", "machine-detail-fact", ""],
  ["Card header", "secondary-card-header", "event-time"],
  ["Section heading", "panel-header", ""],
  ["Review actions", "review-foot", "review-actions"],
  ["Workflow actions", "page-head", "head-actions"],
  ["Strategy metadata", "strategy-doc-metadata", "strategy-doc-age"],
  ["Item toolbar", "item-roster-toolbar", ""],
  ["Run decision", "run-decision-ask", ""],
  ["Session message", "session-message-header", "session-message-recipient-status"],
  ["Runtime identity", "runtime-identity-help-row", "runtime-identity-help-value"],
  ["Editor actions", "instruction-editor-actions", ""],
  ["Form actions", "item-form-actions", ""],
  ["Dialog actions", "workflow-dialog-footer actions-only", ""],
  ["Test machine dialog", "test-machine-dialog-actions", ""],
  ["Review buttons", "review-actions", ""],
];
const html = (assets) => `<!doctype html><html><head>
  ${styles.map((name) => `<link rel="stylesheet" href="${assets}${name}">`).join("\n")}
  <style>
    body { padding: 20px; margin: 0; }
    .proof { width: var(--proof-width); margin: 0 0 18px; }
    .proof-label { font: 12px sans-serif; margin-bottom: 6px; }
    .proof-row { padding: 10px; border: 1px solid #b8b8b8; gap: 10px; }
    .proof-footer { font: 12px sans-serif; }
  </style></head><body><main class="universe-app-root">
  <div id="delivery" class="proof"></div>
  <div id="specimens"></div>
  <footer class="proof-footer">Styles: candidate checkout;
    fixture data; no control-plane universe</footer>
  </main><script type="module">
    import { workflowPanel } from "${assets}workflow_view_primitives.js";
    import { renderInboxView } from "${assets}universe_views_inbox.js";
    import { qaPanel } from "${assets}qa_view_primitives.js";
    const { panel } = workflowPanel(document, "Delivery", { detail: ${JSON.stringify(flowName)} });
    document.getElementById("delivery").append(panel, qaPanel(document, "Test plans", 2).root);
    const samples = ${JSON.stringify(rows)};
    for (const [label, rowClass, trailingClass] of samples) {
      const specimen = document.createElement("section");
      specimen.className = "proof";
      specimen.innerHTML = '<div class="proof-label"></div>';
      specimen.firstChild.textContent = label;
      const row = document.createElement("div");
      row.className = rowClass + " proof-row";
      const first = document.createElement("span");
      first.textContent = "Current execution context";
      if (label === "Runtime identity") first.className = "runtime-identity-help-label";
      const trailing = document.createElement("span");
      trailing.className = trailingClass;
      trailing.textContent = "Production deployment owner";
      row.append(first, trailing);
      specimen.append(row);
      document.getElementById("specimens").append(specimen);
    }
    const inbox = document.createElement("section");
    inbox.className = "proof inbox-message";
    inbox.innerHTML = '<div class="inbox-message-main">Inbox message</div>' +
      '<div class="inbox-message-sender"><div class="inbox-message-meta">' +
      'Production deployment reviewer with a long name</div></div>';
    document.getElementById("specimens").append(inbox);
    const inboxHost = document.createElement("section");
    inboxHost.className = "proof";
    document.getElementById("specimens").append(inboxHost);
    const subject = { run_id: "sample-release", stage: "approve",
      carried: { items: [{ item_id: 17, ref: "DEMO-17", title: "Dashboard corrections" }], commits: [] },
      release_effect: { consequence: "deploys", headline: "Deploy dashboard corrections" } };
    const rows = [{ id: 1, kind: "deployment_stage_approval", status: "pending", project_id: 1,
      subject_context: subject, actions: ["approve", "reject"], can_act: true },
      { id: 2, kind: "deployment_stage_approval", status: "resolved", project_id: 1,
      subject_context: subject, actions: [], can_act: false, decided_by_you: true, your_decision: { action: "approve" } }];
    renderInboxView({ document, isMounted: () => true, projects: () => [{ id: 1, slug: "Demo" }],
      client: { call: async (request) => ({ status: 200, envelope: { success: true,
        result: request.function === "inbox.list" ? { needs_decision: rows, messages: [] } : { rows: [] } } }) } }, inboxHost, "all");
    window.proofReady = true;
  </script></body></html>`;

const server = createServer(async (request, response) => {
  try {
    if (request.url === "/") {
      response.setHeader("Content-Type", "text/html");
      response.end(html("/assets/"));
      return;
    }
    const name = new URL(request.url, "http://localhost").pathname.slice("/assets/".length);
    assert(!name.includes("/") && !name.includes(".."), "Invalid asset path");
    response.setHeader("Content-Type", name.endsWith(".js") ? "text/javascript" : "text/css");
    response.end(await readFile(path.join(staticRoot, name)));
  } catch (error) {
    response.statusCode = 500;
    response.end(String(error));
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
await mkdir(outputDir, { recursive: true });
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 800, height: 1000 } });
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.waitForFunction(() => window.proofReady
    && document.querySelector('[data-fold="section:inbox-waiting"] .approval-carried'));
  for (const width of [268, 350, 1100]) {
    await page.setViewportSize({ width: width + 40, height: 1000 });
    await page.evaluate((value) => {
      document.documentElement.style.setProperty("--proof-width", `${value}px`);
    }, width);
    const result = await page.evaluate(() => {
      const delivery = document.querySelector(".workflow-panel-header");
      const meta = document.querySelector(".workflow-panel-meta");
      const left = (node) => node.getBoundingClientRect().left;
      const measurements = [...document.querySelectorAll(".proof-row")].map((row) => {
        const [first, trailing] = row.children;
        const style = getComputedStyle(row);
        return { label: row.parentElement.firstChild.textContent,
          wrapped: trailing.getBoundingClientRect().top >= first.getBoundingClientRect().bottom - 1,
          offset: left(trailing) - left(first), align: getComputedStyle(trailing).textAlign,
          rightGap: row.getBoundingClientRect().right - trailing.getBoundingClientRect().right
            - parseFloat(style.paddingRight) - parseFloat(style.borderRightWidth),
          rowRightGap: row.parentElement.getBoundingClientRect().right - row.getBoundingClientRect().right,
          rowLeftGap: row.getBoundingClientRect().left - row.parentElement.getBoundingClientRect().left };
      });
      return {
        captions: document.querySelectorAll(".qa-panel-context,.panel-hint").length,
        pendingCarried: document.querySelector('[data-fold="section:inbox-waiting"] .approval-carried') !== null,
        decidedCarried: document.querySelector('[data-fold="section:inbox-decided"] .approval-carried') !== null,
        decidedControls: document.querySelectorAll('[data-fold="section:inbox-decided"] .review-action').length,
        measurements,
        overflowing: [...document.querySelectorAll(".proof")].filter((node) => node.scrollWidth > node.clientWidth + 1).length,
        inboxAlign: getComputedStyle(document.querySelector(".inbox-message-meta")).textAlign,
      };
    });
    await page.screenshot({ path: path.join(outputDir, `wrapping-${width}.png`), fullPage: true });
    console.log(JSON.stringify({ width, ...result }));
    assert.equal(result.captions, 0);
    assert.equal(result.pendingCarried, true);
    assert.equal(result.decidedCarried, false);
    assert.equal(result.decidedControls, 0);
    assert.equal(result.inboxAlign, "left");
    assert.equal(result.overflowing, 0, `Overflow at ${width}px`);
    for (const row of result.measurements) {
      assert.equal(row.align, "left", row.label);
      if (width === 268) assert(row.wrapped, `${row.label} must exercise a second line`);
      if (row.wrapped) {
        assert(Math.abs(row.offset) < 1, `${row.label} second line is indented`);
        assert(Math.abs(row.rowLeftGap) < 1, `${row.label} wrapped row is indented`);
      }
      else if (["Runtime identity", "Editor actions", "Form actions", "Dialog actions", "Test machine dialog", "Review buttons"].includes(row.label)) {
        assert(Math.abs(row.rightGap) < 1, `${row.label} fitting content must reach the right edge`);
        assert(Math.abs(row.rowRightGap) < 1, `${row.label} fitting row must reach the right edge`);
      }
    }
  }
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
