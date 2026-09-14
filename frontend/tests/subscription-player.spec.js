import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import SubscriptionPlayer from '../src/components/SubscriptionPlayer.vue'
import { fetchText } from '../src/api.js'

const mocks = vi.hoisted(() => ({ engines: [], copy: vi.fn(), play: vi.fn() }))
vi.mock('../src/api.js', () => ({ fetchText: vi.fn() }))
vi.mock('../src/composables/useClipboard.js', () => ({ useClipboard: () => ({ copyText: mocks.copy }) }))
vi.mock('hls.js', () => {
  class Hls {
    static isSupported() { return true }
    static Events = { MANIFEST_PARSED: 'manifest', ERROR: 'error' }
    constructor() { this.handlers = {}; this.destroy = vi.fn(); this.loadSource = vi.fn(); this.attachMedia = vi.fn(); mocks.engines.push(this) }
    on(event, handler) { this.handlers[event] = handler }
  }
  return { default: Hls }
})
vi.mock('mpegts.js', () => ({ default: {
  isSupported: () => true, Events: { ERROR: 'error' },
  createPlayer: vi.fn(() => {
    const engine = { handlers: {}, destroy: vi.fn(), attachMediaElement: vi.fn(), load: vi.fn(), on(event, handler) { this.handlers[event] = handler } }
    mocks.engines.push(engine)
    return engine
  }),
} }))

const playlist = '#EXTM3U\n#EXTINF:-1 group-title="新闻",CCTV1\nhttps://tv.test/one.m3u8\n#EXTINF:-1 group-title="新闻",CCTV1\nhttps://tv.test/two.ts\n#EXTINF:-1 group-title="体育",体育频道\nhttps://tv.test/sport.mp4'
let wrapper
function mountPlayer() {
  wrapper = mount(SubscriptionPlayer, { global: { stubs: {
    't-button': { template: '<button><slot /></button>' }, 't-space': { template: '<div><slot /></div>' },
    't-input': { props: ['modelValue'], template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />' },
    't-select': { emits: ['change', 'update:modelValue'], props: ['value', 'modelValue', 'options'], template: '<select :value="value ?? modelValue" @change="$emit(\'change\', options[$event.target.selectedIndex].value); $emit(\'update:modelValue\', options[$event.target.selectedIndex].value)"><option v-for="o in options" :value="o.value">{{ o.label }}</option></select>' },
  } } })
  return wrapper
}
beforeEach(() => {
  vi.useFakeTimers()
  mocks.engines.length = 0
  mocks.copy.mockReset()
  mocks.play.mockReset().mockResolvedValue(undefined)
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(mocks.play)
  vi.spyOn(HTMLMediaElement.prototype, 'canPlayType').mockReturnValue('')
  vi.mocked(fetchText).mockReset().mockResolvedValue(playlist)
})
afterEach(() => { wrapper?.unmount(); wrapper = null; vi.useRealTimers() })

describe('subscription player', () => {
  it('loads the exact tested subscription and waits for user selection', async () => {
    mountPlayer(); await flushPromises()
    expect(fetchText).toHaveBeenCalledWith('/api/subscribe.m3u', expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(wrapper.findAll('.channel-list button')).toHaveLength(2)
    expect(mocks.engines).toHaveLength(0)
    await wrapper.get('input').setValue('体育')
    expect(wrapper.findAll('.channel-list button')).toHaveLength(1)
    await wrapper.get('input').setValue('')
    await wrapper.get('select[aria-label="频道分类"]').setValue('新闻')
    expect(wrapper.findAll('.channel-list button')).toHaveLength(1)
  })

  it('switches ranked routes, destroys old engines and copies the selected route', async () => {
    mountPlayer(); await flushPromises()
    await wrapper.get('.channel-list button').trigger('click'); await flushPromises()
    const first = mocks.engines[0]
    expect(first.loadSource).toHaveBeenCalledWith('https://tv.test/one.m3u8')
    await wrapper.get('select[aria-label="播放线路"]').setValue('1'); await flushPromises()
    expect(first.destroy).toHaveBeenCalledOnce()
    expect(mocks.engines[1].load).toHaveBeenCalledOnce()
    await wrapper.findAll('button').find(b => b.text() === '复制线路地址').trigger('click')
    expect(mocks.copy).toHaveBeenCalledWith('https://tv.test/two.ts')
    wrapper.unmount(); wrapper = null
    expect(mocks.engines[1].destroy).toHaveBeenCalledOnce()
  })

  it('ignores old engine errors and releases resources on fatal playback failure', async () => {
    mountPlayer(); await flushPromises()
    await wrapper.get('.channel-list button').trigger('click'); await flushPromises()
    const first = mocks.engines[0]
    await wrapper.get('select[aria-label="播放线路"]').setValue('1'); await flushPromises()
    first.handlers.error(null, { fatal: true })
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    mocks.engines[1].handlers.error()
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('跨域')
    expect(mocks.engines[1].destroy).toHaveBeenCalledOnce()
  })

  it('reports empty subscriptions and allows retry after loading errors', async () => {
    vi.mocked(fetchText).mockRejectedValueOnce(new Error('network down')).mockResolvedValueOnce('#EXTM3U')
    mountPlayer(); await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('network down')
    await wrapper.findAll('button').find(b => b.text() === '刷新列表').trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('暂无可播放频道')
  })

  it('aborts playlist loading on unmount and never starts a stream afterward', async () => {
    let resolve
    vi.mocked(fetchText).mockReturnValue(new Promise(r => { resolve = r }))
    mountPlayer()
    const signal = vi.mocked(fetchText).mock.calls[0][1].signal
    wrapper.unmount(); wrapper = null
    expect(signal.aborted).toBe(true)
    resolve(playlist); await flushPromises()
    expect(mocks.engines).toHaveLength(0)
  })

  it('times out stalled connections and releases the engine', async () => {
    mountPlayer(); await flushPromises()
    await wrapper.get('.channel-list button').trigger('click'); await flushPromises()
    await vi.advanceTimersByTimeAsync(20000)
    expect(wrapper.get('[role="alert"]').text()).toContain('连接超时')
    expect(mocks.engines[0].destroy).toHaveBeenCalledOnce()
  })

  it('offers manual play when autoplay is blocked, without a false timeout', async () => {
    mocks.play.mockRejectedValue(Object.assign(new Error('blocked'), { name: 'NotAllowedError' }))
    mountPlayer(); await flushPromises()
    await wrapper.findAll('.channel-list button')[1].trigger('click'); await flushPromises()
    expect(wrapper.text()).toContain('浏览器已阻止自动播放')
    await vi.advanceTimersByTimeAsync(20000)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('reports pause and end instead of leaving a stale playing status', async () => {
    mountPlayer(); await flushPromises()
    await wrapper.findAll('.channel-list button')[1].trigger('click'); await flushPromises()
    await wrapper.get('video').trigger('playing')
    expect(wrapper.text()).toContain('正在播放')
    await wrapper.get('video').trigger('pause')
    expect(wrapper.text()).toContain('已暂停')
    await wrapper.get('video').trigger('ended')
    expect(wrapper.text()).toContain('播放已结束')
  })
})
