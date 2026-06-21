<template>
  <div class="testing-tab">
    <!-- 测试控制 -->
    <t-card size="small" :bordered="false" style="margin-bottom:12px">
      <div class="card-label" style="margin-bottom:12px">测试控制</div>
      <t-space>
        <t-button theme="success" :disabled="running" :loading="starting" @click="triggerTest">
          {{ running ? '运行中...' : '立即测试' }}
        </t-button>
        <t-button v-if="running" theme="danger" :disabled="stopping" @click="stopTest">
          {{ stopping ? '终止中...' : '终止测试' }}
        </t-button>
        <span style="font-size:13px;color:var(--td-text-color-placeholder)">{{ statusText }}</span>
      </t-space>
      <div v-if="running || progressVisible" style="margin-top:12px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <span style="font-size:12px;color:var(--td-text-color-secondary)">进度 {{ progressLabel }}</span>
          <span style="font-size:12px;font-weight:600;color:#2563eb">{{ progressPct }}%</span>
        </div>
        <t-progress :percentage="progressPct" status="active" />
        <t-space :size="16" style="margin-top:6px">
          <span style="font-size:12px">已测：<b>{{ processed }}</b></span>
          <span style="font-size:12px;color:#16a34a">通过：<b>{{ passed }}</b></span>
          <span style="font-size:12px;color:#dc2626">失败：<b>{{ failed }}</b></span>
          <span style="font-size:12px">耗时：<b>{{ elapsed }}</b>s</span>
        </t-space>
      </div>
    </t-card>

    <!-- 日志面板 -->
    <t-card size="small" :bordered="false" style="margin-bottom:12px">
      <div class="card-label" style="margin-bottom:8px">实时日志</div>
      <LogPanel
        :entries="logLines"
        :show-count="false"
        empty-text="等待测试开始..."
        @clear="clearLogLines"
      />
    </t-card>

    <!-- 下载链接 -->
    <t-card size="small" :bordered="false">
      <div class="card-label" style="margin-bottom:8px">结果订阅地址</div>
      <p style="font-size:12px;color:var(--td-text-color-placeholder);margin-bottom:12px">
        复制以下地址到播放器，可自动获取最新测速通过的频道列表
      </p>
      <div v-for="fmt in ['txt', 'm3u']" :key="fmt" class="download-row">
        <span style="font-size:12px;color:var(--td-text-color-placeholder);width:36px;text-transform:uppercase">{{ fmt }}</span>
        <t-link :href="downloadUrl(fmt)" target="_blank" theme="primary">{{ downloadUrl(fmt) }}</t-link>
        <t-button variant="outline" size="small" @click="copyLink(fmt)">复制</t-button>
        <t-button variant="outline" size="small" @click="previewResult(fmt)">预览</t-button>
      </div>

      <div class="subscribe-section">
        <div class="subscribe-header">
          <span class="subscribe-title">📺 播放器订阅地址（M3U）</span>
        </div>
        <div class="subscribe-body">
          <div class="subscribe-url-row">
            <t-input :value="subscribeUrl" readonly size="small" />
            <t-button theme="primary" size="small" @click="copySubscribeUrl">复制</t-button>
          </div>
          <div v-if="qrDataUrl" class="qr-section">
            <img :src="qrDataUrl" alt="扫码订阅" class="qr-image" />
            <span class="qr-hint">手机扫码添加订阅</span>
          </div>
        </div>
      </div>

      <!-- 预览 -->
      <div v-if="previewVisible" style="margin-top:12px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <span style="font-size:12px;font-weight:600">{{ previewTitle }}</span>
          <t-space>
            <t-button variant="outline" size="small" @click="copyPreview">复制全部</t-button>
            <t-button variant="outline" size="small" @click="previewVisible = false">关闭</t-button>
          </t-space>
        </div>
        <pre class="preview-content">{{ previewContent }}</pre>
        <div style="font-size:11px;color:var(--td-text-color-placeholder);margin-top:6px">{{ previewStats }}</div>
      </div>
    </t-card>
  </div>
</template>

<script setup>
import { ref, watch, inject, computed, onMounted } from 'vue'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import QRCode from 'qrcode'
import { apiTriggerTest, apiStopTest, apiPreviewResult, apiDownloadUrl } from '../api.js'
import { useTheme } from '../composables/useTheme.js'
import LogPanel from './LogPanel.vue'

const emit = defineEmits(['test-finished'])

const testProgress = inject('testProgress', { running: false, processed: 0, passed: 0, failed: 0, elapsed: 0, total: 0, lines: [] })
const clearTestLogs = inject('clearTestLogs', () => {})
const startGlobalPoll = inject('startGlobalPoll', () => {})

const running = computed(() => testProgress.running)
const processed = computed(() => testProgress.processed)
const passed = computed(() => testProgress.passed)
const failed = computed(() => testProgress.failed)
const elapsed = computed(() => testProgress.elapsed)
const logLines = computed(() => testProgress.lines)
const progressPct = computed(() => {
  const t = testProgress.total || 0
  return t > 0 ? Math.min(100, Math.round(testProgress.processed / t * 100)) : 0
})

const starting = ref(false)
const stopping = ref(false)
const statusText = ref('空闲')
const progressVisible = ref(false)
const wasRunning = ref(false)
const testFinished = ref(false)
const progressLabel = computed(() => {
  if (testFinished.value) return '测试完成'
  const t = testProgress.total || 0
  return t > 0 ? `${testProgress.processed} / ${t}` : '准备中...'
})
const previewVisible = ref(false)
const previewTitle = ref('')
const previewContent = ref('')
const previewStats = ref('')

const { theme } = useTheme()
const qrDataUrl = ref('')
const subscribeUrl = computed(() => `${window.location.origin}/api/subscribe.m3u`)

async function generateQR() {
  try {
    const isDark = theme.value === 'dark'
    qrDataUrl.value = await QRCode.toDataURL(subscribeUrl.value, {
      width: 200,
      margin: 2,
      color: {
        dark: isDark ? '#e5edf7' : '#000000',
        light: isDark ? '#1e293b' : '#ffffff',
      }
    })
  } catch (e) {
    console.warn('QR generation failed:', e)
  }
}

watch(theme, () => { generateQR() })
onMounted(() => { generateQR() })

async function copySubscribeUrl() {
  try {
    await navigator.clipboard.writeText(subscribeUrl.value)
    MessagePlugin.success('订阅地址已复制')
  } catch {
    const ta = document.createElement('textarea')
    ta.value = subscribeUrl.value
    ta.style.position = 'fixed'; ta.style.opacity = '0'
    document.body.appendChild(ta); ta.select(); document.execCommand('copy')
    document.body.removeChild(ta)
    MessagePlugin.success('订阅地址已复制')
  }
}

async function triggerTest() {
  starting.value = true
  try {
    const res = await apiTriggerTest()
    if (res.ok) {
      MessagePlugin.success('测试已启动')
      clearTestLogs()
      testProgress.running = true
      testFinished.value = false
      progressVisible.value = true
      statusText.value = '运行中...'
      startGlobalPoll()
    } else {
      MessagePlugin.error(res.error || '启动失败')
    }
  } catch (e) { MessagePlugin.error('启动失败: ' + e.message) }
  finally { starting.value = false }
}

async function stopTest() {
  const confirmed = await DialogPlugin.confirm({
    header: '确认终止',
    body: '终止后当前进度将丢失，确认终止？',
    theme: 'warning',
    confirmBtn: { theme: 'danger' }
  })
  if (!confirmed) return
  stopping.value = true
  try {
    await apiStopTest()
    MessagePlugin.success('已请求终止')
  } catch (e) { MessagePlugin.error('终止失败: ' + e.message) }
  finally { stopping.value = false }
}

async function clearLogLines() {
  const confirmed = await DialogPlugin.confirm({
    header: '确认清空',
    body: '清空后日志将无法恢复，确认清空？',
    theme: 'warning',
    confirmBtn: { theme: 'danger' }
  })
  if (!confirmed) return
  clearTestLogs()
}

function downloadUrl(fmt) { return location.origin + apiDownloadUrl(fmt) }

function copyLink(fmt) {
  const url = downloadUrl(fmt)
  navigator.clipboard?.writeText(url)
    .then(() => MessagePlugin.success('已复制'))
    .catch(() => MessagePlugin.error('复制失败'))
}

async function previewResult(fmt) {
  previewVisible.value = true
  previewTitle.value = fmt.toUpperCase() + ' 预览'
  previewContent.value = '加载中...'
  previewStats.value = ''
  try {
    const text = await apiPreviewResult(fmt)
    previewContent.value = text
    const lines = text.split('\n').filter(l => l.trim())
    if (fmt === 'txt') {
      const ch = lines.filter(l => !l.startsWith('#') && !l.includes('#genre#'))
      const genres = lines.filter(l => l.includes('#genre#'))
      previewStats.value = `共 ${genres.length} 个分类，${ch.length} 条频道记录，${text.length} 字符`
    } else {
      const ch = lines.filter(l => l.startsWith('#EXTINF'))
      previewStats.value = `共 ${ch.length} 个频道，${text.length} 字符`
    }
  } catch (e) { previewContent.value = '加载失败: ' + e.message }
}

function copyPreview() {
  if (!previewContent.value) return
  navigator.clipboard?.writeText(previewContent.value)
    .then(() => MessagePlugin.success('已复制'))
    .catch(() => MessagePlugin.error('复制失败'))
}

// 监听全局测试状态变化
watch(() => testProgress.running, (isRunning) => {
  if (isRunning) {
    wasRunning.value = true
    testFinished.value = false
    progressVisible.value = true
    statusText.value = '运行中...'
  } else if (wasRunning.value) {
    wasRunning.value = false
    testFinished.value = true
    statusText.value = '已完成'
    emit('test-finished')
    MessagePlugin.success('测试已完成')
  }
}, { immediate: true })

// Auto-scroll is handled internally by LogPanel component
</script>

<style scoped>
.testing-tab { padding-top: 4px; }
.card-label { font-size: 12px; font-weight: 600; color: var(--td-text-color-secondary); margin-bottom: 12px; }
.download-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.preview-content { background: #1e1e2e; color: #cdd6f4; font-family: 'Cascadia Code','Fira Code',Consolas,monospace; font-size: 12px; line-height: 1.6; max-height: 400px; overflow: auto; padding: 12px; border-radius: 8px; white-space: pre-wrap; word-break: break-all; margin: 0; }
.subscribe-section { margin-top: 12px; border: 1px solid var(--td-border-level-1-color); border-radius: 8px; overflow: hidden; }
.subscribe-header { background: var(--td-bg-color-secondarycontainer); padding: 8px 16px; }
.subscribe-title { font-weight: 600; font-size: 14px; }
.subscribe-body { padding: 16px; }
.subscribe-url-row { display: flex; gap: 8px; align-items: center; }
.qr-section { margin-top: 12px; text-align: center; }
.qr-image { width: 160px; height: 160px; border-radius: 4px; }
.qr-hint { display: block; margin-top: 8px; font-size: 12px; color: var(--td-text-color-placeholder); }
</style>
