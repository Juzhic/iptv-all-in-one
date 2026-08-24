import { flushPromises, shallowMount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ScanConfigTab from '../src/components/ScanConfigTab.vue'

const apiMocks = vi.hoisted(() => ({
  apiSaveScanConfig: vi.fn(),
  apiScanConfig: vi.fn(() => Promise.resolve({})),
  apiScanKeyAdd: vi.fn(),
  apiScanKeyDelete: vi.fn(),
  apiScanKeys: vi.fn(() => Promise.resolve([])),
  apiScanKeysCredits: vi.fn(() => Promise.resolve([])),
  apiScanKeyUpdate: vi.fn(),
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
  it('mounts, loads its data, and exposes the real save handler', async () => {
    wrapper = shallowMount(ScanConfigTab)
    await flushPromises()

    expect(apiMocks.apiScanConfig).toHaveBeenCalledOnce()
    expect(apiMocks.apiScanKeys).toHaveBeenCalledOnce()
    expect(wrapper.vm.save).toBeTypeOf('function')
  })
})
