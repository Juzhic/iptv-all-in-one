import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import { parse } from '@vue/compiler-sfc'

import { NAV_GROUPS, NAV_ITEMS, TAB_VALUES, getPageMeta } from '../src/navigation.js'

const frontendRoot = fileURLToPath(new URL('..', import.meta.url))
const read = (relativePath) => readFileSync(join(frontendRoot, relativePath), 'utf8')

test('navigation groups expose every page exactly once', () => {
  assert.equal(NAV_GROUPS.length, 4)
  assert.equal(NAV_ITEMS.length, 9)
  assert.equal(new Set(TAB_VALUES).size, TAB_VALUES.length)
  assert.deepEqual(NAV_GROUPS.flatMap((group) => group.items), NAV_ITEMS)
  assert.deepEqual(NAV_GROUPS.map((group) => group.items.map((item) => item.value)), [
    ['overview'],
    ['scan-results', 'sources', 'detection'],
    ['testing', 'scanner', 'ip-scan'],
    ['history', 'configuration'],
  ])

  for (const item of NAV_ITEMS) {
    assert.ok(item.value)
    assert.ok(item.label)
    assert.ok(item.short)
    assert.ok(item.description.length >= 10)
    assert.equal(getPageMeta(item.value), item)
  }

  assert.equal(getPageMeta('unknown-page'), NAV_ITEMS[0])
})

test('application shell has grouped desktop navigation and a mobile drawer', () => {
  const app = read('src/App.vue')
  const asyncPage = read('src/utils/asyncPage.js')
  const entry = read('src/main.js')
  const layout = read('src/styles/layout.css')

  assert.match(app, /class="app-sidebar"/)
  assert.match(app, /class="mobile-topbar"/)
  assert.match(app, /<t-drawer/)
  assert.match(app, /class="drawer-nav"/)
  assert.match(app, /useHashRoute/)
  assert.match(asyncPage, /loadingComponent:\s*AsyncPageLoading/)
  assert.match(asyncPage, /errorComponent:\s*AsyncPageError/)
  assert.match(asyncPage, /suspensible:\s*false/)
  assert.doesNotMatch(app, /class="mobile-nav"/)
  assert.match(app, /activeTab === 'overview'/)
  assert.match(app, /:aria-current="activeTab === item\.value \? 'page'/)
  assert.match(layout, /--app-sidebar-width:/)
  assert.match(layout, /\.data-table-shell\s*\{/)
  assert.match(layout, /overflow-x:\s*auto/)
  assert.match(layout, /:focus-visible\s*\{/)
  assert.match(layout, /outline:\s*2px solid var\(--td-brand-color/)
  assert.match(layout, /@media \(max-width: 768px\)/)
  assert.match(entry, /tdesign-vue-next\/esm\/common\/style\/web\/theme\/_index\.less/)
})

test('data-heavy pages define narrow-screen and local overflow contracts', () => {
  const contracts = [
    ['src/components/HistoryTab.vue', /table-scroll-shell/, /@media \(max-width: 768px\)/],
    ['src/components/TestingTab.vue', /download-row/, /@media \(max-width: 640px\)/],
    ['src/components/DetectionTab.vue', /data-table-shell/, /responsive-toolbar/],
    ['src/components/IpScanTab.vue', /data-table-shell/, /@media \(max-width: 768px\)/],
    ['src/components/ScanResultsTab.vue', /data-table-shell/, /@media \(max-width: 720px\)/],
    ['src/components/ScannerTab.vue', /workspace-card/, /@media \(max-width: 768px\)/],
    ['src/components/ScanConfigTab.vue', /scan-size-item/, /grid-template-columns: repeat\(2, minmax\(0, 1fr\)\)/],
    ['src/components/SettingsTab.vue', /config-actions :deep\(\.t-space\)/, /@media \(max-width: 768px\)/],
    ['src/components/SourcesTab.vue', /source-table-shell/, /@media \(max-width: 768px\)/],
    ['src/components/ConfigurationCenter.vue', /center-tabs/, /@media \(max-width: 768px\)/],
  ]

  for (const [path, layoutPattern, mobilePattern] of contracts) {
    const source = read(path)
    assert.match(source, layoutPattern, `${path} must contain its local layout contract`)
    assert.match(source, mobilePattern, `${path} must contain a mobile layout contract`)
  }

  const scanResults = read('src/components/ScanResultsTab.vue')
  assert.match(scanResults, /<AsyncState[\s\S]*:error="groupedError"/)
  assert.match(scanResults, /:retry="loadGrouped"/)
})

test('all Vue single-file components remain parseable', () => {
  const componentDir = join(frontendRoot, 'src', 'components')
  const vueFiles = [
    join(frontendRoot, 'src', 'App.vue'),
    ...readdirSync(componentDir)
      .filter((name) => name.endsWith('.vue'))
      .map((name) => join(componentDir, name)),
  ]

  for (const filename of vueFiles) {
    const { errors } = parse(readFileSync(filename, 'utf8'), { filename })
    assert.deepEqual(errors, [], `${filename} should parse without errors`)
  }
})
