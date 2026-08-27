<template>
  <div class="scanner-tab">
    <t-card size="small" :bordered="false" class="panel-card workspace-card">
      <div class="section-title">测绘采集</div>
      <p class="section-subtitle">从测绘平台、搜索引擎及补探测流程发现候选地址，验证后写入候选源池。</p>
      <t-space class="scan-actions">
        <t-button theme="success" :disabled="scanRunning" :loading="scanStarting" @click="triggerScan">
          {{ startButtonText }}
        </t-button>
        <t-button v-if="scanRunning" theme="danger" :disabled="scanStopping" @click="stopScan">
          {{ scanStopping ? '停止中...' : '停止采集' }}
        </t-button>
        <t-button variant="outline" theme="warning" :disabled="scanClearing" @click="forceClear">
          {{ scanClearing ? '重置中...' : '重置卡死状态' }}
        </t-button>
      </t-space>
      <p class="section-subtitle clear-hint">仅在进度卡住、或点“开始”提示“正在进行中”但没有实际任务时使用；不会清空日志和历史记录。</p>
    </t-card>

    <t-card size="small" :bordered="false" class="panel-card workspace-card">
      <div class="section-title">采集进度</div>
      <span class="phase-text">{{ phaseText }}</span>
      <div v-if="scanRunning || progressVisible" class="progress-wrap">
        <div class="progress-head">
          <span class="progress-label">{{ progressLabel }}</span>
          <span class="progress-value">{{ progressPct }}%</span>
        </div>
        <t-progress :percentage="progressPct" />
      </div>
      <LogPanel
        :entries="scanLogLines"
        :show-count="false"
        download-name="iptv-channel-scan-session.log"
        empty-text="等待采集开始..."
        @clear="clearScanLogLines"
      />
    </t-card>

    <div v-if="showScanError" class="scan-error" role="alert">
      <div class="scan-error-main">
        <span class="scan-error-label">最近一次采集失败</span>
        <span class="scan-error-message">{{ scanSummary.error }}</span>
      </div>
      <t-button size="small" theme="danger" variant="outline" :disabled="scanRunning || scanStarting" @click="triggerScan">
        重新采集
      </t-button>
    </div>

    <div class="summary-head" :class="{ 'is-failed': showScanError }">
      <div>
        <div class="section-title summary-title">采集概览</div>
        <div class="summary-caption">{{ summaryCaption }}</div>
      </div>
      <div class="summary-status" :class="summaryStatusTone">{{ summaryStatusText }}</div>
    </div>

    <div class="stats-grid">
      <t-card
        v-for="card in statCards"
        :key="card.key"
        size="small"
        :bordered="false"
        class="stat-card workspace-card"
        :class="card.tone"
      >
        <div class="stat-top">
          <span class="stat-badge">{{ card.badge }}</span>
          <span class="stat-foot">{{ card.foot }}</span>
        </div>
        <div class="stat-value">{{ formatMetric(card.value) }}</div>
        <div class="stat-label">{{ card.label }}</div>
        <div class="stat-sub">{{ card.sub }}</div>
      </t-card>
    </div>
  </div>
</template>

<script setup>
import { computed, inject, onActivated, onBeforeUnmount, onDeactivated, onMounted, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next/es/message/index.mjs'
import { DialogPlugin } from 'tdesign-vue-next/es/dialog/index.mjs'
import { apiScanForceClear, apiScanLatest, apiScanStatus, apiScanStop, apiScanTrigger, connectScanSse, shouldUseSse } from '../api.js'
import { useAdaptivePolling, taskIsRunning } from '../composables/useAdaptivePolling.js'
import { normalizeTask, readTaskId } from '../utils/tasks.js'
import LogPanel from './LogPanel.vue'

const props = defineProps({
  active: { type: Boolean, default: true },
  task: { type: Object, default: null },
})
const registerTask = inject('registerTask', () => null)
const currentTaskId = ref(props.task?.task_id || readTaskId('scan'))

watch(() => props.task, (task) => {
  if (task?.task_id) currentTaskId.value = task.task_id
}, { immediate: true })

const scanRunning = ref(false)
const scanStarting = ref(false)
const scanStopping = ref(false)
const scanClearing = ref(false)
const currentPhase = ref('idle')
const phaseText = ref('空闲')
const progressVisible = ref(false)
const progressLabel = ref('')
const progressPct = ref(0)
const scanLogLines = ref([])
const scanSummary = ref(createEmptySummary())

let lastLogSeq = 0
let wasRunning = false
let triggerPending = false
let scanEventSource = null

function createEmptySummary() {
  return {
    scanId: '',
    status: '',
    startedAt: '',
    finishedAt: '',
    durationSeconds: 0,
    totalRaw: 0,
    totalDeduped: 0,
    totalFastPass: 0,
    totalDeepPass: 0,
    error: '',
  }
}

function normalizeSummary(raw) {
  if (!raw || typeof raw !== 'object') return createEmptySummary()
  return {
    scanId: raw.scan_id || '',
    status: raw.status || '',
    startedAt: raw.started_at || '',
    finishedAt: raw.finished_at || '',
    durationSeconds: Number(raw.duration_seconds) || 0,
    totalRaw: Number(raw.total_raw) || 0,
    totalDeduped: Number(raw.total_deduped) || 0,
    totalFastPass: Number(raw.total_fast_pass) || 0,
    totalDeepPass: Number(raw.total_deep_pass) || 0,
    error: raw.error || '',
  }
}

function phaseName(phase) {
  return ({
    idle: '空闲',
    collecting: '采集中',
    fast_filter: '快速过滤',
    deep_check: '深度检测',
    health_check: '健康检查',
  })[phase] || phase || '空闲'
}

function buildPhaseText(phase, message) {
  const label = phaseName(phase)
  if (!message || message === label) return label
  return `${label} · ${message}`
}

function appendLogs(lines) {
  if (!Array.isArray(lines) || !lines.length) return
  lines.forEach((line) => {
    const seq = Number(line.seq)
    if (Number.isFinite(seq) && seq <= lastLogSeq) return
    scanLogLines.value.push(line)
    if (Number.isFinite(seq)) lastLogSeq = seq
  })
  // 限制日志行数，避免 DOM 性能恶化
  const MAX_LOG_LINES = 2000
  if (scanLogLines.value.length > MAX_LOG_LINES) {
    scanLogLines.value = scanLogLines.value.slice(-1500)
  }
}

function applyProgressPatch(data = {}) {
  scanRunning.value = true
  progressVisible.value = true
  triggerPending = false
  wasRunning = true
  startPoll()
  currentPhase.value = data.phase || currentPhase.value
  phaseText.value = buildPhaseText(currentPhase.value, data.message)

  const backendPercent = Number(data.percent)
  if (Number.isFinite(backendPercent)) {
    progressPct.value = Math.max(0, Math.min(100, Math.round(backendPercent)))
  }
  if (data.message) {
    progressLabel.value = data.message
  }
}

function handleScanStreamError() {
  disconnectScanStream()
  if (scanRunning.value || wasRunning || triggerPending) {
    startPoll()
  }
}

async function connectScanStream() {
  disconnectScanStream()
  if (!await shouldUseSse()) {
    startPoll()
    return
  }
  try {
    scanEventSource = connectScanSse({
      status(event) {
        try {
          applyStatus(JSON.parse(event.data))
        } catch (_) {}
      },
      progress(event) {
        try {
          applyProgressPatch(JSON.parse(event.data))
        } catch (_) {}
      },
      log(event) {
        try {
          appendLogs([JSON.parse(event.data)])
        } catch (_) {}
      },
      scan_complete(event) {
        try {
          refreshStatus()
        } catch (_) {}
        disconnectScanStream()
      },
      onerror: handleScanStreamError,
    })
  } catch (_) {
    startPoll()
  }
}

function disconnectScanStream() {
  if (scanEventSource) {
    scanEventSource.close()
    scanEventSource = null
  }
}

function applyStatus(data = {}) {
  const statusTask = normalizeTask(data.task, 'scan')
  if (statusTask?.task_id && currentTaskId.value && statusTask.task_id !== currentTaskId.value) return
  if (statusTask) {
    registerTask('scan', statusTask)
    if (statusTask.task_id) currentTaskId.value = statusTask.task_id
  }
  const running = data.running != null ? Boolean(data.running) : taskIsRunning(statusTask)
  // 刚点“开始采集”后，后端可能还没把 running 翻成 true。
  // triggerPending 期间（10s 内）忽略 running=false，避免把刚启动的采集误判为已完成。
  if (!running && triggerPending) return

  const nextSummary = normalizeSummary(data.summary)
  const statusMessage = !running && nextSummary.status === 'failed' && nextSummary.error
    ? nextSummary.error
    : data.message

  scanRunning.value = running
  currentPhase.value = data.phase || 'idle'
  phaseText.value = buildPhaseText(data.phase, statusMessage)

  const total = Number(data.total) || 0
  const processed = Number(data.processed) || 0
  const backendPercent = Number(data.percent)
  progressPct.value = Number.isFinite(backendPercent)
    ? Math.max(0, Math.min(100, Math.round(backendPercent)))
    : (total > 0 ? Math.min(100, Math.round(processed / total * 100)) : 0)
  progressLabel.value = total > 0
    ? `进度 ${Math.min(total, processed)} / ${total}`
    : (statusMessage || (running ? '准备中...' : '暂无进行中的采集任务'))
  progressVisible.value = running || progressPct.value > 0 || scanLogLines.value.length > 0

  scanSummary.value = nextSummary
  appendLogs(data.lines)

  if (running) {
    triggerPending = false
    wasRunning = true
    return
  }

  if (wasRunning) {
    wasRunning = false
    const terminalError = data.error || (nextSummary.status === 'failed' ? nextSummary.error : '')
    if (terminalError) MessagePlugin.error(`采集异常: ${terminalError}`)
    else MessagePlugin.success(data.message || (currentPhase.value === 'health_check' ? '健康检查已完成' : '采集已完成'))
    disconnectScanStream()
    return
  }

  disconnectScanStream()
}

async function refreshStatus() {
  try {
    const data = await apiScanStatus(currentTaskId.value)
    if (!data?.summary?.scan_id) {
      try {
        data.summary = await apiScanLatest()
      } catch (_) {}
    }
    applyStatus(data)
    return data
  } catch (_) {}
}

const hasSummary = computed(() => Boolean(scanSummary.value.scanId))

const showScanError = computed(() => (
  !scanRunning.value &&
  scanSummary.value.status === 'failed' &&
  Boolean(scanSummary.value.error)
))

const startButtonText = computed(() => {
  if (scanStarting.value) return '启动中...'
  if (scanRunning.value) return '采集中...'
  return '开始采集'
})

const summaryCaption = computed(() => {
  if (!hasSummary.value) return '还没有采集记录，启动一次采集后这里会显示最近一次摘要。'
  if (scanSummary.value.status === 'failed' && scanSummary.value.error) {
    const time = scanSummary.value.finishedAt || scanSummary.value.startedAt
    return time ? `最近一次采集失败时间：${time}` : '最近一次采集失败，已保留阶段统计。'
  }
  const time = scanSummary.value.finishedAt || scanSummary.value.startedAt
  return time ? `最近一次采集时间：${time}` : '最近一次采集摘要'
})

const summaryStatusText = computed(() => {
  if (scanRunning.value) return phaseName(currentPhase.value)
  if (!hasSummary.value) return '等待采集'
  return ({
    running: '进行中',
    completed: '已完成',
    failed: '失败',
    stopped: '已停止',
  })[scanSummary.value.status] || '最近记录'
})

const summaryStatusTone = computed(() => {
  if (scanRunning.value) return 'running'
  if (!hasSummary.value) return 'idle'
  return ({
    completed: 'success',
    failed: 'danger',
    stopped: 'idle',
    running: 'running',
  })[scanSummary.value.status] || 'idle'
})

const statCards = computed(() => [
  {
    key: 'raw',
    badge: 'RAW',
    tone: 'blue',
    value: scanSummary.value.totalRaw,
    label: '原始结果',
    sub: '平台采集返回的频道地址总数',
    foot: hasSummary.value ? `去重候选 ${scanSummary.value.totalDeduped} 条` : '等待采集生成数据',
  },
  {
    key: 'fast',
    badge: 'FAST',
    tone: 'green',
    value: scanSummary.value.totalFastPass,
    label: '快速过滤',
    sub: '通过去重和基础连通性校验的频道数量',
    foot: hasSummary.value ? '适合进入深度检测阶段' : '运行采集后自动更新',
  },
  {
    key: 'deep',
    badge: 'DEEP',
    tone: 'purple',
    value: scanSummary.value.totalDeepPass,
    label: '深度可用',
    sub: '通过深度可用性检测的候选频道数量',
    foot: hasSummary.value ? '可用于后续全量测速或候选导出' : '深度检测完成后显示',
  },
])

function formatMetric(value) {
  if (!hasSummary.value) return '--'
  return String(value ?? 0)
}

const { start: startPoll, stop: stopPoll, setRunning: setPollRunning } = useAdaptivePolling(refreshStatus, {
  active: computed(() => props.active),
  runningDelay: 2000,
  idleDelay: 10000,
  getRunning: data => Boolean(data?.running) || taskIsRunning(data?.task),
})

async function triggerScan() {
  scanStarting.value = true
  triggerPending = true
  try {
    const res = await apiScanTrigger()
    const task = registerTask('scan', res)
    if (task?.task_id) currentTaskId.value = task.task_id
    MessagePlugin.success('测绘采集已启动')
    scanLogLines.value = []
    lastLogSeq = 0
    wasRunning = true
    progressVisible.value = true
    phaseText.value = '采集启动中...'
    progressLabel.value = '正在连接采集任务...'
    connectScanStream()
    setPollRunning(true)
    startPoll()
    setTimeout(() => { triggerPending = false }, 10000)
  } catch (_) {
    MessagePlugin.error('启动失败')
    triggerPending = false
  } finally {
    scanStarting.value = false
  }
}

async function stopScan() {
  const confirmed = await DialogPlugin.confirm({
    header: '确认停止',
    body: '停止后当前采集进度将丢失，确认停止？',
    theme: 'warning',
    confirmBtn: { theme: 'danger' }
  })
  if (!confirmed) return
  scanStopping.value = true
  try {
    const res = await apiScanStop()
    MessagePlugin.success(res.message || '已请求终止')
    await refreshStatus()
  } catch (_) {
    MessagePlugin.error('终止失败')
  } finally {
    scanStopping.value = false
  }
}

async function forceClear() {
  const confirmed = await DialogPlugin.confirm({
    header: '确认清除',
    body: '强制清除将重置采集状态，确认继续？',
    theme: 'warning',
    confirmBtn: { theme: 'danger' }
  })
  if (!confirmed) return
  scanClearing.value = true
  try {
    const res = await apiScanForceClear()
    MessagePlugin.success(res.message || '采集状态已清除')
    // 清除残留状态：复位本地标志并停止轮询，避免守卫继续吞掉状态
    triggerPending = false
    wasRunning = false
    await refreshStatus()
    setPollRunning(false)
  } catch (_) {
    MessagePlugin.error('清除失败')
  } finally {
    scanClearing.value = false
  }
}

async function clearScanLogLines() {
  const confirmed = await DialogPlugin.confirm({
    header: '确认清空',
    body: '清空后日志将无法恢复，确认清空？',
    theme: 'warning',
    confirmBtn: { theme: 'danger' }
  })
  if (!confirmed) return
  scanLogLines.value = []
}

onMounted(async () => {
  startPoll()
  await refreshStatus()
  if (scanRunning.value) {
    progressVisible.value = true
    connectScanStream()
    startPoll()
  }
})

onActivated(() => {
  startPoll()
  if (scanRunning.value) connectScanStream()
})

onDeactivated(() => {
  disconnectScanStream()
  stopPoll()
})

onBeforeUnmount(() => {
  disconnectScanStream()
  stopPoll()
})
</script>

<style scoped>
.scanner-tab {
  padding-top: 4px;
}

.panel-card {
  margin-bottom: 16px;
  background: var(--td-bg-color-container);
  border-radius: var(--app-radius-lg, 18px);
}

.section-title {
  margin-bottom: 10px;
  font-size: 15px;
  font-weight: 600;
}

.section-subtitle {
  margin-bottom: 12px;
  font-size: 13px;
  color: var(--td-text-color-placeholder, #6b7280);
}

.clear-hint {
  margin-top: 10px;
  margin-bottom: 0;
  font-size: 12px;
}

.phase-text {
  font-size: 13px;
  color: var(--td-text-color-placeholder, #6b7280);
}

.progress-wrap {
  margin-top: 12px;
}

.progress-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}

.progress-label {
  font-size: 12px;
  color: var(--td-text-color-secondary, #4b5563);
}

.progress-value {
  font-size: 12px;
  font-weight: 700;
  color: #2563eb;
}

.summary-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  padding-top: 2px;
}

.summary-title {
  margin-bottom: 4px;
}

.summary-caption {
  font-size: 12px;
  line-height: 1.6;
  color: var(--td-text-color-placeholder, #6b7280);
}

.scan-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
  padding: 12px 14px;
  border: 1px solid color-mix(in srgb, var(--td-error-color, #d54941) 26%, transparent);
  border-radius: var(--td-radius-default);
  background: color-mix(in srgb, var(--td-error-color-1, #fff0ed) 86%, transparent);
}

.scan-error-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.scan-error-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--td-error-color, #d54941);
}

.scan-error-message {
  font-size: 12px;
  line-height: 1.6;
  color: var(--td-text-color-primary, #111827);
  word-break: break-word;
}

.summary-status {
  flex-shrink: 0;
  padding: 7px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: var(--td-brand-color-1, #edf3ff);
  color: var(--td-brand-color, #366ef4);
}

.summary-status.running {
  background: var(--td-brand-color-1, #edf3ff);
  color: var(--td-brand-color, #366ef4);
}

.summary-status.success {
  background: var(--td-success-color-1, #e3f9e9);
  color: var(--td-success-color, #00a870);
}

.summary-status.danger {
  background: var(--td-error-color-1, #fff0ed);
  color: var(--td-error-color, #d54941);
}

.summary-status.idle {
  background: var(--td-bg-color-component, #f3f4f6);
  color: var(--td-text-color-secondary, #4b5563);
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.stat-card {
  overflow: hidden;
  border: 1px solid var(--td-border-level-1-color, #e5e7eb);
  border-radius: var(--td-radius-default);
  background: var(--td-bg-color-container);
  box-shadow: none;
}

.stat-card :deep(.t-card__body) {
  min-height: 170px;
  padding: 18px;
}

.stat-card.blue {
  --stat-color: var(--td-brand-color, #366ef4);
  --stat-soft: var(--td-brand-color-1, #edf3ff);
}

.stat-card.green {
  --stat-color: var(--td-success-color, #00a870);
  --stat-soft: var(--td-success-color-1, #e3f9e9);
}

.stat-card.purple {
  --stat-color: var(--td-warning-color, #ed7b2f);
  --stat-soft: var(--td-warning-color-1, #fff1e9);
}

.stat-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 18px;
}

.stat-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 52px;
  padding: 4px 10px;
  border-radius: 999px;
  background: var(--stat-soft, var(--td-bg-color-component, #f3f4f6));
  color: var(--stat-color, var(--td-text-color-secondary, #4b5563));
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
}

.stat-foot {
  font-size: 11px;
  color: var(--td-text-color-placeholder, #6b7280);
}

.stat-value {
  margin-bottom: 8px;
  font-size: 34px;
  font-weight: 700;
  line-height: 1;
  color: var(--stat-color, var(--td-text-color-primary, #111827));
}

.stat-label {
  margin-bottom: 6px;
  font-size: 15px;
  font-weight: 600;
  color: var(--td-text-color-primary, #111827);
}

.stat-sub {
  font-size: 12px;
  line-height: 1.65;
  color: var(--td-text-color-secondary, #4b5563);
}

@media (max-width: 768px) {
  .scanner-tab {
    padding-top: 0;
  }

  .panel-card :deep(.t-card__body) {
    padding: 16px;
  }

  .scan-actions {
    display: flex !important;
    flex-wrap: wrap;
  }

  .summary-head {
    flex-direction: column;
    align-items: stretch;
  }

  .summary-status {
    align-self: flex-start;
  }

  .scan-error {
    flex-direction: column;
    align-items: stretch;
  }

  .stat-card :deep(.t-card__body) {
    min-height: 142px;
    padding: 15px;
  }

  .stat-value {
    font-size: 26px;
  }

  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
