import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const appSource = readFileSync(join(process.cwd(), 'src', 'App.vue'), 'utf8')
const historySource = readFileSync(join(process.cwd(), 'src', 'components', 'HistoryTab.vue'), 'utf8')
const resultsSource = readFileSync(join(process.cwd(), 'src', 'components', 'ScanResultsTab.vue'), 'utf8')
const centerSource = readFileSync(join(process.cwd(), 'src', 'components', 'ConfigurationCenter.vue'), 'utf8')

describe('page state and lazy loading contracts', () => {
  it('keeps dashboard and history state in separate component stores', () => {
    expect(appSource).toContain("const dashboardState = reactive({ loading: true, error: '' })")
    expect(historySource).toMatch(/const historyRuns = ref\(/)
    expect(historySource).not.toMatch(/dashboard\.(value|loading|error)\s*=/)
  })

  it('loads route pages and configuration subpages on demand', () => {
    expect(appSource).toMatch(/defineAsyncPage\(\(\) => import\('\.\/components\/SourcesTab\.vue'\)\)/)
    expect(appSource).toMatch(/defineAsyncPage\(\(\) => import\('\.\/components\/ConfigurationCenter\.vue'\)\)/)
    expect(centerSource).toMatch(/defineAsyncPage\(\(\) => import\('\.\/SettingsTab\.vue'\)\)/)
    expect(centerSource).toMatch(/defineAsyncPage\(\(\) => import\('\.\/ScanConfigTab\.vue'\)\)/)
  })

  it('labels current-page and all-filtered export actions distinctly', () => {
    expect(resultsSource).toContain('导出本页候选 M3U')
    expect(resultsSource).toContain('导出筛选候选 M3U')
    expect(resultsSource).toContain('apiScanAllResults')
  })
})
