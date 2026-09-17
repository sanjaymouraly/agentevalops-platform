import puppeteer from 'puppeteer'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
const base = process.argv[2] || 'http://localhost:8000'
const IMG_DIR = fileURLToPath(new URL('../docs/images/', import.meta.url))
fs.mkdirSync(IMG_DIR, { recursive: true })
const browser = await puppeteer.launch({ headless: 'new', args: ['--no-sandbox'] })
const page = await browser.newPage()
await page.setViewport({ width: 1440, height: 900 })
async function goto(label) {
  await page.goto(base, { waitUntil: 'networkidle0', timeout: 60000 })
  for (const b of await page.$$('aside a')) {
    if ((await b.evaluate((e) => e.textContent))?.trim() === label) { await b.click(); break }
  }
  await new Promise((r) => setTimeout(r, 1400))
}
const shots = [
  ['Overview', 'dashboard'], ['Benchmarks', 'benchmarks'], ['Agents', 'agents'], ['Providers', 'providers'],
  ['Experiments', 'experiments'], ['Comparison', 'comparison'], ['Failures', 'failures'], ['Security', 'security'],
  ['Reports', 'release-report'], ['Settings', 'settings'],
]
for (const [label, file] of shots) {
  await goto(label)
  await page.screenshot({ path: `${IMG_DIR}${file}.png` })
  console.log('saved', file)
}
await goto('Experiments')
await new Promise((r) => setTimeout(r, 800))
await page.screenshot({ path: `${IMG_DIR}trace.png` })
console.log('saved trace')
await browser.close()
