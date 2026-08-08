<template>
  <div class="testing-tab">
    <!-- 测试控制 -->
    <t-card size="small" :bordered="false" class="panel-card">
      <div class="section-header">
        <div class="section-title">测试控制</div>
        <p class="section-subtitle">启动一次完整测速，并在当前页面持续查看执行进度。</p>
      </div>
      <div class="control-toolbar">
        <t-button theme="success" :disabled="running" :loading="starting" @click="triggerTest">
          {{ running ? '运行中...' : '立即测试' }}
        </t-button>
        <t-button v-if="running" theme="danger" :disabled="stopping" @click="stopTest">
          {{ stopping ? '终止中...' : '终止测试' }}
        </t-button>
        <span class="status-text">{{ statusText }}</span>
      </div>
      <div v-if="running || progressVisible" class="progress-section">
        <div class="progress-head">
          <span class="progress-label">进度 {{ progressLabel }}</span>
          <span class="progress-value">{{ progressPct }}%</span>
        </div>
        <t-progress :percentage="progressPct" status="active" />
        <div class="progress-stats">
          <span>已测：<b>{{ processed }}</b></span>
          <span class="stat-pass">通过：<b>{{ passed }}</b></span>
          <span class="stat-fail">失败：<b>{{ failed }}</b></span>
          <span>耗时：<b>{{ elapsed }}</b>s</span>
        </div>
      </div>
    </t-card>

    <!-- 日志面板 -->
    <t-card size="small" :bordered="false" class="panel-card">
      <div class="section-header section-header--compact">
        <div class="section-title">实时日志</div>
        <p class="section-subtitle">查看当前测速轮次的最新输出。</p>
      </div>
      <LogPanel
        :entries="logLines"
        :show-count="false"
        download-name="iptv-test-session.log"
        empty-text="等待测试开始..."
        @clear="clearLogLines"
      />
    </t-card>

    <!-- 下载链接 -->
    <t-card size="small" :bordered="false" class="panel-card panel-card--last">
      <div class="section-header section-header--compact">
        <div class="section-title">结果订阅地址</div>
        <p class="section-subtitle">复制以下地址到播放器，可自动获取最新测速通过的频道列表。</p>
      </div>
      <div v-for="fmt in ['txt', 'm3u']" :key="fmt" class="download-row">
        <span class="download-format">{{ fmt }}</span>
        <t-link :href="downloadUrl(fmt)" target="_blank" theme="primary" class="download-link">{{ downloadUrl(fmt) }}</t-link>
        <div class="download-actions">
          <t-button variant="outline" size="small" @click="copyLink(fmt)">复制</t-button>
          <t-button variant="outline" size="small" @click="previewResult(fmt)">预览</t-button>
        </div>
      </div>

      <div class="subscribe-section">
        <div class="subscribe-header">
          <span class="subscribe-title">📺 播放器订阅地址（M3U）</span>
        </div>
        <div class="subscribe-body">
          <div class="subscribe-url-row">
            <t-input :value="subscribeUrl" readonly size="small" class="subscribe-input" />
            <t-button theme="primary" size="small" @click="copySubscribeUrl">复制</t-button>
          </div>
          <div v-if="qrDataUrl" class="qr-section">
            <img :src="qrDataUrl" alt="扫码订阅" class="qr-image" />
            <span class="qr-hint">手机扫码添加订阅</span>
          </div>
        </div>
      </div>

      <!-- 预览 -->
      <div v-if="previewVisible" class="preview-section">
        <div class="preview-header">
          <span class="preview-title">{{ previewTitle }}</span>
          <t-space>
            <t-button variant="outline" size="small" @click="copyPreview">复制全部</t-button>
            <t-button variant="outline" size="small" @click="previewVisible = false">关闭</t-button>
          </t-space>
        </div>
        <pre class="preview-content">{{ previewContent }}</pre>
        <div class="preview-stats">{{ previewStats }}</div>
      </div>
    </t-card>
  </div>
</template>

<script setup>
import { ref, watch, inject, computed, onMounted } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next/es/message/index.mjs'
import { DialogPlugin } from 'tdesign-vue-next/es/dialog/index.mjs'
import QRCode from 'qrcode'
import { apiTriggerTest, apiStopTest, apiPreviewResult, apiDownloadUrl } from '../api.js'
import { useTheme } from '../composables/useTheme.js'
import { useClipboard } from '../composables/useClipboard.js'
import LogPanel from './LogPanel.vue'

const emit = defineEmits(['test-finished'])
defineProps({
  active: { type: Boolean, default: true },
  task: { type: Object, default: null },
})

const testProgress = inject('testProgress', { running: false, processed: 0, passed: 0, failed: 0, elapsed: 0, total: 0, lines: [] })
const clearTestLogs = inject('clearTestLogs', () => {})
const registerTask = inject('registerTask', () => null)

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

const { copyText } = useClipboard()

async function copySubscribeUrl() {
  const ok = await copyText(subscribeUrl.value)
  if (ok) MessagePlugin.success('订阅地址已复制')
}

async function triggerTest() {
  starting.value = true
  try {
    const res = await apiTriggerTest()
    registerTask('test', res)
    MessagePlugin.success('测试已启动')
    clearTestLogs()
    testProgress.running = true
    testFinished.value = false
    progressVisible.value = true
    statusText.value = '运行中...'
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
.testing-tab {
  padding-top: 4px;
}

.panel-card {
  margin-bottom: 16px;
  border: 1px solid var(--td-border-level-1-color, #e5e7eb);
  border-radius: 12px;
  background: var(--td-bg-color-container, #ffffff);
  box-shadow: none;
}

.panel-card--last {
  margin-bottom: 0;
}

.section-header {
  margin-bottom: 14px;
}

.section-header--compact {
  margin-bottom: 12px;
}

.section-title {
  color: var(--td-text-color-primary, #111827);
  font-size: 16px;
  font-weight: 600;
}

.section-subtitle {
  margin: 4px 0 0;
  color: var(--td-text-color-placeholder, #6b7280);
  font-size: 12px;
  line-height: 1.6;
}

.control-toolbar,
.progress-head,
.progress-stats,
.preview-header,
.download-actions,
.subscribe-url-row {
  display: flex;
  align-items: center;
}

.control-toolbar,
.progress-stats,
.download-actions {
  flex-wrap: wrap;
  gap: 10px;
}

.status-text {
  color: var(--td-text-color-placeholder, #6b7280);
  font-size: 13px;
}

.progress-section {
  margin-top: 14px;
  padding-top: 14px;
  border-top: 1px solid var(--td-border-level-1-color, #e5e7eb);
}

.progress-head {
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}

.progress-label,
.progress-value,
.progress-stats {
  font-size: 12px;
}

.progress-label {
  color: var(--td-text-color-secondary, #4b5563);
}

.progress-value {
  color: var(--td-brand-color, #2563eb);
  font-weight: 600;
}

.progress-stats {
  margin-top: 8px;
  color: var(--td-text-color-secondary, #4b5563);
}

.stat-pass {
  color: var(--td-success-color, #16a34a);
}

.stat-fail {
  color: var(--td-error-color, #dc2626);
}

.download-row {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 10px 0;
  border-bottom: 1px solid var(--td-border-level-1-color, #e5e7eb);
}

.download-row:last-of-type {
  border-bottom: 0;
}

.download-format {
  color: var(--td-text-color-placeholder, #6b7280);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
}

.download-link {
  min-width: 0;
  overflow: hidden;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--td-border-level-1-color, #e5e7eb);
}

.preview-header {
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 8px;
}

.preview-title {
  color: var(--td-text-color-primary, #111827);
  font-size: 12px;
  font-weight: 600;
}

.preview-content {
  max-height: 400px;
  margin: 0;
  overflow: auto;
  padding: 12px;
  border-radius: 8px;
  background: #1e1e2e;
  color: #cdd6f4;
  font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
}

.preview-stats {
  margin-top: 6px;
  color: var(--td-text-color-placeholder, #6b7280);
  font-size: 11px;
}

.subscribe-section {
  margin-top: 16px;
  overflow: hidden;
  border: 1px solid var(--td-border-level-1-color, #e5e7eb);
  border-radius: 10px;
}

.subscribe-header {
  padding: 10px 14px;
  background: var(--td-bg-color-secondarycontainer, #f3f4f6);
}

.subscribe-title {
  font-size: 14px;
  font-weight: 600;
}

.subscribe-body {
  padding: 14px;
}

.subscribe-url-row {
  gap: 8px;
}

.subscribe-input {
  min-width: 0;
  flex: 1;
}

.qr-section {
  margin-top: 14px;
  text-align: center;
}

.qr-image {
  width: 160px;
  height: 160px;
  max-width: 100%;
  border-radius: 6px;
}

.qr-hint {
  display: block;
  margin-top: 8px;
  color: var(--td-text-color-placeholder);
  font-size: 12px;
}

@media (max-width: 640px) {
  .control-toolbar {
    align-items: stretch;
  }

  .control-toolbar :deep(.t-button) {
    flex: 1 1 140px;
  }

  .status-text {
    flex-basis: 100%;
  }

  .download-row {
    grid-template-columns: 40px minmax(0, 1fr);
  }

  .download-link {
    overflow: visible;
    text-overflow: clip;
    white-space: normal;
    word-break: break-all;
  }

  .download-actions {
    grid-column: 2;
  }

  .download-actions :deep(.t-button) {
    flex: 1 1 96px;
  }

  .subscribe-url-row {
    align-items: stretch;
    flex-direction: column;
  }

  .subscribe-url-row :deep(.t-button) {
    width: 100%;
  }
}
</style>
