// Source-rendering fixtures for an item's delivery row and Approvals section
// in each QA and approval state. These captures prove layout and wording,
// not live settlement; the footer names that boundary.
// node item_approvals.visual.mjs PLAYWRIGHT_MODULE OUTPUT_DIR
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const [playwrightModule, output] = process.argv.slice(2);
assert(playwrightModule && output, "Name PLAYWRIGHT_MODULE and OUTPUT_DIR.");
const { chromium } = createRequire(import.meta.url)(playwrightModule);
const root = fileURLToPath(new URL("../../packages/yoke-core/src/yoke_core/ui/static/", import.meta.url));
const head = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
assert.equal(execFileSync("git", ["status", "--porcelain"], { encoding: "utf8" }).trim(), "", "Commit the capture source first.");
const entry = await readFile(path.join(root, "index.html"), "utf8");
const styles = [...entry.matchAll(/href="(?:\.\/|\/)assets\/([^"]+\.css)"/g)].map((match) => match[1]);
assert(styles.length, "Read the source stylesheet roster.");

// state -> [delivery row text, Approvals section text it must contain, text it must not]
const states = {
  "no-qa-pending": ["no item QA required · awaiting approval", "awaiting a decision", /QA ran|has no screenshot/],
  "approved-open": ["no item QA required · approved · completion pending", "approved · not yet completed", /QA ran/],
  "closing": ["no item QA required · approved · closing", "approved · not yet completed", /QA ran/],
  "done": ["deployed · item completed", "approved · completed", /QA ran/],
  "rejected": ["QA passed · approval rejected", "rejected", /QA ran/],
  "superseded": ["QA waived · awaiting item completion", "No approval is open", /\bApprove\b/],
  "visual-missing": ["QA passed · awaiting approval", "A screenshot check", /QA ran/],
  "command-ci": ["QA passed · awaiting approval", "command checks", /QA ran|has no screenshot/],
};
const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
${styles.map((name) => `<link rel="stylesheet" href="/assets/${name}">`).join("\n")}
<style>body{margin:0;color:var(--yoke-ink);background:var(--yoke-bg);font-family:var(--yoke-font-sans)}
.proof-frame{max-width:940px;margin:auto;padding:24px;display:grid;gap:16px}.proof-footer{color:var(--yoke-muted);font-size:11px;overflow-wrap:anywhere}</style></head>
<body><main class="universe-app-root proof-frame"><div class="item-card" id="card"></div><div id="panel"></div>
<footer class="proof-footer">Source rendering fixture · no live universe · ${head}</footer></main>
<script type="module">
import { appendItemDelivery, deploymentsByItemId } from '/assets/universe_item_deployment.js';
import { itemApprovalsPanel } from '/assets/item_view_approvals.js';
const state = new URL(location.href).searchParams.get('state');
const now = new Date().toISOString();
const qa = ['no-qa-pending','approved-open','closing','done'].includes(state)
  ? {state:'discharged',no_item_qa_required:true} : state === 'superseded' ? {state:'discharged'} : {state:'accepted'};
const standing = {"no-qa-pending":"pending","approved-open":"approved","closing":"approved","done":"completed",
  "rejected":"rejected","superseded":"superseded","visual-missing":"pending","command-ci":"pending"}[state];
const evidence = state === 'visual-missing' ? 'missing' : state.startsWith('no-qa') || ['approved-open','closing','done'].includes(state)
  ? 'not_required' : 'not_expected';
const pending = standing === 'pending';
const gate = {request_id:12,kind:'lifecycle_transition_approval',standing,status:pending ? 'pending' : 'resolved',
  item_status:state === 'done' ? 'done' : 'release',requested_at:now,
  subject_context:{item_id:70,item_ref:'DEMO-70',from_stage:'release',to_stage:'done',evidence:{state:evidence,screenshots:[]}},
  actions:pending ? ['approve','reject'] : [],can_act:pending,deciders:[{via:'owner',label:'Morgan'}],
  resolution_action:pending ? null : standing === 'rejected' ? 'reject' : 'approve',resolved_by:pending ? null : 'Morgan',resolved_at:pending ? null : now};
const older = {...gate,request_id:4,standing:'superseded',status:'resolved',actions:[],can_act:false,
  resolution_action:'approve',resolved_by:'Morgan',resolved_at:'2026-10-01T12:00:00Z',requested_at:'2026-10-01T11:00:00Z'};
const run = {id:'run-demo-70',status:state === 'done' ? 'succeeded' : 'executing',target_environment:'prod',current_stage:'item-qa',
  created_at:now,settling_at:state === 'closing' ? now : null,gates:state === 'superseded' ? [] : [gate],
  member_items:[{id:70,ref:'DEMO-70',status:state === 'done' ? 'done' : 'release',item_qa:qa,
    completed_deliveries:state === 'done' ? [{item_id:70,member_public_ref:'DEMO-70',run_id:'run-demo-70',environment:'prod'}] : []}]};
appendItemDelivery(document,document.getElementById('card'),{public_ref:'DEMO-70',project_id:1,completion_flow:'release'},deploymentsByItemId([run]));
const context = {document,isMounted:()=>true,client:{async call(){return {status:200,envelope:{success:true,result:{}}};}}};
const approvals = state === 'superseded' ? [older] : [gate, older];
document.getElementById('panel').append(itemApprovalsPanel(context,{public_ref:'DEMO-70',project:{id:1},approvals}));
window.proofReady=true;
</script></body></html>`;
const server = createServer(async (request, response) => {
  try {
    const pathname = new URL(request.url, "http://localhost").pathname;
    if (pathname === "/") { response.setHeader("Content-Type", "text/html"); response.end(html); return; }
    const name = pathname.slice("/assets/".length);
    assert(pathname.startsWith("/assets/") && !name.includes("/") && !name.includes(".."));
    response.setHeader("Content-Type", name.endsWith(".js") ? "text/javascript" : "text/css");
    response.end(await readFile(path.join(root, name)));
  } catch (error) { response.statusCode = 500; response.end(String(error)); }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const measurements = { head_sha: head, data_source: "source fixtures; no live universe", captures: [] };
try {
  for (const width of [1280, 375]) for (const theme of ["light", "dark"]) {
    const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: theme });
    const page = await context.newPage();
    for (const [state, [row, panel, absent]] of Object.entries(states)) {
      await page.goto(`http://127.0.0.1:${server.address().port}/?state=${state}`);
      await page.waitForFunction(() => window.proofReady);
      const values = await page.evaluate(() => ({
        row: document.querySelector(".item-deployment-outcome")?.textContent || "",
        panel: document.querySelector("#panel").textContent,
        bodyWidth: document.body.scrollWidth,
      }));
      assert(values.row.endsWith(row), JSON.stringify({ state, values }));
      assert(values.panel.includes(panel), JSON.stringify({ state, values }));
      assert(!absent.test(values.panel), JSON.stringify({ state, values }));
      assert(values.bodyWidth <= width, JSON.stringify({ state, width, values }));
      const name = `${state}-${width}-${theme}.png`;
      await page.screenshot({ path: path.join(output, name), fullPage: true });
      measurements.captures.push({ state, width, theme, file: name, ...values });
    }
    await context.close();
  }
  await writeFile(path.join(output, "measurements.json"), JSON.stringify(measurements, null, 2));
  console.log(`Captured ${measurements.captures.length} source fixtures at desktop/375px in both themes on ${head}`);
} finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
