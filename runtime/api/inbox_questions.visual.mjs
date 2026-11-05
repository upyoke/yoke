// Source fixtures use the real Inbox, evidence strip and answer resolver.
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
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
const html = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
${styles.map((name) => `<link rel="stylesheet" href="/assets/${name}">`).join("\n")}
<style>body{margin:0;background:var(--yoke-bg);color:var(--yoke-ink);font-family:var(--yoke-font-sans)}
main{max-width:960px;margin:auto;padding:16px}footer{font-size:11px;overflow-wrap:anywhere;margin-top:20px}</style></head>
<body><main class="universe-app-root"><h1>Inbox</h1><div id="inbox"></div>
<footer>Source fixture · no live universe · ${head}</footer></main><script type="module">
import {renderInboxView} from '/assets/universe_views_inbox.js';
const state=new URL(location.href).searchParams.get('state');
const stamp=new Date(Date.now()-300000).toISOString();
const svg='<svg xmlns="http://www.w3.org/2000/svg" width="480" height="240"><rect width="480" height="240" fill="#f5f6f8"/><text x="28" y="70" font-family="sans-serif" font-size="24" fill="#253342">Header preview</text><rect x="28" y="105" width="280" height="44" fill="#26334d"/><text x="28" y="193" font-family="sans-serif" font-size="16" fill="#253342">Current blue header</text></svg>';
const artifacts=[{artifact_id:1,decision_request_id:7,artifact_type:'screenshot',content_type:'image/svg+xml',metadata:{label:'header-preview.svg'}},
{artifact_id:2,decision_request_id:7,artifact_type:'document',content_type:'application/pdf',metadata:{label:'header-brief.pdf'}}];
let row={id:7,kind:'operator_question',status:'pending',project_id:10,created_at:stamp,
requesting_session_id:'sample-worker',requesting_session_label:'Morgan · Codex',
actions:state==='options' ? ['blue','green','freeform'] : ['freeform'],
subject_context:{question:['options','answered'].includes(state) ? 'Which color should the header use?' : 'What should the welcome message say?',
context:'The current header uses **blue**. Green has more contrast.',
options:['options','answered'].includes(state) ? [{id:'blue',label:'Keep blue',detail:'Matches the current header.'},{id:'green',label:'Use green'}] : [],
recommended_option:state==='options' ? 'blue' : null,allow_freeform:true,artifacts:state==='options' ? artifacts : []}};
if(state==='answered')row={...row,status:'resolved',decided_by_you:true,actions:[],resolution_action:'blue',resolved_at:stamp};
window.calls=[];
const client={async call(request){
window.calls.push(request);
if(request.function==='decision_requests.attachment.read')return {status:200,envelope:{success:true,result:{artifact_id:request.payload.artifact_id,backend:'local',disposition:'ready',content_type:'image/svg+xml',content_base64:btoa(svg)}}};
if(request.function==='decision_requests.resolve'){
if(state==='error')return {status:503,envelope:{success:false,error:{code:'answer_unavailable',message:'Retry Send.'}}};
row={...row,status:'resolved',decided_by_you:true,actions:[],resolution_action:request.payload.action,
resolution_note:request.payload.note,resolved_at:new Date().toISOString(),your_decision:{action:request.payload.action,note:request.payload.note}};
return {status:200,envelope:{success:true,result:{request:row}}};}
return {status:200,envelope:{success:true,result:{needs_decision:[row],messages:[]}}};}};
renderInboxView({document,client,isMounted:()=>true,projects:()=>[{id:10,slug:'example'}]},document.getElementById('inbox'),'all');
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
const captures = [];
try {
  for (const width of [1440, 375]) for (const state of ["options", "freeform", "answered", "error"]) {
    const page = await browser.newPage({ viewport: { width, height: 1000 }, colorScheme: "light" });
    await page.goto(`http://127.0.0.1:${server.address().port}/?state=${state}`);
    await page.locator(".inbox-question-card").waitFor();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    if (state === "answered") {
      assert.match(await page.locator(".inbox-question-answer").textContent(), /Which color.*Keep blue · you/);
      assert.equal(await page.locator(".inbox-question-card").locator("h3,button,textarea,details").count(), 0);
      assert.equal(await page.locator(".inbox-question-answer-text").evaluate((node) => node.scrollWidth <= node.clientWidth), true, "Keep the short answer fully visible.");
    } else {
      assert.equal(await page.locator(".inbox-question-context").evaluate((node) => node.open), false);
      const heights = await page.locator(".inbox-question-option, .inbox-question-send").evaluateAll((buttons) => buttons.map((button) => button.getBoundingClientRect().height));
      assert(heights.every((height) => height >= 44), `Question buttons must be at least 44px: ${heights}`);
      if (state === "options") {
        assert.equal(await page.locator(".inbox-question-option.primary").textContent(), "Keep blue");
        assert.equal(await page.locator(".inbox-question-choice small").textContent(), "Recommended");
        assert.equal(await page.locator(".review-evidence figure, .review-evidence .review-text-chip").count(), 2);
        await page.locator(".review-shot.is-ready").waitFor();
        await page.locator(".review-shot-open").click();
        await page.locator(".review-lightbox").waitFor();
        await page.keyboard.press("Escape");
        if (width === 375) {
          const boxes = await page.locator(".inbox-question-option").evaluateAll((buttons) => buttons.map((button) => { const box=button.getBoundingClientRect(); return {x:box.x,width:box.width}; }));
          assert.equal(boxes[0].x, boxes[1].x);
          assert.equal(boxes[0].width, boxes[1].width);
        }
      }
    }
    if (state !== "error") await page.screenshot({ path: path.join(output, `${width}-${state}.png`), fullPage: true });
    if (state === "options") {
      await page.locator(".inbox-question-option.primary").click();
      await page.locator(".inbox-question-answer").waitFor();
      assert.match(await page.locator(".inbox-question-answer").textContent(), /Which color.*Keep blue/);
    } else if (state !== "answered") {
      const input = page.locator(".inbox-question-freeform textarea");
      assert.equal(await page.locator(".inbox-question-send").isDisabled(), true);
      await input.fill("Welcome back");
      await input.press("Control+Enter");
      if (state === "error") {
        await page.locator(".inbox-row-error").waitFor();
        assert.match(await page.locator(".inbox-row-error").textContent(), /answer_unavailable.*Retry Send/);
        assert.equal(await input.inputValue(), "Welcome back");
      } else {
        await page.locator(".inbox-question-answer").waitFor();
        assert.match(await page.locator(".inbox-question-answer").textContent(), /welcome message.*Welcome back/);
      }
    }
    captures.push({ width, state, calls: await page.evaluate(() => window.calls) });
    await page.close();
  }
  await writeFile(path.join(output, "measurements.json"), JSON.stringify({ head, data_source: "source fixtures", captures }, null, 2));
  process.stdout.write(`Verified ${captures.length} question states; wrote six operator review screenshots.\n`);
} finally {
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
