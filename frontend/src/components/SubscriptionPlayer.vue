<template>
  <section class="subscription-player" aria-label="测速订阅在线播放器">
    <div class="player-toolbar">
      <div><strong>订阅源在线播放</strong><p>读取最新测速通过的订阅列表，选择频道开始播放。</p></div>
      <t-space>
        <t-button size="small" variant="outline" :loading="loading" @click="loadPlaylist">刷新列表</t-button>
        <t-button size="small" variant="text" @click="$emit('close')">关闭播放器</t-button>
      </t-space>
    </div>
    <p v-if="loadError" role="alert" class="player-error">{{ loadError }}</p>
    <p v-else-if="loading" role="status">正在加载订阅列表…</p>
    <p v-else-if="!channels.length" role="status">暂无可播放频道，请先完成全量测速并确认有频道通过。</p>
    <div v-if="channels.length" class="player-layout">
      <div class="channel-panel">
        <t-input v-model="search" aria-label="搜索频道" placeholder="搜索频道" clearable />
        <t-select v-model="group" aria-label="频道分类" :options="groupOptions" />
        <p class="channel-count">{{ filteredChannels.length }} 个频道 · {{ routeCount }} 条线路</p>
        <div class="channel-list" aria-label="频道列表">
          <button v-for="channel in filteredChannels" :key="channel.key" type="button"
            :class="{ selected: selected?.key === channel.key }" :aria-pressed="selected?.key === channel.key"
            @click="selectChannel(channel)">
            <span>{{ channel.name }}</span><small>{{ channel.urls.length }} 条线路</small>
          </button>
          <p v-if="!filteredChannels.length">没有匹配的频道</p>
        </div>
      </div>
      <div class="video-panel">
        <video ref="video" controls playsinline preload="none" aria-label="频道视频"
          @playing="onPlaying" @waiting="onWaiting" @pause="onPause" @ended="onEnded" @error="onVideoError" />
        <template v-if="selected">
          <div class="now-playing"><strong>{{ selected.name }}</strong><span>{{ selected.group }}</span></div>
          <p class="playback-mode">{{ usingProxy ? '代理播放 · 使用服务器 / FRP 带宽' : '直连试看 · 视频不经过服务器转发' }}</p>
          <div class="playback-controls">
            <t-select :value="routeIndex" aria-label="播放线路" :options="routeOptions" @change="changeRoute" />
            <t-select :value="mode" aria-label="播放格式" :options="formatOptions" @change="changeMode" />
            <t-button variant="outline" size="small" @click="startPlayback">重新播放</t-button>
            <t-button variant="outline" size="small" @click="copyRoute">复制线路地址</t-button>
            <t-button v-if="usingProxy" variant="outline" size="small" @click="stopProxy">停止代理，改为直连</t-button>
          </div>
        </template>
        <p v-if="playError" role="alert" class="player-error">{{ playError }}</p>
        <p v-else role="status">{{ status }}</p>
        <p class="player-hint">默认直连试看，失败后自动尝试代理播放（使用服务器 / FRP 带宽）。切换频道、线路或格式后重新优先直连。支持 HLS、HTTP-TS、FLV 及原生视频，H.265 和音频编码支持取决于浏览器。</p>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { fetchText, apiCreatePlaybackSession } from '../api.js'
import { useClipboard } from '../composables/useClipboard.js'
import { parseSubscription, playbackSource } from '../utils/playlist.js'

defineEmits(['close'])
const channels = ref([])
const loading = ref(false)
const loadError = ref('')
const search = ref('')
const group = ref('')
const selected = ref(null)
const routeIndex = ref(0)
const mode = ref('auto')
const video = ref(null)
const status = ref('请选择频道开始播放')
const playError = ref('')
const usingProxy = ref(false)
const proxyAvailable = ref(false)
const { copyText } = useClipboard()
let requestController = null
let playbackController = null
let engine = null
let generation = 0
let startupTimer = null
let mediaActive = false
let autoProxyAllowed = true
function failureHint() {
  return usingProxy.value
    ? '代理播放失败，请检查服务器到源站的连接，或切换线路、格式。代理无法解决浏览器编码不兼容的问题。'
    : '直连播放失败，可能是源站跨域限制、网络连接或编码不兼容。请切换线路或格式。'
}
const formatOptions = [
  { label: '自动识别格式', value: 'auto' }, { label: 'HLS / M3U8', value: 'hls' },
  { label: 'HTTP-TS', value: 'mpegts' }, { label: 'FLV', value: 'flv' }, { label: '原生视频', value: 'native' },
]
const groupOptions = computed(() => [{ label: '全部分类', value: '' }, ...[...new Set(channels.value.map(c => c.group))].map(value => ({ label: value, value }))])
const filteredChannels = computed(() => channels.value.filter(c => (!group.value || c.group === group.value) && c.name.toLowerCase().includes(search.value.trim().toLowerCase())))
const routeCount = computed(() => filteredChannels.value.reduce((sum, c) => sum + c.urls.length, 0))
const routeOptions = computed(() => (selected.value?.urls || []).map((_, value) => ({ label: `线路 ${value + 1}`, value })))

function stopPlayback() {
  generation += 1
  playbackController?.abort()
  playbackController = null
  mediaActive = false
  clearTimeout(startupTimer)
  if (engine) { engine.destroy(); engine = null }
  if (video.value) {
    video.value.pause()
    video.value.removeAttribute('src')
    video.value.load()
  }
}

function failPlayback(message = failureHint()) {
  stopPlayback()
  if (!usingProxy.value && proxyAvailable.value && autoProxyAllowed) {
    usingProxy.value = true
    startPlayback()
    return
  }
  playError.value = message
  status.value = ''
}

async function loadPlaylist() {
  requestController?.abort()
  const controller = new AbortController()
  requestController = controller
  loading.value = true
  loadError.value = ''
  stopPlayback()
  selected.value = null
  usingProxy.value = false
  proxyAvailable.value = false
  channels.value = []
  playError.value = ''
  status.value = '请选择频道开始播放'
  try {
    const text = await fetchText('/api/subscribe.m3u', { signal: controller.signal, cache: 'no-cache' })
    if (controller.signal.aborted) return
    channels.value = parseSubscription(text)
    group.value = ''
    search.value = ''
  } catch (error) {
    if (!controller.signal.aborted) loadError.value = `订阅加载失败：${error.message}`
  } finally {
    if (requestController === controller) loading.value = false
  }
}

function selectChannel(channel) {
  selected.value = channel
  routeIndex.value = 0
  mode.value = 'auto'
  startDirect()
}
function changeRoute(value) { routeIndex.value = value; startDirect() }
function changeMode(value) { mode.value = value; startDirect() }
function startDirect() { autoProxyAllowed = true; usingProxy.value = false; startPlayback() }
function stopProxy() {
  // An explicit stop must not immediately reopen the proxy on another error.
  autoProxyAllowed = false
  usingProxy.value = false
  startPlayback()
}
async function copyRoute() { await copyText(selected.value.urls[routeIndex.value]) }

async function startPlayback() {
  stopPlayback()
  const current = generation
  playError.value = ''
  proxyAvailable.value = false
  if (!selected.value || !video.value) return
  status.value = usingProxy.value ? '正在通过代理连接频道…' : '正在直连频道…'
  try {
    const source = playbackSource(selected.value.urls[routeIndex.value], mode.value)
    proxyAvailable.value = true
    if (usingProxy.value) {
      playbackController = new AbortController()
      const session = await apiCreatePlaybackSession(selected.value.urls[routeIndex.value], source.type, { signal: playbackController.signal })
      if (current !== generation) return
      // Blob workers need an absolute URL even for same-origin requests.
      source.url = new URL(session.url, window.location.origin).href
    } else if (window.location.protocol === 'https:' && new URL(source.url).protocol === 'http:') {
      throw new Error('当前页面为 HTTPS，浏览器会拦截 HTTP 线路直连。')
    }
    mediaActive = true
    startupTimer = setTimeout(() => {
      if (current === generation) failPlayback(usingProxy.value
        ? '代理连接超时，请切换线路，或检查服务器到源站的网络连接。'
        : '直连连接超时，请切换线路。')
    }, 20000)
    const play = async () => {
      if (current !== generation) return
      try { await video.value.play() } catch (error) {
        if (current !== generation) return
        if (error.name === 'NotAllowedError') {
          clearTimeout(startupTimer)
          status.value = '浏览器已阻止自动播放，请点击视频中的播放按钮。'
        } else if (error.name !== 'AbortError') failPlayback()
      }
    }
    if (source.type === 'hls' && !video.value.canPlayType('application/vnd.apple.mpegurl')) {
      const { default: Hls } = await import('hls.js')
      if (current !== generation) return
      if (!Hls.isSupported()) throw new Error('当前浏览器不支持 HLS 播放，请使用外部播放器。')
      engine = new Hls({ enableWorker: true })
      engine.on(Hls.Events.MANIFEST_PARSED, play)
      engine.on(Hls.Events.ERROR, (_, data) => { if (current === generation && data.fatal) failPlayback() })
      engine.loadSource(source.url)
      engine.attachMedia(video.value)
    } else if (['mpegts', 'flv'].includes(source.type)) {
      const { default: mpegts } = await import('mpegts.js')
      if (current !== generation) return
      if (!mpegts.isSupported()) throw new Error('当前浏览器不支持 HTTP-TS / FLV 播放，请使用外部播放器。')
      engine = mpegts.createPlayer({ type: source.type, isLive: true, url: source.url }, { enableWorker: true })
      engine.on(mpegts.Events.ERROR, () => { if (current === generation) failPlayback() })
      engine.attachMediaElement(video.value)
      engine.load()
      await play()
    } else {
      video.value.src = source.url
      await play()
    }
  } catch (error) {
    if (current === generation) failPlayback(error.message || failureHint())
  }
}

function onPlaying() {
  if (!mediaActive) return
  clearTimeout(startupTimer)
  status.value = '正在播放'
}
function onWaiting() { if (mediaActive) status.value = '正在缓冲…' }
function onPause() { if (mediaActive) status.value = '已暂停，点击视频中的播放按钮继续。' }
function onEnded() { if (mediaActive) { clearTimeout(startupTimer); status.value = '播放已结束，可重新播放或切换线路。' } }
function onVideoError() { if (mediaActive && video.value?.error) failPlayback() }
function cleanup() {
  requestController?.abort()
  loading.value = false
  stopPlayback()
  usingProxy.value = false
  status.value = selected.value ? '播放已停止，点击重新播放继续。' : '请选择频道开始播放'
}
onMounted(loadPlaylist)
onDeactivated(cleanup)
onBeforeUnmount(cleanup)
</script>

<style scoped>
.subscription-player { margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--td-border-level-1-color); }
.player-toolbar, .now-playing, .playback-controls { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; }
.player-toolbar { justify-content: space-between; margin-bottom: 16px; }
p { margin: 8px 0; font-size: 13px; line-height: 1.6; }
.player-toolbar p, .player-hint, .channel-count, .now-playing span { color: var(--td-text-color-secondary); }
.player-layout { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 16px; }
.channel-panel { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.channel-list { max-height: 380px; overflow-y: auto; }
.channel-list button { display: flex; justify-content: space-between; align-items: center; gap: 8px; width: 100%; padding: 12px; border: 0; border-radius: 6px; background: transparent; color: var(--td-text-color-primary); cursor: pointer; text-align: left; }
.channel-list button:hover { background: var(--td-bg-color-container-hover); }
.channel-list button.selected { background: var(--td-brand-color-light); color: var(--td-brand-color); }
.channel-list button span { overflow-wrap: anywhere; }
.channel-list small { white-space: nowrap; }
.video-panel { min-width: 0; }
video { display: block; width: 100%; aspect-ratio: 16 / 9; background: #080b12; border-radius: 8px; }
.now-playing { margin: 12px 0; }
.playback-controls :deep(.t-select__wrap) { width: 150px; }
.player-error { color: var(--td-error-color); }
.playback-mode { color: var(--td-text-color-secondary); }
@media (max-width: 768px) {
  .player-layout { grid-template-columns: minmax(0, 1fr); }
  .video-panel { grid-row: 1; }
  .channel-list { max-height: 240px; }
}
</style>
