<template>
  <t-config-provider :global-config="globalConfig">
    <div class="app-shell" :class="{ 'sidebar-is-compact': sidebarCollapsed }">
      <aside class="app-sidebar" aria-label="主导航">
        <div class="brand-block">
          <div class="brand-mark" aria-hidden="true">IP</div>
          <div v-if="!sidebarCollapsed" class="brand-copy">
            <div class="brand-title">IPTV 质量台</div>
            <div class="brand-subtitle">quality console</div>
          </div>
          <button
            type="button"
            class="sidebar-collapse"
            :aria-label="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
            :aria-expanded="!sidebarCollapsed"
            @click="sidebarCollapsed = !sidebarCollapsed"
          >
            {{ sidebarCollapsed ? '›' : '‹' }}
          </button>
        </div>

        <nav class="sidebar-nav">
          <section v-for="group in navGroups" :key="group.value" class="nav-group">
            <button
              type="button"
              class="nav-group-toggle"
              :aria-expanded="!collapsedGroups.has(group.value)"
              :aria-label="`${collapsedGroups.has(group.value) ? '展开' : '收起'}${group.label}`"
              @click="toggleGroup(group.value)"
            >
              <span class="nav-group-symbol" aria-hidden="true">{{ group.label.slice(0, 1) }}</span>
              <span v-if="!sidebarCollapsed" class="nav-group-label">{{ group.label }}</span>
              <span v-if="!sidebarCollapsed" class="nav-group-chevron" aria-hidden="true">
                {{ collapsedGroups.has(group.value) ? '›' : '⌄' }}
              </span>
            </button>
            <div v-show="sidebarCollapsed || !collapsedGroups.has(group.value)" class="nav-group-items">
              <button
                v-for="item in group.items"
                :key="item.value"
                type="button"
                class="nav-item"
                :class="{ 'is-active': activeTab === item.value }"
                :aria-current="activeTab === item.value ? 'page' : undefined"
                :title="sidebarCollapsed ? item.label : undefined"
                @click="switchTab(item.value)"
              >
                <span class="nav-item-mark" aria-hidden="true">{{ item.short }}</span>
                <span v-if="!sidebarCollapsed" class="nav-item-label">{{ item.label }}</span>
                <span v-if="!sidebarCollapsed" class="nav-item-arrow" aria-hidden="true">›</span>
              </button>
            </div>
          </section>
        </nav>

        <div class="sidebar-foot">
          <span class="sidebar-foot-dot" :class="{ 'has-error': taskLoadError }"></span>
          <span v-if="!sidebarCollapsed">{{ taskSummaryText }}</span>
        </div>
      </aside>

      <section class="app-workspace">
        <div class="mobile-topbar">
          <button
            type="button"
            class="mobile-menu-button"
            aria-label="打开功能导航"
            :aria-expanded="mobileDrawerVisible"
            @click="mobileDrawerVisible = true"
          >
            <span aria-hidden="true">☰</span>
          </button>
          <div class="mobile-title-block">
            <span class="mobile-eyebrow">{{ activeGroupLabel }}</span>
            <strong>{{ activePage.label }}</strong>
          </div>
          <t-switch v-model="isDark" size="small" aria-label="切换深色或浅色模式" />
        </div>

        <header class="workspace-header">
          <div class="workspace-heading">
            <div class="workspace-eyebrow">{{ activeGroupLabel }}</div>
            <h1>{{ activePage.label }}</h1>
            <p>{{ activePage.description }}</p>
          </div>

          <div class="workspace-actions" aria-label="页面工具栏">
            <t-tag v-if="testRunning" theme="warning" variant="light" shape="round" aria-live="polite">
              <template #icon><t-loading size="12px" /></template>
              测试运行中 {{ progressText }}
            </t-tag>
            <div class="mode-chip">
              <span class="mode-chip-dot" :class="{ 'is-dark': isDark }"></span>
              <span>{{ isDark ? '深色' : '浅色' }}</span>
              <t-switch v-model="isDark" size="small" aria-label="切换深色或浅色模式" />
            </div>
          </div>
        </header>

        <div class="workspace-facts" aria-label="运行摘要">
          <span v-for="item in headerFacts" :key="item.label" class="header-fact">
            <span class="header-fact-dot" :class="item.tone" aria-hidden="true"></span>
            <span class="header-fact-label">{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </span>
        </div>

        <main ref="pageRootRef" class="workspace-main" aria-label="主要功能区域">
          <template v-if="activeTab === 'overview'">
            <section v-if="topSummaryCards.length" class="summary-grid" aria-label="核心质量指标">
              <article v-for="card in topSummaryCards" :key="card.label" class="summary-card">
                <div class="summary-card-head">
                  <span>{{ card.label }}</span>
                  <span class="summary-card-status" :class="card.tone">{{ card.status }}</span>
                </div>
                <div class="summary-card-value" :class="card.tone">{{ card.value }}</div>
                <div class="summary-card-sub">{{ card.sub }}</div>
                <div v-if="card.progress != null" class="summary-meter" aria-hidden="true">
                  <span :style="{ width: `${card.progress}%` }" :class="card.tone"></span>
                </div>
              </article>
            </section>

            <AsyncState
              :loading="dashboardState.loading"
              :error="dashboardState.error"
              :empty="dashboardIsEmpty"
              empty-title="还没有质量数据"
              empty-description="可前往“系统测试”或“频道扫描”启动第一轮任务。"
              :retry="() => loadDashboard()"
            >
              <OverviewTab
                ref="activePageRef"
                :dashboard="dashboard"
                :latest="latestRun"
                :runs="runs"
                :channel-summary="channelSummary"
                :codec-stats="codecStats"
              />
            </AsyncState>
          </template>

          <KeepAlive v-else>
            <component
              :is="activeComponent"
              :key="activeTab"
              ref="activePageRef"
              v-bind="activeComponentProps"
              @test-finished="onTestFinished"
            />
          </KeepAlive>
        </main>
      </section>

      <t-drawer
        v-model:visible="mobileDrawerVisible"
        placement="left"
        size="min(88vw, 340px)"
        header="功能导航"
        :footer="false"
        class="mobile-drawer"
      >
        <nav class="drawer-nav" aria-label="移动端功能导航">
          <section v-for="group in navGroups" :key="group.value" class="drawer-group">
            <div class="drawer-group-label">{{ group.label }}</div>
            <button
              v-for="item in group.items"
              :key="item.value"
              type="button"
              class="drawer-item"
              :class="{ 'is-active': activeTab === item.value }"
              :aria-current="activeTab === item.value ? 'page' : undefined"
              @click="switchTab(item.value)"
            >
              <span class="nav-item-mark" aria-hidden="true">{{ item.short }}</span>
              <span>
                <strong>{{ item.label }}</strong>
                <small>{{ item.description }}</small>
              </span>
            </button>
          </section>
        </nav>
      </t-drawer>
    </div>
  </t-config-provider>
</template>

<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  provide,
  reactive,
  ref,
} from 'vue'
import AsyncState from './components/AsyncState.vue'
import { useTheme } from './composables/useTheme.js'
import { useDialogDrag } from './composables/useDialogDrag.js'
import { useHashRoute } from './composables/useHashRoute.js'
import { useAdaptivePolling, taskIsRunning } from './composables/useAdaptivePolling.js'
import {
  apiGetDashboard,
  apiGetInitial,
  apiGetProgress,
  apiGetTasks,
} from './api.js'
import { NAV_GROUPS, TAB_VALUES, getPageMeta } from './navigation.js'
import { normalizeTask, normalizeTasks, readTaskId, rememberTask } from './utils/tasks.js'
import { defineAsyncPage } from './utils/asyncPage.js'
import { isEditableShortcutTarget } from './utils/keyboard.js'
import {
  buildDashboardCards,
  normalizeSubscriptionRun,
  normalizeSubscriptionTrend,
} from './utils/dashboard.js'

const OverviewTab = defineAsyncPage(() => import('./components/OverviewTab.vue'))
const HistoryTab = defineAsyncPage(() => import('./components/HistoryTab.vue'))
const TestingTab = defineAsyncPage(() => import('./components/TestingTab.vue'))
const ScannerTab = defineAsyncPage(() => import('./components/ScannerTab.vue'))
const DetectionTab = defineAsyncPage(() => import('./components/DetectionTab.vue'))
const ScanResultsTab = defineAsyncPage(() => import('./components/ScanResultsTab.vue'))
const IpScanTab = defineAsyncPage(() => import('./components/IpScanTab.vue'))
const SourcesTab = defineAsyncPage(() => import('./components/SourcesTab.vue'))
const ConfigurationCenter = defineAsyncPage(() => import('./components/ConfigurationCenter.vue'))

const PAGE_COMPONENTS = {
  history: HistoryTab,
  testing: TestingTab,
  scanner: ScannerTab,
  detection: DetectionTab,
  'scan-results': ScanResultsTab,
  'ip-scan': IpScanTab,
  sources: SourcesTab,
  configuration: ConfigurationCenter,
}

const globalConfig = {}
const { theme, setTheme } = useTheme()
useDialogDrag()

const isDark = computed({
  get: () => theme.value === 'dark',
  set: value => setTheme(value ? 'dark' : 'light'),
})

const activePageRef = ref(null)
const pageRootRef = ref(null)
const mobileDrawerVisible = ref(false)
const sidebarCollapsed = ref(false)
const collapsedGroups = reactive(new Set())
const navGroups = NAV_GROUPS

async function beforeRouteChange(next, previous) {
  if (previous !== 'configuration') return true
  const canLeave = activePageRef.value?.canLeave
  return typeof canLeave === 'function' ? await canLeave() : true
}

const { current: activeTab, navigate } = useHashRoute({
  routes: TAB_VALUES,
  fallback: 'overview',
  aliases: { settings: 'configuration', 'scan-config': 'configuration' },
  beforeChange: beforeRouteChange,
})

const activePage = computed(() => getPageMeta(activeTab.value))
const activeGroupLabel = computed(() => (
  NAV_GROUPS.find(group => group.items.some(item => item.value === activeTab.value))?.label || '工作台'
))
const activeComponent = computed(() => PAGE_COMPONENTS[activeTab.value] || HistoryTab)

const taskRegistry = reactive({ test: null, scan: null, ip_scan: null, detection: null })
const activeComponentProps = computed(() => {
  if (activeTab.value === 'testing') return { active: true, task: taskRegistry.test }
  if (activeTab.value === 'scanner') return { active: true, task: taskRegistry.scan }
  if (activeTab.value === 'ip-scan') return { active: true, task: taskRegistry.ip_scan }
  if (activeTab.value === 'detection') return { active: true, task: taskRegistry.detection }
  return {}
})

function toggleGroup(value) {
  if (collapsedGroups.has(value)) collapsedGroups.delete(value)
  else collapsedGroups.add(value)
}

async function switchTab(value) {
  if (!TAB_VALUES.includes(value)) return false
  const changed = await navigate(value)
  if (changed) mobileDrawerVisible.value = false
  return changed
}

const dashboard = ref(null)
const latestRun = ref(null)
const latestScan = ref(null)
const runs = ref([])
const channelSummary = ref({})
const codecStats = ref({})
const dashboardState = reactive({ loading: true, error: '' })

function applyDashboard(data) {
  dashboard.value = data || {}
  const subscriptions = data?.subscriptions || {}
  latestRun.value = subscriptions.latest
    ? normalizeSubscriptionRun(subscriptions.latest)
    : (data?.latest || null)
  latestScan.value = data?.scan?.latest || data?.latest_scan || null
  runs.value = Array.isArray(subscriptions.trend)
    ? normalizeSubscriptionTrend(subscriptions.trend)
    : (Array.isArray(data?.runs) ? data.runs : [])
  channelSummary.value = data?.channel_summary || subscriptions.channel_summary || {}
  codecStats.value = data?.codec_stats || subscriptions.codec_stats || {}
}

async function loadDashboard({ silent = false } = {}) {
  if (!silent) dashboardState.loading = true
  dashboardState.error = ''
  try {
    let data
    try {
      data = await apiGetDashboard(10)
    } catch (dashboardError) {
      if (dashboardError?.status && dashboardError.status !== 404) throw dashboardError
      data = await apiGetInitial()
    }
    applyDashboard(data)
  } catch (error) {
    dashboardState.error = error?.message || '无法加载总览数据'
  } finally {
    dashboardState.loading = false
  }
}

const dashboardIsEmpty = computed(() => {
  if (latestRun.value || latestScan.value || runs.value.length) return false
  const pool = dashboard.value?.scan?.pool
  return !pool || Object.values(pool).every(value => !Number(value))
})

const overviewActive = computed(() => activeTab.value === 'overview')
const dashboardPoller = useAdaptivePolling(
  async () => {
    await loadDashboard({ silent: Boolean(dashboard.value) })
    return { state: 'idle' }
  },
  { active: overviewActive, runningDelay: 10000, idleDelay: 10000, immediate: true },
)

const testProgress = reactive({
  running: false,
  processed: 0,
  passed: 0,
  failed: 0,
  elapsed: 0,
  total: 0,
  lines: [],
})
let lastLogSeq = 0
const taskLoadError = ref('')

function mergeTask(type, payload) {
  const task = rememberTask(normalizeTask(payload, type), type)
  if (task) taskRegistry[type] = task
  return task
}

function applyTestProgress(data = {}) {
  const responseTask = normalizeTask(data.task, 'test')
  if (responseTask) mergeTask('test', responseTask)
  const task = responseTask || taskRegistry.test
  testProgress.running = Boolean(data.running) || taskIsRunning(task)
  testProgress.processed = Number(data.processed ?? data.progress?.processed ?? task?.progress?.processed) || 0
  testProgress.passed = Number(data.passed ?? data.progress?.passed ?? task?.progress?.passed) || 0
  testProgress.failed = Number(data.failed ?? data.progress?.failed ?? task?.progress?.failed) || 0
  testProgress.elapsed = Math.round(Number(data.elapsed ?? data.progress?.elapsed ?? task?.progress?.elapsed) || 0)
  testProgress.total = Number(data.total ?? data.progress?.total ?? task?.progress?.total) || 0

  const lines = data.lines || data.logs || []
  for (const line of lines) {
    const seq = Number(line.seq)
    if (Number.isFinite(seq) && seq <= lastLogSeq) continue
    testProgress.lines.push(line)
    if (Number.isFinite(seq)) lastLogSeq = seq
  }
  if (testProgress.lines.length > 5000) testProgress.lines.splice(0, testProgress.lines.length - 5000)
}

async function refreshTasks() {
  taskLoadError.value = ''
  try {
    const normalized = normalizeTasks(await apiGetTasks())
    for (const [type, task] of Object.entries(normalized)) {
      if (task) mergeTask(type, task)
    }
  } catch (error) {
    if (error?.status !== 404) taskLoadError.value = error?.message || '任务状态不可用'
  }

  const testTaskId = taskRegistry.test?.task_id || readTaskId('test')
  try {
    applyTestProgress(await apiGetProgress(lastLogSeq, testTaskId))
  } catch (error) {
    if (error?.name !== 'AbortError' && error?.status !== 404) taskLoadError.value ||= error?.message || '测速状态不可用'
  }

  return { running: Object.values(taskRegistry).some(taskIsRunning) || testProgress.running }
}

const taskPoller = useAdaptivePolling(refreshTasks, {
  runningDelay: 2000,
  idleDelay: 10000,
  getRunning: result => Boolean(result?.running),
  immediate: true,
})

function registerTask(type, payload) {
  const task = mergeTask(type, payload)
  taskPoller.setRunning(taskIsRunning(task))
  return task
}

provide('testProgress', testProgress)
provide('taskRegistry', taskRegistry)
provide('activeRoute', activeTab)
provide('registerTask', registerTask)
provide('clearTestLogs', () => {
  testProgress.lines.splice(0)
  lastLogSeq = 0
})

const testRunning = computed(() => testProgress.running || taskIsRunning(taskRegistry.test))
const progressText = computed(() => {
  const processed = testProgress.processed
  const total = testProgress.total
  return total > 0 ? `${processed}/${total} · ${Math.round(processed / total * 100)}%` : '准备中'
})
const runningTaskCount = computed(() => Object.values(taskRegistry).filter(taskIsRunning).length)
const taskSummaryText = computed(() => {
  if (taskLoadError.value) return '任务状态连接异常'
  return runningTaskCount.value ? `${runningTaskCount.value} 个任务运行中` : '任务服务正常'
})

const topSummaryCards = computed(() => buildDashboardCards(
  dashboard.value,
  latestRun.value,
  runningTaskCount.value,
))

const headerFacts = computed(() => {
  const facts = [
    { label: '任务', value: taskSummaryText.value, tone: taskLoadError.value ? 'danger' : (runningTaskCount.value ? 'running' : 'good') },
  ]
  const updated = latestRun.value?.finished_at || latestScan.value?.finished_at || latestScan.value?.started_at
  if (updated) facts.push({ label: '最近数据', value: updated, tone: '' })
  const nextRun = dashboard.value?.subscriptions?.next_scheduled_run
  if (nextRun) facts.push({ label: '下次测试', value: nextRun, tone: '' })
  return facts
})

async function onTestFinished() {
  await loadDashboard()
  await switchTab('overview')
  nextTick(() => activePageRef.value?.refreshCharts?.())
}

function activeSearchInput() {
  return pageRootRef.value?.querySelector(
    'input[type="search"], .search-input input, input[placeholder*="搜索"], input[placeholder*="筛选"]',
  )
}

function activeSaveAction() {
  if (activeTab.value !== 'configuration') return null
  if (typeof activePageRef.value?.save === 'function') return () => activePageRef.value.save()
  const button = pageRootRef.value?.querySelector('.settings-config-save-button, .scan-config-save-button')
  return button ? () => button.click() : null
}

function handleKeyDown(event) {
  if (isEditableShortcutTarget(event.target)) return
  const key = event.key.toLowerCase()
  const modifier = event.ctrlKey || event.metaKey
  if (modifier && key === 'f') {
    const input = activeSearchInput()
    if (!input) return
    event.preventDefault()
    input.focus()
    return
  }
  if (modifier && key === 's') {
    const save = activeSaveAction()
    if (!save) return
    event.preventDefault()
    save()
    return
  }
  if (event.altKey && event.key >= '1' && event.key <= '9') {
    const target = TAB_VALUES[Number(event.key) - 1]
    if (!target) return
    event.preventDefault()
    switchTab(target)
  }
}

onMounted(() => {
  dashboardPoller.start()
  taskPoller.start()
  window.addEventListener('keydown', handleKeyDown)
})

onBeforeUnmount(() => {
  dashboardPoller.stop()
  taskPoller.stop()
  window.removeEventListener('keydown', handleKeyDown)
})
</script>

<style>
.t-dialog__ctx .t-dialog__position {
  display: flex !important;
  align-items: center !important;
  justify-content: center !important;
  inset: 0 !important;
  width: 100% !important;
  height: 100% !important;
  padding: 0 !important;
}

.t-dialog {
  position: static !important;
  display: flex !important;
  flex-direction: column !important;
  max-width: 90vw !important;
  max-height: 85vh !important;
  margin: 0 !important;
}

.t-dialog__header {
  flex-shrink: 0;
  cursor: move;
  user-select: none;
}

.t-dialog__body {
  min-height: 0 !important;
  overflow-y: auto !important;
}
</style>

<style scoped>
.app-shell {
  display: flex;
  min-height: 100vh;
  background: var(--td-bg-color-page, #f4f7fb);
}

.app-sidebar {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  flex: 0 0 252px;
  flex-direction: column;
  width: 252px;
  height: 100vh;
  padding: 18px 14px 14px;
  border-right: 1px solid var(--app-border);
  background: var(--app-surface);
  transition: width 180ms ease, flex-basis 180ms ease;
}

.sidebar-is-compact .app-sidebar {
  flex-basis: 76px;
  width: 76px;
  padding-inline: 10px;
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 50px;
  padding: 2px 4px 16px;
  border-bottom: 1px solid var(--app-border);
}

.brand-mark {
  display: grid;
  flex: 0 0 38px;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 12px;
  background: linear-gradient(145deg, #2563eb, #4f46e5);
  box-shadow: 0 9px 20px rgb(37 99 235 / 24%);
  color: #fff;
  font-size: 13px;
  font-weight: 800;
}

.brand-copy {
  min-width: 0;
  flex: 1;
}

.brand-title {
  color: var(--app-text);
  font-size: 15px;
  font-weight: 750;
  white-space: nowrap;
}

.brand-subtitle {
  margin-top: 2px;
  color: var(--app-text-muted);
  font-size: 9px;
  letter-spacing: .13em;
  text-transform: uppercase;
}

.sidebar-collapse,
.nav-group-toggle,
.nav-item,
.drawer-item,
.mobile-menu-button {
  border: 0;
  font: inherit;
  cursor: pointer;
}

.sidebar-collapse {
  display: grid;
  flex: 0 0 26px;
  width: 26px;
  height: 26px;
  place-items: center;
  border: 1px solid var(--app-border);
  border-radius: 8px;
  background: var(--app-surface-soft);
  color: var(--app-text-muted);
}

.sidebar-is-compact .sidebar-collapse {
  position: absolute;
  top: 24px;
  right: -12px;
  background: var(--app-surface);
}

.sidebar-nav {
  min-height: 0;
  padding: 12px 0;
  overflow-y: auto;
  scrollbar-width: thin;
}

.nav-group + .nav-group {
  margin-top: 8px;
}

.nav-group-toggle {
  display: grid;
  grid-template-columns: 24px 1fr auto;
  align-items: center;
  width: 100%;
  min-height: 30px;
  padding: 3px 8px;
  background: transparent;
  color: var(--app-text-muted);
  text-align: left;
}

.sidebar-is-compact .nav-group-toggle {
  grid-template-columns: 1fr;
  justify-items: center;
  padding-inline: 0;
}

.nav-group-symbol {
  font-size: 10px;
  font-weight: 800;
  opacity: .7;
}

.nav-group-label {
  font-size: 10px;
  font-weight: 750;
  letter-spacing: .12em;
}

.nav-group-chevron {
  font-size: 13px;
}

.nav-group-items {
  margin-top: 2px;
}

.nav-item {
  display: grid;
  grid-template-columns: 28px 1fr auto;
  align-items: center;
  width: 100%;
  min-height: 40px;
  margin: 2px 0;
  padding: 6px 9px;
  border-radius: 11px;
  background: transparent;
  color: var(--app-text-muted);
  text-align: left;
  transition: background 160ms ease, color 160ms ease;
}

.sidebar-is-compact .nav-item {
  display: flex;
  justify-content: center;
  padding-inline: 0;
}

.nav-item:hover,
.nav-item:focus-visible {
  background: var(--app-surface-soft);
  color: var(--app-text);
}

.nav-item.is-active {
  background: color-mix(in srgb, var(--td-brand-color, #2563eb) 13%, transparent);
  color: var(--td-brand-color, #2563eb);
  font-weight: 650;
}

.nav-item-mark {
  display: inline-grid;
  width: 24px;
  height: 24px;
  place-items: center;
  border-radius: 8px;
  background: color-mix(in srgb, var(--app-border) 58%, transparent);
  color: inherit;
  font-size: 10px;
  font-weight: 800;
}

.nav-item.is-active .nav-item-mark,
.drawer-item.is-active .nav-item-mark {
  background: color-mix(in srgb, var(--td-brand-color, #2563eb) 18%, transparent);
}

.nav-item-label {
  min-width: 0;
}

.nav-item-arrow {
  opacity: 0;
}

.nav-item.is-active .nav-item-arrow {
  opacity: 1;
}

.sidebar-foot {
  display: flex;
  align-items: center;
  gap: 9px;
  min-height: 42px;
  margin-top: auto;
  padding: 12px 8px 2px;
  border-top: 1px solid var(--app-border);
  color: var(--app-text-muted);
  font-size: 11px;
}

.sidebar-is-compact .sidebar-foot {
  justify-content: center;
}

.sidebar-foot-dot,
.header-fact-dot {
  flex: 0 0 auto;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #22c55e;
  box-shadow: 0 0 0 4px rgb(34 197 94 / 12%);
}

.sidebar-foot-dot.has-error,
.header-fact-dot.danger {
  background: #ef4444;
  box-shadow: 0 0 0 4px rgb(239 68 68 / 12%);
}

.header-fact-dot.running {
  background: #f59e0b;
  box-shadow: 0 0 0 4px rgb(245 158 11 / 12%);
}

.app-workspace {
  min-width: 0;
  flex: 1;
  padding: 24px 30px 40px;
}

.workspace-header,
.workspace-facts,
.workspace-main {
  width: min(100%, var(--app-content-max));
  margin-inline: auto;
}

.workspace-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  min-height: 82px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--app-border);
}

.workspace-eyebrow,
.mobile-eyebrow {
  color: var(--td-brand-color, #2563eb);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: .14em;
}

.workspace-heading h1 {
  margin: 5px 0 0;
  color: var(--app-text);
  font-size: clamp(22px, 2vw, 29px);
  line-height: 1.15;
}

.workspace-heading p {
  margin: 7px 0 0;
  color: var(--app-text-muted);
  font-size: 13px;
}

.workspace-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 10px;
}

.mode-chip {
  display: inline-flex;
  align-items: center;
  gap: 9px;
  padding: 7px 10px;
  border: 1px solid color-mix(in srgb, var(--td-brand-color, #2563eb) 20%, var(--app-border));
  border-radius: 999px;
  background: color-mix(in srgb, var(--td-brand-color, #2563eb) 7%, var(--app-surface));
  color: var(--app-text-muted);
  font-size: 12px;
}

.mode-chip-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #2563eb;
}

.mode-chip-dot.is-dark {
  background: #8b5cf6;
}

.workspace-facts {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px 20px;
  min-height: 42px;
  padding-block: 9px;
}

.header-fact {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: var(--app-text-muted);
  font-size: 11px;
}

.header-fact-label {
  opacity: .76;
}

.header-fact strong {
  color: var(--app-text);
  font-weight: 650;
}

.workspace-main {
  min-width: 0;
  padding-top: 12px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.summary-card {
  min-width: 0;
  padding: 15px 16px 13px;
  border: 1px solid var(--app-border);
  border-radius: 14px;
  background: var(--app-surface);
  box-shadow: 0 8px 24px rgb(15 23 42 / 4%);
}

.summary-card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  color: var(--app-text-muted);
  font-size: 11px;
}

.summary-card-status {
  flex: 0 0 auto;
  padding: 2px 7px;
  border-radius: 999px;
  background: var(--app-surface-soft);
  font-size: 10px;
}

.summary-card-value {
  margin-top: 9px;
  overflow: hidden;
  color: var(--app-text);
  font-size: clamp(22px, 2vw, 30px);
  font-weight: 760;
  line-height: 1.12;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.summary-card-value.good,
.summary-card-status.good { color: #16a34a; }
.summary-card-value.warn,
.summary-card-status.warn { color: #d97706; }
.summary-card-value.info,
.summary-card-status.info { color: #2563eb; }
.summary-card-value.muted,
.summary-card-status.muted { color: var(--app-text-muted); }

.summary-card-sub {
  min-height: 34px;
  margin-top: 7px;
  color: var(--app-text-muted);
  font-size: 11px;
  line-height: 1.5;
}

.summary-meter {
  height: 3px;
  margin-top: 10px;
  overflow: hidden;
  border-radius: 999px;
  background: var(--app-surface-soft);
}

.summary-meter span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #2563eb;
}

.summary-meter span.good { background: #22c55e; }
.summary-meter span.warn { background: #f59e0b; }

.mobile-topbar {
  display: none;
}

.drawer-nav {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.drawer-group-label {
  margin-bottom: 7px;
  color: var(--app-text-muted);
  font-size: 10px;
  font-weight: 750;
  letter-spacing: .14em;
}

.drawer-item {
  display: grid;
  grid-template-columns: 30px 1fr;
  gap: 10px;
  width: 100%;
  padding: 10px;
  border-radius: 11px;
  background: transparent;
  color: var(--app-text);
  text-align: left;
}

.drawer-item.is-active {
  background: color-mix(in srgb, var(--td-brand-color, #2563eb) 12%, transparent);
  color: var(--td-brand-color, #2563eb);
}

.drawer-item strong,
.drawer-item small {
  display: block;
}

.drawer-item strong {
  font-size: 13px;
}

.drawer-item small {
  margin-top: 3px;
  color: var(--app-text-muted);
  font-size: 10px;
  line-height: 1.4;
}

@media (max-width: 1180px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .app-sidebar,
  .workspace-header,
  .workspace-facts {
    display: none;
  }

  .app-workspace {
    width: 100%;
    padding: 0 16px 28px;
  }

  .mobile-topbar {
    position: sticky;
    top: 0;
    z-index: 15;
    display: grid;
    grid-template-columns: 38px 1fr auto;
    align-items: center;
    gap: 10px;
    min-height: 62px;
    margin-inline: -16px;
    padding: 8px 16px;
    border-bottom: 1px solid var(--app-border);
    background: color-mix(in srgb, var(--app-surface) 94%, transparent);
    backdrop-filter: blur(14px);
  }

  .mobile-menu-button {
    display: grid;
    width: 36px;
    height: 36px;
    place-items: center;
    border: 1px solid var(--app-border);
    border-radius: 10px;
    background: var(--app-surface-soft);
    color: var(--app-text);
    font-size: 18px;
  }

  .mobile-title-block {
    display: flex;
    min-width: 0;
    flex-direction: column;
    gap: 2px;
  }

  .mobile-title-block strong {
    overflow: hidden;
    color: var(--app-text);
    font-size: 15px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .workspace-main {
    padding-top: 14px;
  }
}

@media (max-width: 600px) {
  .summary-grid {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .summary-card {
    padding: 13px 14px 11px;
  }

  .summary-card-sub {
    min-height: 0;
  }

  :global(.t-dialog) {
    width: calc(100vw - 24px) !important;
    max-width: calc(100vw - 24px) !important;
    max-height: calc(100dvh - 24px) !important;
  }
}
</style>
