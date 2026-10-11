// Reproduce the example profile locally and capture the relevant sections.
// Optional developer tool: node render-references.cjs [playwright module] [browser executable]
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const { chromium } = require(process.argv[2] || 'playwright');
const repo = path.resolve(__dirname, '..');
const server = http.createServer((req, res) => {
  const requestPath = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  let target = path.resolve(repo, '.' + requestPath);
  if (!target.startsWith(repo + path.sep)) { res.writeHead(403); res.end(); return; }
  if (fs.existsSync(target) && fs.statSync(target).isDirectory()) target = path.join(target, 'index.html');
  const types = { '.html':'text/html', '.css':'text/css', '.js':'text/javascript', '.svg':'image/svg+xml', '.png':'image/png', '.mp4':'video/mp4', '.txt':'text/plain' };
  if (!fs.existsSync(target)) { res.writeHead(404); res.end(); return; }
  res.setHeader('Content-Type', types[path.extname(target)] || 'application/octet-stream');
  fs.createReadStream(target).pipe(res);
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({ headless:true, ...(process.argv[3] ? {executablePath:process.argv[3]} : {}) });
    const page = await browser.newPage({ viewport:{width:1000,height:760}, deviceScaleFactor:1.5, reducedMotion:'reduce' });
    // Use the checked-out source; the rendered preview never needs credentials.
    await page.route('**/api.github.com/**', route => route.abort());
    await page.goto('http://127.0.0.1:' + server.address().port + '/example/', {waitUntil:'networkidle'});
    await page.locator('#entryGate').click();
    await page.locator('#motionButton').click();
    await page.locator('#profileCard').waitFor({state:'visible'});
    const card = await page.locator('#profileCard').boundingBox();
    const name = await page.locator('#displayName').boundingBox();
    const bio = await page.locator('#bio').boundingBox();
    const clip = {x:card.x, y:name.y-22, width:card.width, height:bio.y+bio.height+26-(name.y-22)};
    fs.mkdirSync(path.join(__dirname,'assets'), {recursive:true});
    for (const [id, file] of [['displayName','names.png'],['bio','bio.png']]) {
      const style = await page.addStyleTag({content:'#' + id + ' { outline:2px solid #cfa3f0; outline-offset:8px; border-radius:4px; }'});
      await page.screenshot({path:path.join(__dirname,'assets',file), clip});
      await style.evaluate(el => el.remove());
    }
    console.log('Captured names.png and bio.png from the local example profile.');
  } finally {
    if (browser) await browser.close();
    await new Promise(resolve => server.close(resolve));
  }
})().catch(error => { console.error(error.message); process.exitCode=1; });
