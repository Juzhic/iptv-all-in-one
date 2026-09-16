import { flushPromises, mount, shallowMount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ScanConfigTab from '../src/components/ScanConfigTab.vue'
import { DialogPlugin } from 'tdesign-vue-next/es/dialog/index.mjs'

const apiMocks = vi.hoisted(() => ({
  apiSaveScanConfig: vi.fn(),
  apiScanConfig: vi.fn(() => Promise.resolve({})),
  apiScanKeyAdd: vi.fn(),
  apiScanKeyDelete: vi.fn(),
  apiScanKeys: vi.fn(() => Promise.resolve([])),
  apiScanKeysCredits: vi.fn(() => Promise.resolve([])),
  apiScanKeyUpdate: vi.fn(),
  apiScanKeyTest: vi.fn(),
}))

vi.mock('../src/api.js', () => apiMocks)
vi.mock('tdesign-vue-next/es/message/index.mjs', () => ({
  MessagePlugin: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}))
vi.mock('tdesign-vue-next/es/dialog/index.mjs', () => ({
  DialogPlugin: { confirm: vi.fn() },
}))

let wrapper

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.clearAllMocks()
})

describe('scan configuration page', () => {
  it('edits multicast templates, preserves saved controls, and keeps catalog out of updates', async () => {
    const template = { province: '广东', operator: '电信', content: 'CCTV1,rtp://239.1.1.1:1234' }
    apiMocks.apiScanConfig.mockResolvedValueOnce({
      multicast_enabled: true, multicast_quake_enabled: false,
      multicast_proxy_urls: '广东,电信,http://8.8.8.8:4022', multicast_templates: [template],
      multicast_builtin_catalog: [{ province: '广东', operator: '电信', channels: 400 }],
    })
    wrapper = mount(ScanConfigTab)
    await flushPromises()
    const state = wrapper.vm.$.setupState
    const card = wrapper.get('[data-testid="multicast-config"]')
    expect(card.text()).toContain('广东 · 电信 · 400 频道')
    expect(state.scanCfg).not.toHaveProperty('multicast_quake_enabled')
    expect(wrapper.text()).not.toContain('Quake 自动发现')
    expect(wrapper.get('[data-testid="udpxy-discovery"]').text()).toContain('UDPXY 组播识别')
    expect(card.text()).not.toContain('组播搜索预算')
    const add = card.findAll('button').find(button => button.text() === '添加组播模板')
    await add.trigger('click')
    expect(state.scanCfg.multicast_templates).toHaveLength(2)
    await wrapper.vm.save()
    expect(apiMocks.apiSaveScanConfig).not.toHaveBeenCalled()
    await card.get('[aria-label="删除模板 2"]').trigger('click')
    state.scanCfg.multicast_max_channels = 72
    apiMocks.apiSaveScanConfig.mockResolvedValueOnce({ multicast_max_channels: 72, multicast_builtin_catalog: [] })
    await wrapper.vm.save()
    const payload = apiMocks.apiSaveScanConfig.mock.calls[0][0]
    expect(payload).toMatchObject({ multicast_enabled: true,
      multicast_templates: [template], multicast_max_channels: 72, multicast_max_proxies: 20 })
    expect(payload).not.toHaveProperty('multicast_builtin_catalog')
    expect(payload).not.toHaveProperty('multicast_quake_enabled')
    expect(payload).not.toHaveProperty('multicast_search_size')
    expect(state.isDirty).toBe(false)
  })

  it('defaults multicast to off and rejects duplicate templates and excessive budgets', async () => {
    wrapper = mount(ScanConfigTab)
    await flushPromises()
    const state = wrapper.vm.$.setupState
    expect(state.scanCfg.multicast_enabled).toBe(false)
    state.scanCfg.multicast_max_proxies = 51
    await wrapper.vm.save()
    expect(apiMocks.apiSaveScanConfig).not.toHaveBeenCalled()
    state.scanCfg.multicast_max_proxies = 20
    const template = { province: '广东', operator: '电信', content: 'CCTV1,udp://239.1.1.1:1234' }
    state.scanCfg.multicast_templates = [template, { ...template }]
    await wrapper.vm.save()
    expect(apiMocks.apiSaveScanConfig).not.toHaveBeenCalled()
  })

  it('loads and saves daily expansion controls and rejects invalid budgets', async () => {
    apiMocks.apiScanConfig.mockResolvedValueOnce({ detection_expansion_enabled: false, detection_expansion_max_ips: 17 })
    wrapper = mount(ScanConfigTab)
    await flushPromises()
    const state = wrapper.vm.$.setupState
    expect(state.scanCfg.detection_expansion_enabled).toBe(false)
    expect(state.scanCfg.detection_expansion_max_ips).toBe(17)
    state.scanCfg.detection_expansion_max_ips = 201
    await wrapper.vm.save()
    expect(apiMocks.apiSaveScanConfig).not.toHaveBeenCalled()
    state.scanCfg.detection_expansion_max_ips = 20
    state.scanCfg.detection_expansion_enabled = true
    apiMocks.apiSaveScanConfig.mockResolvedValueOnce({})
    await wrapper.vm.save()
    expect(apiMocks.apiSaveScanConfig.mock.calls[0][0]).toMatchObject({ detection_expansion_enabled: true,
      detection_expansion_max_ips: 20, detection_expansion_cooldown_hours: 24 })
  })

  it('appends recommended rules without losing custom text and saves them only on request', async () => {
    apiMocks.apiScanConfig.mockResolvedValueOnce({ search_keywords: ['# 自定义规则', 'title:自定义直播', '/iptv/live/1000.json'] })
    wrapper = mount(ScanConfigTab)
    await flushPromises()
    const button = wrapper.findAll('button').find(b => b.text() === '补充推荐规则')
    await button.trigger('click')
    const state = wrapper.vm.$.setupState
    const first = state.scanCfg.search_keywords
    expect(first).toContain('# 自定义规则\ntitle:自定义直播')
    expect(first).toContain('/api/live/channels')
    expect(first).toContain('title:Tvheadend')
    expect(first.split('\n').filter(line => line === '/iptv/live/1000.json')).toHaveLength(1)
    expect(state.isDirty).toBe(true)
    expect(apiMocks.apiSaveScanConfig).not.toHaveBeenCalled()
    await button.trigger('click')
    expect(state.scanCfg.search_keywords).toBe(first)
    apiMocks.apiSaveScanConfig.mockResolvedValueOnce({})
    await wrapper.vm.save()
    const saved = apiMocks.apiSaveScanConfig.mock.calls[0][0].search_keywords
    expect(saved).toContain('title:自定义直播')
    expect(saved).toContain('/tsfile/live/')
    expect(saved).not.toContain('# 自定义规则')
  })

  it('tests only the clicked key and shows account and search results separately', async () => {
    apiMocks.apiScanKeys.mockResolvedValueOnce([{ platform: 'hunter', key_id: 'h-1', key_suffix: '...sample' }])
    let resolveProbe
    apiMocks.apiScanKeyTest.mockReturnValueOnce(new Promise(resolve => { resolveProbe = resolve }))
    wrapper = mount(ScanConfigTab)
    await flushPromises()
    const button = wrapper.findAll('button').find(b => b.text() === '测试可用性')
    await button.trigger('click')
    await button.trigger('click')
    expect(apiMocks.apiScanKeyTest).toHaveBeenCalledOnce()
    expect(apiMocks.apiScanKeyTest).toHaveBeenCalledWith('hunter', 'h-1')
    expect(wrapper.text()).toContain('正在测试')
    resolveProbe({ state: 'permission_denied', summary: '搜索权限受限：不能据此认定 Key 失效', query: 'web.title="电视"', tested_at: '2026-09-14T07:00:00Z', steps: [
      { kind: 'account', endpoint: '/openApi/userInfo', state: 'passed', http_status: 200, code: '200', message: '账号接口认证成功' },
      { kind: 'search', endpoint: '/openApi/search', state: 'permission_denied', http_status: 403, code: '403', message: '账号无 API 访问权限' },
    ] })
    await flushPromises()
    const report = wrapper.get('[aria-label="Key 可用性测试结果"]')
    expect(report.text()).toContain('账号接口 · 通过')
    expect(report.text()).toContain('搜索接口 · 权限受限')
    expect(report.text()).toContain('/openApi/userInfo')
    expect(report.text()).toContain('/openApi/search')
    expect(wrapper.text()).not.toContain('正在测试')
  })

  it('clears previous success and reports uncertainty after a failed retry', async () => {
    wrapper = mount(ScanConfigTab)
    await flushPromises()
    const state = wrapper.vm.$.setupState
    const row = { platform: 'hunter', key_id: 'h-1', _row_key: 'h-1', key_suffix: '...sample' }
    apiMocks.apiScanKeyTest.mockResolvedValueOnce({ state: 'passed', summary: '真实搜索成功', tested_at: '2026-09-14T07:00:00Z', steps: [] })
    await state.testKey(row)
    apiMocks.apiScanKeyTest.mockRejectedValueOnce(new Error('请求超时'))
    await state.testKey(row)
    await flushPromises()
    expect(wrapper.text()).toContain('请求超时')
    expect(wrapper.text()).toContain('不代表 Key 失效')
    expect(wrapper.text()).not.toContain('真实搜索成功')
  })
  it('mounts, loads its data, and exposes the real save handler', async () => {
    wrapper = shallowMount(ScanConfigTab)
    await flushPromises()

    expect(apiMocks.apiScanConfig).toHaveBeenCalledOnce()
    expect(apiMocks.apiScanKeys).toHaveBeenCalledOnce()
    expect(wrapper.vm.save).toBeTypeOf('function')
  })

  it('shows all FOFA balances and keeps zero F points distinct from key validity', async () => {
    apiMocks.apiScanKeys.mockResolvedValueOnce([{ platform: 'fofa', key_id: 'fofa-1', key_suffix: '...sample' }])
    apiMocks.apiScanKeysCredits.mockResolvedValueOnce([{
      platform: 'fofa', key_id: 'fofa-1', credit: 0, verified: true,
      balances: { fcoin: 0, fofa_point: 0, remain_free_point: null, remain_api_query: 42, remain_api_data: 1000 },
    }])
    wrapper = mount(ScanConfigTab)
    await flushPromises()
    expect(wrapper.text()).toContain('F 点：0')
    expect(wrapper.text()).toContain('F 币：0')
    expect(wrapper.text()).toContain('免费 F 点：-')
    expect(wrapper.text()).toContain('月度查询剩余次数：42')
    expect(wrapper.text()).toContain('月度数据剩余条数：1,000')
    expect(wrapper.text()).toContain('Key有效')
    expect(wrapper.text()).not.toContain('不支持余额查询')
    expect(wrapper.text()).not.toContain('余额不足')
  })

  it('keeps refresh loading until the balance request settles', async () => {
    let resolveCredits
    apiMocks.apiScanKeysCredits.mockReturnValueOnce(new Promise(resolve => { resolveCredits = resolve }))
    wrapper = mount(ScanConfigTab)
    await flushPromises()
    const refresh = wrapper.findAllComponents({ name: 'TButton' }).find(button => button.text() === '刷新余额')
    expect(refresh.props('loading')).toBe(true)
    resolveCredits([])
    await flushPromises()
    expect(refresh.props('loading')).toBe(false)
  })

  it('submits a FOFA key with an empty optional email', async () => {
    wrapper = mount(ScanConfigTab)
    await flushPromises()
    const state = wrapper.vm.$.setupState
    state.keyForm.platform = 'fofa'
    state.keyForm.key = 'test-only-key'
    state.keyForm.email = ''
    await state.submitKey()
    expect(apiMocks.apiScanKeyAdd).toHaveBeenCalledWith('fofa', 'test-only-key', '')
  })

  it('saves platform selection and disabled schedule without carrying hidden response fields', async () => {
    apiMocks.apiScanConfig.mockResolvedValueOnce({ enabled_platforms: ['hunter'], daily_full_update: false, update_days: [] })
    apiMocks.apiSaveScanConfig.mockResolvedValueOnce({ enabled_platforms: ['hunter'], deep_concurrent: 99 })
    wrapper = mount(ScanConfigTab)
    await flushPromises()
    await wrapper.vm.save()
    expect(apiMocks.apiSaveScanConfig.mock.calls[0][0]).toMatchObject({ enabled_platforms: ['hunter'], daily_full_update: false, update_days: [] })
    expect(wrapper.vm.$.setupState.scanCfg).not.toHaveProperty('deep_concurrent')
    expect(await wrapper.vm.canLeave()).toBe(true)
  })

  it('blocks saving when loading the persisted configuration fails', async () => {
    apiMocks.apiScanConfig.mockRejectedValueOnce(new Error('offline'))
    wrapper = mount(ScanConfigTab)
    await flushPromises()
    await wrapper.vm.save()
    expect(apiMocks.apiSaveScanConfig).not.toHaveBeenCalled()
    expect(wrapper.find('.scan-config-save-button').attributes('disabled')).toBeDefined()
  })

  it('rejects empty keyword conditions and keeps edits dirty until a successful save', async () => {
    wrapper = mount(ScanConfigTab)
    await flushPromises()
    const state = wrapper.vm.$.setupState
    state.scanCfg.search_keywords = 'title:'
    await wrapper.vm.save()
    expect(apiMocks.apiSaveScanConfig).not.toHaveBeenCalled()
    expect(state.isDirty).toBe(true)
    state.scanCfg.search_keywords = 'title:直播 && body:/iptv/'
    apiMocks.apiSaveScanConfig.mockRejectedValueOnce(new Error('offline'))
    await wrapper.vm.save()
    expect(state.isDirty).toBe(true)
    apiMocks.apiSaveScanConfig.mockResolvedValueOnce({ search_keywords: ['title:直播 && body:/iptv/'] })
    await wrapper.vm.save()
    expect(state.isDirty).toBe(false)
  })

  it('guards reloading and restores the last saved values only after discarding edits', async () => {
    DialogPlugin.confirm.mockReturnValue({ hide: vi.fn() })
    wrapper = mount(ScanConfigTab)
    await flushPromises()
    const state = wrapper.vm.$.setupState
    state.scanCfg.hunter_size = 37
    const reload = state.reloadConfig()
    DialogPlugin.confirm.mock.calls.at(-1)[0].onCancel()
    await reload
    expect(apiMocks.apiScanConfig).toHaveBeenCalledOnce()
    expect(state.scanCfg.hunter_size).toBe(37)
    const leave = wrapper.vm.canLeave()
    DialogPlugin.confirm.mock.calls.at(-1)[0].onConfirm()
    expect(await leave).toBe(true)
    expect(state.scanCfg.hunter_size).toBe(200)
  })
})
