import assert from 'node:assert/strict'
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

const frontendRoot = fileURLToPath(new URL('..', import.meta.url))
const temporaryDist = join(frontendRoot, '.codex-dist')
const defaultDist = existsSync(join(temporaryDist, 'index.html')) ? temporaryDist : join(frontendRoot, '..', 'dist')
const distDir = resolve(process.env.IPTV_FRONTEND_DIST || defaultDist)
const indexFile = join(distDir, 'index.html')

assert.ok(existsSync(indexFile), `build output not found: ${indexFile}`)

function assetPath(reference, fromFile = indexFile) {
  const clean = reference.split(/[?#]/)[0]
  if (!clean || /^(?:https?:|data:)/.test(clean)) return null
  if (clean.startsWith('/static/dist/')) return join(distDir, clean.slice('/static/dist/'.length))
  if (clean.startsWith('/')) return join(distDir, clean.replace(/^\/+/, ''))
  return resolve(dirname(fromFile), clean)
}

const html = readFileSync(indexFile, 'utf8')
const initial = new Set()
for (const match of html.matchAll(/(?:src|href)=["']([^"']+\.(?:js|css)(?:\?[^"']*)?)["']/g)) {
  const path = assetPath(match[1])
  if (path && existsSync(path)) initial.add(path)
}

const visitedJs = new Set()
function collectStaticImports(filename) {
  if (visitedJs.has(filename) || !existsSync(filename)) return
  visitedJs.add(filename)
  initial.add(filename)
  const source = readFileSync(filename, 'utf8')
  const importPattern = /(?:\bfrom\s*|\bimport\s*)["']([^"']+\.js(?:\?[^"']*)?)["']/g
  for (const match of source.matchAll(importPattern)) {
    const imported = assetPath(match[1], filename)
    if (imported) collectStaticImports(imported)
  }
}

for (const file of [...initial]) {
  if (file.endsWith('.js')) collectStaticImports(file)
}

const initialGzipBytes = [...initial].reduce((sum, file) => (
  sum + gzipSync(readFileSync(file), { level: 9 }).byteLength
), 0)
const initialBudget = 450 * 1024
assert.ok(
  initialGzipBytes <= initialBudget,
  `initial assets are ${(initialGzipBytes / 1024).toFixed(1)} KiB gzip (budget: 450 KiB)`,
)

const assetsDir = join(distDir, 'assets')
const jsFiles = readdirSync(assetsDir).filter(name => name.endsWith('.js'))
const chunkBudget = 750 * 1024
for (const name of jsFiles) {
  const size = statSync(join(assetsDir, name)).size
  assert.ok(size <= chunkBudget, `${name} is ${(size / 1024).toFixed(1)} KiB raw (budget: 750 KiB)`)
}

console.log(`bundle size OK: ${(initialGzipBytes / 1024).toFixed(1)} KiB initial gzip; ${jsFiles.length} JS chunks checked`)
