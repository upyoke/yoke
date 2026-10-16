// Source-rendering fixtures for every approval state. These captures prove
// layout, not live credential issuance; the footer makes that boundary visible.
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
const styles = [...entry.matchAll(/href="(?:\.\/|\/)assets\/([^\"]+\.css)"/g)].map((match) => match[1]);
assert(styles.length, "Read the source stylesheet roster.");
const states = ["waiting", "later", "approved", "denied", "expired", "consumed", "unavailable",
  "read-failed", "refused", "owner-bound", "owner-unknown", "failed-write", "recording", "missing-viewer",
  "local", "local-code", "token", "embedded", "long-facts", "no-code"];
const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
${styles.map((name) => `<link rel="stylesheet" href="/assets/${name}">`).join("\n")}
<style>body{margin:0;color:var(--yoke-ink);background:var(--yoke-bg);font-family:var(--yoke-font-sans)}
.proof-frame{max-width:940px;margin:auto;padding:24px}.proof-footer{margin-top:20px;color:var(--yoke-muted);font-size:11px;overflow-wrap:anywhere}
@media(max-width:520px){.proof-frame{padding:16px 12px}}</style></head>
<body><main class="universe-app-root proof-frame"><header class="page-head"><div class="h"><h1 class="title"></h1></div></header>
<div class="view-host" id="approval"></div><footer class="proof-footer">Source rendering fixture · no live universe · ${head}</footer></main>
<script type="module">
import { renderApprovalCard, renderMachineApproval } from '/assets/machine_approval.js';
import { localReachabilityNotice } from '/assets/local_reachability_notice.js';
const state = new URL(location.href).searchParams.get('state');
const expiry = new Date(Date.now() + (state === 'expired' ? -120000 : 540000)).toISOString();
const authorization = {code:'K7F2',machine:state === 'long-facts' ? 'sample-machine-with-a-very-long-hostname-and-no-short-alias.example.test' : 'sample-macbook-pro',
machine_id:'4f2c9a1e-80d6-4b2c-a447-123456789abc',platform:'macOS',expires_at:expiry,
viewer:state === 'missing-viewer' ? null : {name:state === 'long-facts' ? 'Morgan with a very long display name' : 'Morgan',actor_id:9},
requested_by:state === 'missing-viewer' ? null : {name:'Morgan',actor_id:9},state,
decision:state === 'approved' || state === 'consumed' ? 'approve' : state === 'denied' ? 'deny' : null};
const client = {async call(request){
 const ok = result => ({status:200,envelope:{success:true,result}});
 const fail = (code,message) => ({status:403,envelope:{success:false,error:{code,message}}});
 if(request.function === 'organizations.get')return ok({name:'Example team'});
 if(request.function === 'machine.list')return ok({count:state === 'later' ? 3 : 0,machines:[]});
 if(request.function === 'machine_authorization.resolve') {
  if(state === 'recording')return new Promise(()=>{});
  if(state === 'owner-bound')return fail('authorization_owner_mismatch','start your own connection code');
  if(state === 'failed-write')return fail('storage_unavailable','Storage could not record the decision.');
 }
 if(state === 'unavailable')return fail('authorization_unavailable');
 if(state === 'read-failed')return fail('storage_unavailable','The request could not be read.');
 if(state === 'refused')return fail('organization_membership_required','Membership is required.');
 if(state === 'owner-unknown')return fail('authorization_owner_mismatch','start your own connection');
 return ok({authorization});
}};
const context = {document,isMounted:()=>true,client,capabilities:{data:{portability:{mode:state.startsWith('local') ? 'local' : 'hosted'}}}};
const host = document.getElementById('approval');
if(state === 'embedded') {
 document.querySelector('h1').textContent='Machines';
 await renderApprovalCard(context,host,authorization.code,{embedded:true});
} else if(state === 'token') {
 document.querySelector('h1').textContent='API tokens';
 host.classList.add('machine-approval-card');
 host.appendChild(localReachabilityNotice(document,{variant:'token'}));
} else await renderMachineApproval(context,host,null,['local','no-code'].includes(state) ? null : authorization.code,
 {setPageHead:({title})=>{document.querySelector('h1').textContent=title;}});
if(['owner-bound','failed-write','recording'].includes(state)) {
 host.querySelector('button').click();
 await new Promise(resolve=>setTimeout(resolve,0));
}
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
    const context = await browser.newContext({ viewport: { width, height: 900 }, colorScheme: theme, timezoneId: "America/New_York" });
    const page = await context.newPage();
    for (const state of states) {
      await page.goto(`http://127.0.0.1:${server.address().port}/?state=${state}`);
      await page.waitForFunction(() => window.proofReady);
      const values = await page.evaluate(() => {
        const card = document.querySelector('.machine-approval-card') || document.querySelector('#approval');
        const bounds = card.getBoundingClientRect();
        return { title:document.querySelector('h1').textContent, text:card.textContent,
          cardWidth:bounds.width, cardRight:bounds.right, bodyWidth:document.body.scrollWidth,
          columns:getComputedStyle(document.querySelector('.machine-approval-fact') || card).gridTemplateColumns,
          active:document.querySelectorAll('.machine-approval-steps [aria-current="step"]').length,
          steps:document.querySelectorAll('.machine-approval-steps li').length,
          theme:matchMedia('(prefers-color-scheme:dark)').matches ? 'dark' : 'light',
          forms:document.querySelectorAll('input,form').length,
          focused:document.activeElement.textContent, background:getComputedStyle(card).backgroundColor };
      });
      assert.equal(values.theme, theme);
      assert((state === "no-code" || values.cardWidth <= 580) && values.cardRight <= width && values.bodyWidth <= width, JSON.stringify({ state, width, values }));
      assert(!/CLI|Connecting machine/.test(values.text));
      assert.equal(values.forms, 0);
      assert.equal(values.steps, ["later", "local", "local-code", "token", "embedded", "no-code"].includes(state) ? 0 : 4);
      if (state === "approved") {
        assert.equal(values.title, "Machine connected");
        assert.equal(values.active, 0);
        assert(!/Expires|must match/.test(values.text));
        assert(values.text.includes("Return to your terminal"));
      }
      if (state === "embedded") assert.equal(values.focused, "Approve this machine");
      if (state === "recording") assert(values.text.includes("Recording your decision…"));
      if (state === "owner-bound") assert(values.text.includes("This connection was already handled by Morgan."));
      if (state === "owner-unknown") assert(values.text.includes("This connection was already handled by another person in your org."));
      if (state.startsWith("local")) assert(values.text.includes("Reachable here only."));
      if (state === "token") assert(values.text.includes("This token works on this computer only."));
      if (["waiting", "later"].includes(state)) {
        assert(values.text.includes("macOS · machine 4f2c9a1e"));
        assert(values.text.includes("EDT") || values.text.includes("EST"));
        assert(values.text.includes("in 9 minutes"));
        const gap = await page.locator('.machine-approval-actions').evaluate((node) => getComputedStyle(node).gap);
        assert.equal(gap, "8px");
      }
      const name = `${state}-${width}-${theme}.png`;
      await page.screenshot({ path: path.join(output, name), fullPage: true });
      measurements.captures.push({ state, width, theme, file:name, ...values });
    }
    await context.close();
  }
  await writeFile(path.join(output, "measurements.json"), JSON.stringify(measurements, null, 2));
  console.log(`Captured ${measurements.captures.length} source fixtures at desktop/375px in both themes on ${head}`);
} finally { await browser.close(); await new Promise((resolve) => server.close(resolve)); }
