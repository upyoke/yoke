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
  <div id="grids"></div>
  <footer class="proof-footer">Styles: candidate checkout;
    fixture data; no control-plane universe</footer>
  </main><script type="module">
    import { workflowPanel } from "${assets}workflow_view_primitives.js";
    import { renderInboxView } from "${assets}universe_views_inbox.js";
    import { qaPanel } from "${assets}qa_view_primitives.js";
    import { sessionCard } from "${assets}universe_views_sessions.js";
    // A steered worker carries the card's widest rows at once: identity,
    // model facts, the steering scope chip, and the latest-message badge.
    const steeredSession = (index) => ({
      session_id: "worker-" + index, liveness: "active", mode: "dash",
      turn_posture: "running", executor: "claude-code",
      executor_surface: "claude-desktop", executor_mark: "C",
      executor_class_name: "h-claude", execution_lane: "DARIUS",
      actor_label: "Production deployment owner", model: "claude-opus-5-5",
      model_effort: "medium", usage_tokens: 9300000, usage_cost_usd: 3.33,
      claims: [], holdings: { current: [], previous: [], previous_remainder: 0 },
      messageability: { messageable: true, relay_connected: true },
      relay: "connected", machine_name: "operator-workstation-sixteen-inch",
      latest_message: { created_at: new Date(Date.now() - 660000).toISOString(),
        message_id: "message-" + index, state: "acknowledged" },
      steering_group_session_id: "seat",
      steering_group_scope: { project: "platform", project_id: 1,
        scope: { project_id: 1 }, strategy_docs: [] },
    });
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
    inboxHost.id = "inbox-approvals";
    document.getElementById("specimens").append(inboxHost);
    const subject = { run_id: "sample-release", stage: "approve",
      carried: { items: [{ item_id: 17, ref: "DEMO-17", title: "Dashboard corrections" }], commits: [] },
      release_effect: { consequence: "deploys", headline: "Deploy dashboard corrections" } };
    const rows = [...Array.from({ length: 8 }, (_, index) => ({
      id: index + 1, kind: "deployment_stage_approval", status: "pending", project_id: 1,
      subject_context: { ...subject, run_id: "sample-release-" + (index + 1) },
      actions: ["approve", "reject"], can_act: true })),
      { id: 9, kind: "deployment_stage_approval", status: "resolved", project_id: 1,
      subject_context: subject, actions: [], can_act: false, decided_by_you: true, your_decision: { action: "approve" } }];
    renderInboxView({ document, isMounted: () => true, projects: () => [{ id: 1, slug: "Demo" }],
      client: { call: async (request) => ({ status: 200, envelope: { success: true,
        result: request.function === "inbox.list" ? { needs_decision: rows, messages: [] } : { rows: [] } } }) } }, inboxHost, "all");
    const gridKinds = [
      ["Sessions", "session-grid", "session-card"],
      ["Machines", "machines-grid", "machine-card"],
      ["Frontier", "work-card-grid", "work-item-card"],
      ["Strategy", "work-card-grid", "work-item-card"],
      ["Strategy documents", "strategy-doc-grid", "strategy-doc-card"],
      ["Work sessions", "work-session-grid", "session-card"],
      ["Shipping runs", "work-card-grid shipping-run-grid", "shipping-run-card"],
    ];
    for (const [label, gridClass, cardClass] of gridKinds) {
      const specimen = document.createElement("section");
      specimen.className = "proof grid-proof";
      specimen.dataset.label = label;
      const header = document.createElement("div");
      header.className = "panel-header";
      header.textContent = label;
      specimen.append(header);
      for (const count of [8, 1]) {
        const grid = document.createElement("div");
        grid.className = gridClass;
        for (let index = 0; index < count; index += 1) {
          const card = cardClass === "session-card"
            ? sessionCard(document, steeredSession(index), () => {},
              [{ id: 1, slug: "platform" }], new Map([["seat", "#7c3aed"]]))
            : document.createElement("article");
          if (cardClass !== "session-card") {
            card.className = cardClass;
            card.textContent = "Card " + (index + 1);
          }
          grid.append(card);
        }
        specimen.append(grid);
      }
      document.getElementById("grids").append(specimen);
    }
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
  for (const width of [268, 350, 1100, 1250, 1388]) {
    await page.setViewportSize({ width: width + 40, height: 1000 });
    await page.evaluate((value) => {
      document.documentElement.style.setProperty("--proof-width", `${value}px`);
    }, width);
    const result = await page.evaluate(() => {
      const delivery = document.querySelector(".workflow-panel-header");
      const meta = document.querySelector(".workflow-panel-meta");
      const left = (node) => node.getBoundingClientRect().left;
      const waiting = document.querySelector('[data-fold="section:inbox-waiting"]');
      const decided = document.querySelector('[data-fold="section:inbox-decided"]');
      const pendingCards = [...waiting.querySelectorAll(".review-card")];
      const sparseCard = decided.querySelector(".review-card").getBoundingClientRect();
      const header = waiting.querySelector("summary").getBoundingClientRect();
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
        inbox: {
          pendingCount: pendingCards.length,
          decidedCount: decided.querySelectorAll(".review-card").length,
          leftGap: pendingCards[0].getBoundingClientRect().left - header.left,
          rightGap: header.right - pendingCards[0].getBoundingClientRect().right,
          sparseLeftGap: sparseCard.left - header.left,
          sparseWidthGap: sparseCard.width - pendingCards[0].getBoundingClientRect().width,
          stacked: pendingCards.every((card, index) => !index
            || card.getBoundingClientRect().top >= pendingCards[index - 1].getBoundingClientRect().bottom),
        },
        grids: [...document.querySelectorAll(".grid-proof")].map((specimen) => {
          const [header, full, sparse] = specimen.children;
          const cards = [...full.children].map((card) => card.getBoundingClientRect());
          const firstRow = cards.filter((card) => Math.abs(card.top - cards[0].top) < 1);
          const sparseCard = sparse.firstChild.getBoundingClientRect();
          return { label: specimen.dataset.label, columns: firstRow.length,
            rightGap: header.getBoundingClientRect().right - firstRow.at(-1).right,
            leftGap: cards[0].left - header.getBoundingClientRect().left,
            sparseLeftGap: sparseCard.left - cards[0].left,
            sparseWidthGap: sparseCard.width - cards[0].width,
            overflowing: full.scrollWidth > full.clientWidth + 1
              || sparse.scrollWidth > sparse.clientWidth + 1,
            // How far any card's own content runs past that card's edge, or
            // past the edge of a row inside it, such as the steering chip.
            contentOverflow: Math.max(0, ...[...full.children].flatMap((card) => {
              const edge = card.getBoundingClientRect();
              return [...card.querySelectorAll("*")].map((node) => {
                const box = node.getBoundingClientRect();
                if (!box.width) return 0;
                const own = getComputedStyle(node).overflowX === "visible"
                  && node.clientWidth ? node.scrollWidth - node.clientWidth : 0;
                return Math.max(box.right - edge.right, edge.left - box.left, own);
              });
            })),
            width: cards[0].width };
        }),
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
    await page.locator("#inbox-approvals").screenshot({
      path: path.join(outputDir, `inbox-approvals-${width}.png`),
    });
    console.log(JSON.stringify({ width, ...result }));
    assert.equal(result.captions, 0);
    assert.equal(result.pendingCarried, true);
    assert.equal(result.decidedCarried, false);
    assert.equal(result.decidedControls, 0);
    assert.equal(result.inboxAlign, "left");
    assert.equal(result.overflowing, 0, `Overflow at ${width}px`);
    assert.equal(result.inbox.pendingCount, 8);
    assert.equal(result.inbox.decidedCount, 1);
    assert.equal(result.inbox.stacked, true, "Inbox approval lists keep one full-width card per row");
    for (const gap of ["leftGap", "rightGap", "sparseLeftGap", "sparseWidthGap"]) {
      assert(Math.abs(result.inbox[gap]) < 1, `Inbox ${gap} must align at ${width}px`);
    }
    for (const grid of result.grids) {
      assert(Math.abs(grid.rightGap) < 1, `${grid.label} last column must reach the header edge at ${width}px`);
      assert(Math.abs(grid.leftGap) < 1, `${grid.label} first column must align with the header`);
      assert(Math.abs(grid.sparseLeftGap) < 1, `${grid.label} sparse band must align with populated bands`);
      assert(Math.abs(grid.sparseWidthGap) < 1, `${grid.label} sparse band must preserve empty column slots`);
      assert.equal(grid.overflowing, false, `${grid.label} must not scroll horizontally`);
      assert(grid.contentOverflow < 1,
        `${grid.label} card content runs ${grid.contentOverflow}px past its card at ${width}px`);
      if (width === 268) assert.equal(grid.columns, 1, `${grid.label} must stack on phones`);
      if (width >= 1100) assert(grid.columns >= 3, `${grid.label} must exercise desktop columns`);
      if (width >= 1100 && grid.label.endsWith("essions")) assert(grid.width >= 319.5,
        `${grid.label} cards narrowed to ${grid.width}px at ${width}px`);
    }
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
