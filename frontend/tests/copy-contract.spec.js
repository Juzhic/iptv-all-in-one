import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
import { parse } from '@vue/compiler-sfc'

import { NAV_ITEMS, getPageMeta } from '../src/navigation.js'

const frontendRoot = process.cwd()

function read(relativePath) {
  return readFileSync(join(frontendRoot, relativePath), 'utf8')
}

function readTemplate(relativePath) {
  const source = read(relativePath)
  const { descriptor, errors } = parse(source, { filename: relativePath })
  expect(errors).toEqual([])
  expect(descriptor.template).not.toBeNull()
  return descriptor.template.content
}

describe('user-visible terminology contract', () => {
  it('uses distinct workflow names in navigation without changing route identifiers', () => {
    const contracts = {
      'scan-results': { label: '候选源池', short: '池', description: /复检.*测绘采集|测绘采集.*复检/ },
      detection: { label: '健康复检', short: '检', description: /候选源池.*复检|复检.*候选源池/ },
      testing: { label: '全量测速', short: '测', description: /测速.*播放列表/ },
      scanner: { label: '测绘采集', short: '采', description: /测绘平台.*候选源/ },
      'ip-scan': { label: 'IP 探测', short: 'IP', description: /探测.*(?:IP|域名|端口)/ },
    }

    for (const [route, contract] of Object.entries(contracts)) {
      const page = getPageMeta(route)
      expect(page.value).toBe(route)
      expect(page).toMatchObject({ label: contract.label, short: contract.short })
      expect(page.description).toMatch(contract.description)
    }

    expect(NAV_ITEMS.map(item => item.label)).not.toEqual(expect.arrayContaining([
      '扫描频道',
      '检测监控',
      '系统测试',
      '频道扫描',
      'IP 扫描',
    ]))
  })

  it('keeps primary page titles and actions aligned with their navigation names', () => {
    const testing = readTemplate('src/components/TestingTab.vue')
    expect(testing).toMatch(/class="section-title">全量测速<\/div>/)
    expect(testing).toContain("'开始全量测速'")
    expect(testing).toContain("'停止测速'")
    expect(testing).not.toMatch(/测试控制|立即测试|终止测试/)

    const scannerSource = read('src/components/ScannerTab.vue')
    const scanner = readTemplate('src/components/ScannerTab.vue')
    expect(scanner).toMatch(/class="section-title">测绘采集<\/div>/)
    expect(scanner).toContain('候选源池')
    expect(scanner).toContain("'停止采集'")
    expect(scanner).toMatch(/class="section-title">采集进度<\/div>/)
    expect(scannerSource).toContain("return '开始采集'")
    expect(scanner).not.toMatch(/class="section-title">(?:频道扫描|扫描进度)<\/div>/)
    expect(scannerSource).not.toContain("return '开始扫描'")

    const ipScan = readTemplate('src/components/IpScanTab.vue')
    expect(ipScan).toMatch(/class="section-title">IP 探测<\/div>/)
    expect(ipScan).toContain('开始探测')
    expect(ipScan).toContain("'停止探测'")
    expect(ipScan).toMatch(/class="section-title">探测进度<\/div>/)
    expect(ipScan).not.toMatch(/class="section-title">(?:IP扫描|扫描进度)<\/div>/)

    const results = readTemplate('src/components/ScanResultsTab.vue')
    expect(results).toContain('立即复检')
    expect(results).toContain('候选源池暂无数据')
    expect(results).not.toContain('手动检测一轮')

    const detection = readTemplate('src/components/DetectionTab.vue')
    expect(detection).toMatch(/class="section-title section-title--flush">健康复检<\/div>/)
    expect(detection).toContain('候选源池')
    expect(detection).not.toMatch(/class="section-title section-title--flush">检测监控<\/div>/)

    const configuration = readTemplate('src/components/ConfigurationCenter.vue')
    expect(configuration).toContain('value="scan" label="采集配置"')
    expect(configuration).not.toContain('value="scan" label="扫描配置"')
  })

  it('uses the same workflow names in cross-page guidance and empty states', () => {
    const app = readTemplate('src/App.vue')
    expect(app).toContain('可前往“全量测速”或“测绘采集”启动第一轮任务。')
    expect(app).not.toMatch(/可前往“系统测试”|可前往“频道扫描”/)

    const overview = readTemplate('src/components/OverviewTab.vue')
    expect(overview).toContain('测绘采集质量')
    expect(overview).toContain('候选源池状态')
    expect(overview).toContain('请前往“全量测速”页，点击“开始全量测速”发起首次测速')

    const sources = readTemplate('src/components/SourcesTab.vue')
    expect(sources).toContain('先运行一次全量测速')
    expect(sources).not.toContain('先运行一次系统测试')

    const dashboard = read('src/utils/dashboard.js')
    expect(dashboard).toContain('等待首次测绘采集')
    expect(dashboard).toContain('候选源池良好率')
    expect(dashboard).toContain('等待首次全量测速')
    expect(dashboard).not.toContain('等待首次系统测试')
  })
})
