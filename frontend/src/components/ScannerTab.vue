<template>
  <div class="scanner-tab">
    <t-card size="small" :bordered="false" class="panel-card">
      <div class="section-title">频道扫描</div>
      <p class="section-subtitle">先在“扫描配置”里设置 API Key 和扫描参数，再启动采集和过滤流程。</p>
      <t-space>
        <t-button theme="success" :disabled="scanRunning" :loading="scanStarting" @click="triggerScan">开始扫描</t-button>
        <t-button v-if="scanRunning" theme="danger" :disabled="scanStopping" @click="stopScan">
          {{ scanStopping ? '终止中...' : '停止扫描' }}
        </t-button>
        <t-button variant="outline" theme="warning" :disabled="scanClearing" @click="forceClear">
          {{ scanClearing ? '清除中...' : '强制清除状态' }}
        </t-button>
      </t-space>
      <p class="section-subtitle clear-hint">扫描卡死、点“开始”却提示“正在进行中”时，用此按钮强制清除残留状态。</p>
    </t-card>

    <t-card size="small" :bordered="false" class="panel-card">
      <div class="section-title">扫描进度</div>
      <span class="phase-text">{{ phaseText }}</span>
      <div v-if="scanRunning || progressVisible" class="progress-wrap">
        <div class="progress-head">
          <span class="progress-label">{{ progressLabel }}</span>
          <span class="progress-value">{{ progressPct }}%</span>
        </div>
        <t-progress :percentage="progressPct" />
      </div>
      <div class="toolbar-row">
        <t-button :theme="autoScroll ? 'primary' : 'default'" variant="outline" size="small" @click="autoScroll = !autoScroll">自动滚动</t-button>
        <t-button variant="outline" size="small" @click="scanLogLines = []">清空日志</t-button>
      </div>
      <div class="log-panel" ref="logPanelRef">
        <div v-for="(line, index) in scanLogLines" :key="index" class="log-line">
          <span class="log-time">[{{ line.time || '' }}]</span>
          <span :class="logClass(line.msg)">{{ line.msg || '' }}</span>
        </div>
        <div v-if="!scanLogLines.length" class="log-empty">等待扫描开始...</div>
      </div>
    </t-card>

    <div class="summary-head">
      <div>
        <div class="section-title summary-title">扫描概览</div>
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
        class="stat-card"
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
import { computed, nextTick, onMounted, ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { apiScanForceClear, apiScanLatest, apiScanStatus, apiScanStop, apiScanTrigger } from '../api.js'
import { usePolling } from '../composables/usePolling.js'

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
const logPanelRef = ref(null)
const autoScroll = ref(true)
const scanSummary = ref(createEmptySummary())

let lastLogSeq = 0
let wasRunning = false
let triggerPending = false

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

function logClass(msg) {
  if (/发现|频道|成功|完成|存活/.test(msg || '')) return 'log-msg-pass'
  if (/失败|错误|超时|异常|终止/.test(msg || '')) return 'log-msg-fail'
  return 'log-msg-info'
}

function appendLogs(lines) {
  if (!Array.isArray(lines) || !lines.length) return
  lines.forEach((line) => {
    const seq = Number(line.seq)
    if (Number.isFinite(seq) && seq <= lastLogSeq) return
    scanLogLines.value.push(line)
    if (Number.isFinite(seq)) lastLogSeq = seq
  })
  if (autoScroll.value) {
    nextTick(() => {
      const el = logPanelRef.value
      if (el) el.scrollTop = el.scrollHeight
    })
  }
}

function applyStatus(data = {}) {
  const running = Boolean(data.running)
  // 刚点“开始扫描”后，后端可能还没把 running 翻成 true。
  // triggerPending 期间（10s 内）忽略 running=false，避免把刚启动的扫描误判为已完成。
  if (!running && triggerPending) return

  scanRunning.value = running
  currentPhase.value = data.phase || 'idle'
  phaseText.value = buildPhaseText(data.phase, data.message)

  const total = Number(data.total) || 0
  const processed = Number(data.processed) || 0
  const backendPercent = Number(data.percent)
  progressPct.value = Number.isFinite(backendPercent)
    ? Math.max(0, Math.min(100, Math.round(backendPercent)))
    : (total > 0 ? Math.min(100, Math.round(processed / total * 100)) : 0)
  progressLabel.value = total > 0
    ? `进度 ${Math.min(total, processed)} / ${total}`
    : (data.message || (running ? '准备中...' : '暂无进行中的扫描任务'))
  progressVisible.value = running || progressPct.value > 0 || scanLogLines.value.length > 0

  scanSummary.value = normalizeSummary(data.summary)
  appendLogs(data.lines)

  if (running) {
    triggerPending = false
    wasRunning = true
    return
  }

  if (wasRunning) {
    wasRunning = false
    if (data.error) MessagePlugin.error(`扫描异常: ${data.error}`)
    else MessagePlugin.success(currentPhase.value === 'health_check' ? '健康检查已完成' : '扫描已完成')
    stopPoll()
    return
  }

  stopPoll()
}

async function refreshStatus() {
  try {
    const data = await apiScanStatus()
    if (!data?.summary?.scan_id) {
      try {
        data.summary = await apiScanLatest()
      } catch (_) {}
    }
    applyStatus(data)
  } catch (_) {}
}

const hasSummary = computed(() => Boolean(scanSummary.value.scanId))

const summaryCaption = computed(() => {
  if (!hasSummary.value) return '还没有扫描记录，启动一次扫描后这里会显示最近一次摘要。'
  const time = scanSummary.value.finishedAt || scanSummary.value.startedAt
  return time ? `最近一次扫描时间：${time}` : '最近一次扫描摘要'
})

const summaryStatusText = computed(() => {
  if (scanRunning.value) return phaseName(currentPhase.value)
  if (!hasSummary.value) return '等待扫描'
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
    foot: hasSummary.value ? `去重候选 ${scanSummary.value.totalDeduped} 条` : '等待扫描生成数据',
  },
  {
    key: 'fast',
    badge: 'FAST',
    tone: 'green',
    value: scanSummary.value.totalFastPass,
    label: '快速过滤',
    sub: '通过去重和基础连通性校验的频道数量',
    foot: hasSummary.value ? '适合进入深度检测阶段' : '运行扫描后自动更新',
  },
  {
    key: 'deep',
    badge: 'DEEP',
    tone: 'purple',
    value: scanSummary.value.totalDeepPass,
    label: '深度可用',
    sub: '通过深度可用性检测并写入结果页的数量',
    foot: hasSummary.value ? '可直接用于后续测速或导出' : '深度检测完成后显示',
  },
])

function formatMetric(value) {
  if (!hasSummary.value) return '--'
  return String(value ?? 0)
}

const { start: startPoll, stop: stopPoll } = usePolling(refreshStatus, 2000)

async function triggerScan() {
  scanStarting.value = true
  triggerPending = true
  try {
    const res = await apiScanTrigger()
    if (res.ok) {
      MessagePlugin.success('扫描已启动')
      scanLogLines.value = []
      lastLogSeq = 0
      wasRunning = true
      progressVisible.value = true
      phaseText.value = '扫描启动中...'
      progressLabel.value = '正在连接扫描任务...'
      startPoll()
      setTimeout(() => { triggerPending = false }, 10000)
    } else {
      MessagePlugin.error(res.error || '启动失败')
      triggerPending = false
    }
  } catch (_) {
    MessagePlugin.error('启动失败')
    triggerPending = false
  } finally {
    scanStarting.value = false
  }
}

async function stopScan() {
  scanStopping.value = true
  try {
    const res = await apiScanStop()
    if (res.ok) {
      MessagePlugin.success(res.message || '已请求终止')
      await refreshStatus()
    } else {
      MessagePlugin.error(res.error || '终止失败')
    }
  } catch (_) {
    MessagePlugin.error('终止失败')
  } finally {
    scanStopping.value = false
  }
}

async function forceClear() {
  scanClearing.value = true
  try {
    const res = await apiScanForceClear()
    if (res.ok) {
      MessagePlugin.success(res.message || '扫描状态已清除')
      // 清除残留状态：复位本地标志并停止轮询，避免守卫继续吞掉状态
      triggerPending = false
      wasRunning = false
      stopPoll()
      await refreshStatus()
    } else {
      MessagePlugin.error(res.error || '清除失败')
    }
  } catch (_) {
    MessagePlugin.error('清除失败')
  } finally {
    scanClearing.value = false
  }
}

onMounted(async () => {
  await refreshStatus()
  if (scanRunning.value) {
    progressVisible.value = true
    startPoll()
  }
})
</script>

<style scoped>
.scanner-tab {
  padding-top: 4px;
}

.panel-card {
  margin-bottom: 12px;
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

.toolbar-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 8px;
  margin-bottom: 8px;
}

.log-panel {
  height: 400px;
  overflow-y: auto;
  padding: 12px;
  border-radius: 12px;
  background:
    radial-gradient(circle at top right, rgba(124, 58, 237, 0.18), transparent 34%),
    linear-gradient(160deg, #161822 0%, #1e2230 100%);
  color: #cdd6f4;
  font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
  font-size: 12px;
  line-height: 1.7;
  scroll-behavior: smooth;
}

.log-line {
  white-space: pre-wrap;
  word-break: break-all;
}

.log-empty {
  color: #94a3b8;
}

.log-time {
  margin-right: 8px;
  color: #93c5fd;
}

.log-msg-pass {
  color: #86efac;
}

.log-msg-fail {
  color: #fda4af;
}

.log-msg-info {
  color: #d8b4fe;
}

.summary-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.summary-title {
  margin-bottom: 4px;
}

.summary-caption {
  font-size: 12px;
  line-height: 1.6;
  color: var(--td-text-color-placeholder, #6b7280);
}

.summary-status {
  flex-shrink: 0;
  padding: 7px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: #eef2ff;
  color: #4f46e5;
}

.summary-status.running {
  background: #dbeafe;
  color: #2563eb;
}

.summary-status.success {
  background: #dcfce7;
  color: #166534;
}

.summary-status.danger {
  background: #fee2e2;
  color: #b91c1c;
}

.summary-status.idle {
  background: #f3f4f6;
  color: #4b5563;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
}

.stat-card {
  overflow: hidden;
  border-radius: 18px;
  box-shadow: var(--td-shadow-1);
}

.stat-card :deep(.t-card__body) {
  min-height: 170px;
  padding: 18px;
}

.stat-card.blue {
  background:
    radial-gradient(circle at top right, rgba(59, 130, 246, 0.18), transparent 34%),
    linear-gradient(180deg, rgba(239, 246, 255, 0.9), rgba(255, 255, 255, 1));
}

.stat-card.green {
  background:
    radial-gradient(circle at top right, rgba(34, 197, 94, 0.18), transparent 34%),
    linear-gradient(180deg, rgba(240, 253, 244, 0.92), rgba(255, 255, 255, 1));
}

.stat-card.purple {
  background:
    radial-gradient(circle at top right, rgba(124, 58, 237, 0.18), transparent 34%),
    linear-gradient(180deg, rgba(245, 243, 255, 0.94), rgba(255, 255, 255, 1));
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
  background: rgba(15, 23, 42, 0.08);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
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
  color: #0f172a;
}

.stat-label {
  margin-bottom: 6px;
  font-size: 15px;
  font-weight: 600;
  color: #111827;
}

.stat-sub {
  font-size: 12px;
  line-height: 1.65;
  color: #4b5563;
}

@media (max-width: 768px) {
  .summary-head {
    flex-direction: column;
    align-items: stretch;
  }

  .summary-status {
    align-self: flex-start;
  }

  .stat-card :deep(.t-card__body) {
    min-height: 154px;
  }

  .stat-value {
    font-size: 30px;
  }
}
</style>
