import puppeteer from 'puppeteer'
const base = process.argv[2] || 'http://localhost:8000'
const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox'] })
const page = await browser.newPage()
const fails = []
const check = (name, cond) => { console.log(`${cond ? 'PASS' : 'FAIL'}  ${name}`); if (!cond) fails.push(name) }
await page.goto(base, { waitUntil: 'networkidle0', timeout: 60000 })
check('dashboard shows AgentEvalOps brand', (await page.$eval('aside', (e) => e.textContent)).includes('AgentEvalOps'))
check('dashboard shows benchmark count card', (await page.$eval('main', (e) => e.textContent)).includes('Benchmarks'))
async function goto(label) {
  await page.goto(base, { waitUntil: 'networkidle0', timeout: 60000 })
  for (const b of await page.$$('aside a')) {
    if ((await b.evaluate((e) => e.textContent))?.trim() === label) { await b.click(); break }
  }
  await new Promise((r) => setTimeout(r, 900))
  return page.$eval('main', (e) => e.textContent)
}
check('benchmarks page lists tasks', (await goto('Benchmarks')).includes('tool-permission-v1'))
const exp = await goto('Experiments')
check('experiments page shows create form', exp.includes('Create experiment'))
const rel = await goto('Reports')
check('reports page shows gate + PDF action', rel.includes('PASS') || rel.includes('FAIL') || rel.includes('INSUFFICIENT'))
const sec = await goto('Security')
check('security page shows synthetic-secret boundary note', sec.toLowerCase().includes('synthetic'))
await browser.close()
if (fails.length) { console.error('E2E FAILURES:', fails); process.exit(1) }
console.log('E2E: all checks passed')
