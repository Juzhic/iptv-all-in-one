<template>
  <t-config-provider :global-config="globalConfig">
    <div class="app-container">
      <header class="app-header">
        <div class="header-left">
          <h1 class="app-title">iptv-all-in-one 管理后台</h1>
        </div>

        <nav class="header-right" aria-label="工具栏">
          <div class="header-live" v-if="testRunning" aria-live="polite">
            <t-tag theme="warning" variant="light" shape="round">
              <template #icon><t-loading size="12px" /></template>
              测试运行中 {{ progressText }}
            </t-tag>
          </div>

          <div class="mode-chip">
            <span class="mode-chip-dot" :class="{ 'is-dark': isDark }"></span>
            <span class="mode-chip-label">{{ isDark ? '深色模式' : '浅色模式' }}</span>
            <t-switch v-model="isDark" size="small" aria-label="切换深色/浅色模式" />
          </div>

          <div class="header-facts" v-if="headerFacts.length">
            <span v-for="item in headerFacts" :key="item.label" class="header-fact">
              <span class="header-fact-dot"></span>
              <span class="header-fact-label">{{ item.label }}：</span>
              <span class="header-fact-value">{{ item.value }}</span>
            </span>
          </div>
        </nav>
      </header>

      <section v-if="latestRun" class="summary-cards" aria-label="概览统计">
        <t-row :gutter="[16, 16]" align="stretch">
          <t-col
            v-for="card in topSummaryCards"
            :key="card.label"
            :xs="12"
            :sm="6"
            :md="3"
            :lg="3"
          >
            <t-card size="small" :bordered="false" class="summary-card top-summary-card">
              <div class="card-label">{{ card.label }}</div>
              <div class="card-value" :class="card.klass">{{ card.value }}</div>
              <div class="card-sub">{{ card.sub }}</div>
              <t-progress
                v-if="card.progress !== null"
                :percentage="card.progress"
                :status="card.progressStatus"
                size="small"
                :aria-label="`${card.label} ${card.value}`"
              />
            </t-card>
          </t-col>
        </t-row>
      </section>

      <main class="main-content" aria-label="主要功能区域">
        <t-tabs v-model="activeTab" @change="onTabChange" class="main-tabs" role="tablist" aria-label="功能导航">
          <t-tab-panel value="overview" label="总览" :destroy-on-hide="false">
            <OverviewTab
              v-if="visitedTabs.has('overview')"
              ref="overviewRef"
              :latest="latestRun"
              :runs="runs"
              :channel-summary="channelSummary"
              :codec-stats="codecStats"
            />
          </t-tab-panel>
          <t-tab-panel value="history" label="历史明细" :destroy-on-hide="false">
            <HistoryTab v-if="visitedTabs.has('history')" ref="historyRef" @update-overview="refreshOverview" />
          </t-tab-panel>
          <t-tab-panel value="testing" label="系统测试" :destroy-on-hide="false">
            <TestingTab v-if="visitedTabs.has('testing')" @test-finished="onTestFinished" />
          </t-tab-panel>
          <t-tab-panel value="settings" label="系统配置" :destroy-on-hide="false">
            <SettingsTab v-if="visitedTabs.has('settings')" />
          </t-tab-panel>
          <t-tab-panel value="scanner" label="频道扫描" :destroy-on-hide="false">
            <ScannerTab v-if="visitedTabs.has('scanner')" />
          </t-tab-panel>
          <t-tab-panel value="scan-config" label="扫描配置" :destroy-on-hide="false">
            <ScanConfigTab v-if="visitedTabs.has('scan-config')" />
          </t-tab-panel>
          <t-tab-panel value="detection" label="检测监控" :destroy-on-hide="false">
            <DetectionTab v-if="visitedTabs.has('detection')" />
          </t-tab-panel>
          <t-tab-panel value="scan-results" label="扫描结果" :destroy-on-hide="false">
            <ScanResultsTab v-if="visitedTabs.has('scan-results')" />
          </t-tab-panel>
          <t-tab-panel value="ip-scan" label="IP扫描" :destroy-on-hide="false">
            <IpScanTab v-if="visitedTabs.has('ip-scan')" />
          </t-tab-panel>
        </t-tabs>
      </main>
    </div>
  </t-config-provider>
</template>

<script setup>
import { ref, computed, onMounted, provide, nextTick, reactive, onBeforeUnmount } from 'vue'
import { useMagicKeys, whenever } from '@vueuse/core'
import { useTheme } from './composables/useTheme.js'
import { useDialogDrag } from './composables/useDialogDrag.js'
import { apiGetInitial, apiGetProgress, connectTestSse } from './api.js'
import OverviewTab from './components/OverviewTab.vue'
import HistoryTab from './components/HistoryTab.vue'
import TestingTab from './components/TestingTab.vue'
import SettingsTab from './components/SettingsTab.vue'
import ScannerTab from './components/ScannerTab.vue'
import ScanConfigTab from './components/ScanConfigTab.vue'
import DetectionTab from './components/DetectionTab.vue'
import ScanResultsTab from './components/ScanResultsTab.vue'
import IpScanTab from './components/IpScanTab.vue'

const globalConfig = {}
const { theme, setTheme } = useTheme()
useDialogDrag()

const isDark = computed({
  get: () => theme.value === 'dark',
  set: (value) => { setTheme(value ? 'dark' : 'light') },
})

const activeTab = ref('overview')
// 懒加载标签页：只有访问过的标签才挂载其组件，避免一进后台就并发
// 触发所有标签的 onMounted 数据请求（网络差时会堵死浏览器并发连接）。
// 已访问的标签保持挂载（destroy-on-hide=false），切回时不重新请求。
const visitedTabs = reactive(new Set(['overview']))
const latestRun = ref(null)
const latestScan = ref(null)
const runs = ref([])
const channelSummary = ref({})
const codecStats = ref({})
const overviewRef = ref(null)
const historyRef = ref(null)

// Keyboard shortcuts
const { ctrl_s, ctrl_f, escape } = useMagicKeys()

const TAB_LIST = ['overview', 'history', 'testing', 'settings', 'scanner', 'scan-config', 'detection', 'scan-results', 'ip-scan']

// Ctrl+S 保存配置
whenever(ctrl_s, () => {
  if (activeTab.value === 'settings') {
    const settingsEl = document.querySelector('.settings-tab')
    if (settingsEl) {
      const saveBtn = settingsEl.querySelector('.t-button--theme-primary')
      if (saveBtn) saveBtn.click()
    }
  } else if (activeTab.value === 'scan-config') {
    const scanConfigEl = document.querySelector('.scan-config-tab')
    if (scanConfigEl) {
      const saveBtn = scanConfigEl.querySelector('.scan-config-save-button')
      if (saveBtn) saveBtn.click()
    }
  }
})

// Ctrl+F 聚焦搜索
whenever(ctrl_f, (e) => {
  e.preventDefault()
  const searchInput = document.querySelector('.search-input input, .t-input input[placeholder*="搜索"]')
  if (searchInput) searchInput.focus()
})

// 数字键切换Tab
function handleKeyDown(e) {
  if (e.altKey && e.key >= '1' && e.key <= '9') {
    e.preventDefault()
    const tabIndex = parseInt(e.key) - 1
    if (tabIndex < TAB_LIST.length) {
      activeTab.value = TAB_LIST[tabIndex]
      visitedTabs.add(TAB_LIST[tabIndex])
    }
  }
}

const latestSummary = computed(() => latestRun.value?.summary || {})
const topSummaryCards = computed(() => {
  if (!latestRun.value) return []

  const summary = latestSummary.value
  const totalTested = Number(summary.total_tested || 0)
  const totalPassed = Number(summary.total_passed || 0)
  const passRate = Number(summary.pass_rate || 0)
  const channelsPassed = Number(summary.unique_channels_passed || 0)
  const channelsTotal = Number(summary.unique_channels_total || 0)
  const channelCoverage = channelsTotal > 0
    ? Math.round((channelsPassed / channelsTotal) * 1000) / 10
    : 0
  const durationMinutes = latestRun.value.duration_seconds
    ? Math.max(1, Math.round(latestRun.value.duration_seconds / 60))
    : 0

  const scan = latestScan.value
  const scannedTotal = scan ? Number(scan.total_deduped || scan.total_raw || 0) : 0
  const scannedRaw = scan ? Number(scan.total_raw || 0) : 0

  return [
    {
      label: '通过率',
      value: `${passRate}%`,
      sub: `${totalPassed} / ${totalTested} 个地址通过`,
      klass: passRate >= 50 ? 'green' : 'red',
      progress: passRate,
      progressStatus: passRate >= 50 ? 'success' : 'warning',
    },
    {
      label: '覆盖频道',
      value: `${channelCoverage}%`,
      sub: `${channelsPassed} / ${channelsTotal} 个频道`,
      klass: 'blue',
      progress: channelCoverage,
      progressStatus: channelCoverage >= 50 ? 'success' : 'warning',
    },
    {
      label: '扫描结果',
      value: scannedTotal.toLocaleString(),
      sub: scan
        ? `原始 ${scannedRaw.toLocaleString()} 个地址`
        : '暂无扫描数据',
      klass: 'cyan',
      progress: null,
      progressStatus: 'success',
    },
    {
      label: '执行时长',
      value: `${durationMinutes} 分钟`,
      sub: `${latestRun.value.started_at || '暂无'} 开始`,
      klass: 'purple',
      progress: null,
      progressStatus: 'success',
    },
  ]
})

const headerFacts = computed(() => {
  const facts = []
  if (schedulerRunning.value && nextScheduledRun.value) {
    facts.push({ label: '下次执行', value: nextScheduledRun.value })
  }
  if (latestRun.value?.finished_at) {
    facts.push({ label: '最近更新', value: latestRun.value.finished_at })
  }
  if (latestRun.value?.duration_seconds) {
    facts.push({ label: '耗时', value: `${Math.round(latestRun.value.duration_seconds / 60)} 分钟` })
  }
  return facts
})

const testRunning = ref(false)
const schedulerRunning = ref(false)
const nextScheduledRun = ref('')
const progressText = ref('')

const testProgress = reactive({
  running: false,
  processed: 0,
  passed: 0,
  failed: 0,
  elapsed: 0,
  total: 0,
  lines: [],
})

async function loadInitialData() {
  try {
    const data = await apiGetInitial()
    latestRun.value = data.latest
    latestScan.value = data.latest_scan || null
    runs.value = data.runs || []
    channelSummary.value = data.channel_summary || {}
    codecStats.value = data.codec_stats || {}
    if (!data.latest) {
      activeTab.value = 'testing'
      visitedTabs.add('testing')
    }
  } catch (error) {
    console.error('加载初始数据失败:', error)
  }
}

let lastLogSeq = 0
let testEventSource = null
let pollFallbackTimer = null

function handleSseStatus(e) {
  try {
    const data = JSON.parse(e.data)
    applyTestState(data)
  } catch (_) {}
}

function handleSseProgress(e) {
  try {
    const data = JSON.parse(e.data)
    testRunning.value = true
    testProgress.running = true
    testProgress.processed = Number(data.processed) || 0
    testProgress.passed = data.passed || 0
    testProgress.failed = data.failed || 0
    testProgress.elapsed = Math.round(data.elapsed || 0)
    testProgress.total = Number(data.total) || 0
    const pct = testProgress.total > 0 ? Math.round((testProgress.processed / testProgress.total) * 100) : 0
    progressText.value = `${testProgress.processed}/${testProgress.total || '?'} ${pct}%`
  } catch (_) {}
}

function handleSseLog(e) {
  try {
    const line = JSON.parse(e.data)
    if (line.seq > lastLogSeq) {
      testProgress.lines.push(line)
      if (testProgress.lines.length > 5000) {
        testProgress.lines.splice(0, testProgress.lines.length - 5000)
      }
      lastLogSeq = line.seq
    }
  } catch (_) {}
}

function handleSseTestComplete(e) {
  try {
    const data = JSON.parse(e.data)
    testRunning.value = false
    testProgress.running = false
    if (data.elapsed) testProgress.elapsed = Math.round(data.elapsed)
    if (data.total) testProgress.total = Number(data.total)
    if (data.processed) testProgress.processed = Number(data.processed)
    if (data.passed != null) testProgress.passed = data.passed
    if (data.failed != null) testProgress.failed = data.failed
  } catch (_) {
    testRunning.value = false
    testProgress.running = false
  }
  disconnectTestSse()
  loadInitialData()
}

function handleSseError() {
  disconnectTestSse()
  if (testRunning.value || schedulerRunning.value) {
    startPollFallback()
  }
}

function applyTestState(data) {
  if (!data) return
  testRunning.value = !!data.running
  testProgress.running = !!data.running
  testProgress.processed = Number(data.processed) || 0
  testProgress.passed = data.passed || 0
  testProgress.failed = data.failed || 0
  testProgress.elapsed = Math.round(data.elapsed || 0)
  testProgress.total = Number(data.total) || 0
  schedulerRunning.value = !!data.scheduler_running
  nextScheduledRun.value = data.next_scheduled_run || ''
  if (data.running) {
    const pct = testProgress.total > 0 ? Math.round((testProgress.processed / testProgress.total) * 100) : 0
    progressText.value = `${testProgress.processed}/${testProgress.total || '?'} ${pct}%`
  }
}

function connectTestStream() {
  disconnectTestSse()
  try {
    testEventSource = connectTestSse({
      status: handleSseStatus,
      progress: handleSseProgress,
      log: handleSseLog,
      test_complete: handleSseTestComplete,
      onerror: handleSseError,
    })
  } catch (_) {
    startPollFallback()
  }
}

function disconnectTestSse() {
  if (testEventSource) {
    testEventSource.close()
    testEventSource = null
  }
  stopPollFallback()
}

function startPollFallback() {
  stopPollFallback()
  pollFallbackTimer = setInterval(async () => {
    try {
      const data = await apiGetProgress(lastLogSeq)
      applyTestState(data)
      if (data.lines?.length) {
        data.lines.forEach((line) => {
          if (line.seq > lastLogSeq) {
            testProgress.lines.push(line)
            if (testProgress.lines.length > 5000) {
              testProgress.lines.splice(0, testProgress.lines.length - 5000)
            }
            lastLogSeq = line.seq
          }
        })
      }
      if (!data.running && !schedulerRunning.value) {
        stopPollFallback()
      }
    } catch (_) {}
  }, 2000)
}

function stopPollFallback() {
  if (pollFallbackTimer) {
    clearInterval(pollFallbackTimer)
    pollFallbackTimer = null
  }
}

provide('testProgress', testProgress)
provide('clearTestLogs', () => {
  testProgress.lines = []
  lastLogSeq = 0
})

function onTestFinished() {
  loadInitialData()
  activeTab.value = 'overview'
  nextTick(() => overviewRef.value?.refreshCharts?.())
}

function refreshOverview(runsData) {
  runs.value = runsData
  if (runsData.length) {
    latestRun.value = runsData[0]
  }
  nextTick(() => overviewRef.value?.refreshCharts?.())
}

function onTabChange(value) {
  visitedTabs.add(value)
  if (value === 'overview') {
    nextTick(() => overviewRef.value?.refreshCharts?.())
  }
}

onMounted(async () => {
  await loadInitialData()
  connectTestStream()
  window.addEventListener('keydown', handleKeyDown)
})

onBeforeUnmount(() => {
  disconnectTestSse()
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<style>
*, *::before, *::after { box-sizing: border-box; }
body {
  margin: 0;
  font-family: "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
  background: var(--td-bg-color-page, #f5f7fb);
}

/* ─── 全局弹窗样式：居中 + 拖拽手柄 + 内部滚动 ─── */
.t-dialog__ctx .t-dialog__position {
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  top: 0 !important;
  left: 0 !important;
  width: 100% !important;
  height: 100% !important;
  padding: 0 !important;
  margin: 0 !important;
}
.t-dialog {
  max-height: 85vh !important;
  max-width: 90vw !important;
  display: flex !important;
  flex-direction: column !important;
  margin: 0 !important;
  position: static !important;
  top: auto !important;
  left: auto !important;
}
.t-dialog__header {
  cursor: move;
  user-select: none;
  flex-shrink: 0;
}
.t-dialog__body {
  flex: 1 !important;
  min-height: 0 !important;
  overflow-y: auto !important;
}
.t-dialog__body .t-table__content {
  max-height: calc(85vh - 200px) !important;
  overflow-y: auto !important;
}
</style>

<style scoped>
.app-container {
  max-width: 1680px;
  margin: 0 auto;
  min-height: 100vh;
  padding: 18px;
  background: var(--td-bg-color-page, #f5f7fb);
}

.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px 20px;
  padding: 10px 0 14px;
  margin-bottom: 18px;
  border-bottom: 1px solid var(--td-component-stroke, #e5e7eb);
  flex-wrap: wrap;
}

.app-title {
  margin: 0;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--td-text-color-primary, #111827);
}

.header-right {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 12px;
}

.header-live {
  display: flex;
  align-items: center;
}

.mode-chip {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  padding: 6px 12px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--td-brand-color-1, #edf3ff) 68%, transparent);
  border: 1px solid color-mix(in srgb, var(--td-brand-color, #366ef4) 22%, transparent);
}

.mode-chip-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #2563eb;
  box-shadow: 0 0 0 4px color-mix(in srgb, #2563eb 14%, transparent);
}

.mode-chip-dot.is-dark {
  background: #7c3aed;
  box-shadow: 0 0 0 4px color-mix(in srgb, #7c3aed 14%, transparent);
}

.mode-chip-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--td-text-color-primary);
}

.header-facts {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px 14px;
}

.header-fact {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--td-text-color-secondary);
}

.header-fact-dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: var(--td-brand-color, #366ef4);
  opacity: 0.9;
}

.header-fact-label {
  color: var(--td-text-color-placeholder);
}

.header-fact-value {
  font-weight: 600;
  color: var(--td-text-color-primary);
}

.summary-cards {
  margin-bottom: 18px;
}

.main-content {
  outline: none;
}

.summary-cards :deep(.t-col) {
  display: flex;
}

.summary-card {
  width: 100%;
  border-radius: 16px;
  box-shadow: var(--td-shadow-1);
}

.top-summary-card {
  height: 100%;
}

.top-summary-card :deep(.t-card__body) {
  display: flex;
  flex-direction: column;
  min-height: 140px;
  padding: 18px 20px 16px;
}

.card-label {
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--td-text-color-placeholder, #6b7280);
}

.card-value {
  font-size: 26px;
  font-weight: 700;
  line-height: 1.25;
  color: var(--td-text-color-primary, #111827);
}

.card-value.green { color: #16a34a; }
.card-value.red { color: #dc2626; }
.card-value.blue { color: #2563eb; }
.card-value.cyan { color: #0891b2; }
.card-value.purple { color: #7c3aed; }

.card-sub {
  margin-top: 6px;
  font-size: 12px;
  line-height: 1.5;
  color: var(--td-text-color-placeholder, #9ca3af);
}

.main-tabs {
  background: var(--td-bg-color-container, #ffffff);
  border-radius: 20px;
  padding: 0 18px 18px;
  box-shadow: var(--td-shadow-1);
}

:deep(.t-tabs__header) {
  padding-top: 10px;
}

:deep(.t-tabs__nav-item) {
  font-weight: 500;
}

:deep(.t-tabs__content) {
  padding-top: 18px;
}

@media (max-width: 768px) {
  .app-container {
    padding: 12px;
  }

  .app-title {
    font-size: 18px;
  }

  .header-right {
    width: 100%;
    justify-content: flex-start;
  }

  .main-tabs {
    padding: 0 12px 12px;
  }

  .top-summary-card :deep(.t-card__body) {
    min-height: 128px;
  }

  .card-value {
    font-size: 22px;
  }
}
</style>
