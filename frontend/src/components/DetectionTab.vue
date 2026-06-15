<template>
  <div class="detection-tab" :class="{ 'is-dark-theme': isDarkTheme }">
    <!-- 概览卡：检测轮次记录（置顶） -->
    <t-card size="small" :bordered="false" class="detection-card">
      <div class="config-header">
        <div>
          <div class="section-title section-title--flush">检测概览</div>
          <p class="section-desc">每次定期检测的执行记录，按时间倒序排列。点击"日志"查看该轮每个频道的检测明细。</p>
        </div>
      </div>

      <div class="det-runs-toolbar">
        <t-date-range-picker
          v-model="detDateRange"
          placeholder="选择时间范围"
          size="small"
          style="width: 320px"
          clearable
        />
        <t-button theme="primary" size="small" @click="loadDetRuns">查询</t-button>
      </div>

      <t-table
        :columns="detRunColumns"
        :data="detRuns"
        :bordered="false"
        row-key="cycle_id"
        size="small"
        :pagination="null"
      >
        <template #trigger_source="{ row }">
          <t-tag :theme="row.trigger_source === 'manual' ? 'warning' : 'default'" size="small" variant="light">
            {{ row.trigger_source === 'manual' ? '手动' : '自动' }}
          </t-tag>
        </template>
        <template #duration_seconds="{ row }">
          {{ row.duration_seconds != null ? row.duration_seconds.toFixed(1) + 's' : '-' }}
        </template>
        <template #op="{ row }">
          <t-button size="small" variant="outline" theme="primary" @click="openDetDetail(row)">日志</t-button>
        </template>
      </t-table>
    </t-card>

    <!-- 配置卡：检测维护 + 运行日志 + 保存按钮 -->
    <t-card size="small" :bordered="false" class="detection-card" style="margin-top: 12px;">
      <div class="config-header">
        <div>
          <div class="section-title section-title--flush">检测监控</div>
          <p class="section-desc">管理定期检测策略与实时运行日志。</p>
        </div>
      </div>

      <div class="config-panel-grid">
        <section class="config-panel">
          <div class="config-panel-head">
            <div class="config-panel-eyebrow">检测维护</div>
            <h3>定期检测与淘汰</h3>
            <p>扫描结果会定期检测可用性，连续失败达到阈值的源自动删除，保持结果池质量。</p>
          </div>

          <div class="config-field-list">
            <div class="config-field">
              <div class="config-field-meta">
                <label>检测间隔（分钟）</label>
                <span>每隔多久对持久化结果执行一轮健康检查。设为 0 暂停检测。</span>
              </div>
              <t-input-number v-model="detCfg.detection_interval_minutes" :min="0" :step="10" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>连续失败删除阈值</label>
                <span>源连续检测失败几次后自动从结果池中删除。</span>
              </div>
              <t-input-number v-model="detCfg.deletion_threshold" :min="1" :step="1" class="field-control" />
            </div>
          </div>
        </section>

        <section class="config-panel config-panel--log">
          <div class="config-panel-head">
            <div class="config-panel-eyebrow">运行日志</div>
            <h3>定期检测日志</h3>
            <p>最近一轮检测的执行记录，自动刷新。</p>
          </div>

          <div class="detection-log-toolbar">
            <t-button size="small" variant="outline" @click="detAutoScroll = !detAutoScroll">
              {{ detAutoScroll ? '暂停滚动' : '自动滚动' }}
            </t-button>
            <t-button size="small" variant="outline" @click="detLogLines = []">清空</t-button>
          </div>

          <div class="detection-log-panel" ref="detLogPanelRef">
            <div v-if="!detLogLines.length" class="detection-log-empty">暂无日志</div>
            <div v-for="line in detLogLines" :key="line.ts + line.message" class="detection-log-line">
              <span class="detection-log-time">[{{ line.ts }}]</span>
              <span :class="detLogClass(line.message)">{{ line.message }}</span>
            </div>
          </div>
        </section>
      </div>

      <div class="config-actions">
        <div class="config-actions-tip">修改检测间隔或淘汰阈值后需点击保存生效。</div>
        <t-space>
          <t-button theme="primary" :loading="saving" @click="saveDetConfig">保存配置</t-button>
          <t-button variant="outline" @click="loadConfig">重新加载</t-button>
        </t-space>
      </div>
    </t-card>

    <t-dialog
      v-model:visible="detDetailVisible"
      :header="'检测明细 — ' + detDetailCycleId"
      :footer="false"
      width="90%"
      destroy-on-close
      @close="detDetailSearch = ''"
    >
      <div class="det-detail-toolbar">
        <t-input
          v-model="detDetailSearch"
          placeholder="搜索频道名或 URL..."
          size="small"
          clearable
          style="width: 320px"
        />
        <span class="det-detail-count">
          共 {{ filteredDetDetails.length }} 条
          <template v-if="detDetailSearch">（已过滤）</template>
        </span>
      </div>

      <t-table
        :columns="detDetailColumns"
        :data="paginatedDetDetails"
        :bordered="false"
        row-key="url"
        size="small"
        :pagination="{
          current: detDetailPage,
          pageSize: detDetailPageSize,
          total: filteredDetDetails.length,
          pageSizeOptions: [20, 50, 100, 200],
          showJumper: true,
        }"
        @page-change="(p) => { detDetailPage = p.current; detDetailPageSize = p.pageSize }"
      >
        <template #check_ok="{ row }">
          <t-tag :theme="row.check_ok ? 'success' : 'danger'" size="small" variant="light">
            {{ row.check_ok ? '通过' : '失败' }}
          </t-tag>
        </template>
        <template #quality_status="{ row }">
          <t-tag :theme="detStatusTheme(row.quality_status)" size="small" variant="light">
            {{ detStatusLabel(row.quality_status) }}
          </t-tag>
        </template>
        <template #http_status="{ row }">
          <span :class="row.http_status === 200 ? 'det-val-ok' : 'det-val-fail'">{{ row.http_status || '-' }}</span>
        </template>
        <template #response_time_ms="{ row }">
          {{ row.response_time_ms ? Math.round(row.response_time_ms) + 'ms' : '-' }}
        </template>
        <template #response_size_bytes="{ row }">
          {{ formatBytes(row.response_size_bytes) }}
        </template>
      </t-table>
    </t-dialog>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useTheme } from '../composables/useTheme.js'
import { usePolling } from '../composables/usePolling.js'
import {
  apiDetectionLogs,
  apiDetectionRuns,
  apiDetectionRunResults,
  apiSaveScanConfig,
  apiScanConfig,
} from '../api.js'

const { theme } = useTheme()
const isDarkTheme = computed(() => theme.value === 'dark')
const saving = ref(false)

// ─── 检测配置 ───
const detCfg = reactive({
  detection_interval_minutes: 120,
  deletion_threshold: 3,
})

async function loadConfig() {
  try {
    const cfg = await apiScanConfig()
    detCfg.detection_interval_minutes = typeof cfg.detection_interval_minutes === 'number' ? cfg.detection_interval_minutes : 120
    detCfg.deletion_threshold = typeof cfg.deletion_threshold === 'number' ? cfg.deletion_threshold : 3
  } catch (_) {
    MessagePlugin.error('加载检测配置失败')
  }
}

async function saveDetConfig() {
  saving.value = true
  try {
    const res = await apiSaveScanConfig({ ...detCfg })
    if (res.ok) {
      MessagePlugin.success('检测配置已保存')
      if (res.config) {
        detCfg.detection_interval_minutes = typeof res.config.detection_interval_minutes === 'number' ? res.config.detection_interval_minutes : detCfg.detection_interval_minutes
        detCfg.deletion_threshold = typeof res.config.deletion_threshold === 'number' ? res.config.deletion_threshold : detCfg.deletion_threshold
      }
    } else {
      MessagePlugin.error(`保存失败: ${res.error || ''}`)
    }
  } catch (_) {
    MessagePlugin.error('保存失败')
  } finally {
    saving.value = false
  }
}

// ─── 定期检测日志 ───
const detLogLines = ref([])
const detAutoScroll = ref(true)
const detLogPanelRef = ref(null)

function detLogClass(message) {
  if (/通过|完成|检测完成/.test(message)) return 'det-log-pass'
  if (/失败|错误|异常/.test(message)) return 'det-log-fail'
  return 'det-log-info'
}

async function loadDetectionLogs() {
  try {
    const data = await apiDetectionLogs(300)
    if (Array.isArray(data)) {
      detLogLines.value = data
    }
  } catch (_) { /* ignore */ }
}

const { start: startDetPoll, stop: stopDetPoll } = usePolling(loadDetectionLogs, 10000)

watch(detLogLines, () => {
  if (!detAutoScroll.value) return
  nextTick(() => {
    const el = detLogPanelRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}, { deep: true })

// ─── 检测轮次记录 ───
const daysAgo = (n) => new Date(Date.now() - n * 86400000)
const fmt = (d) => {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
const detDateRange = ref([fmt(daysAgo(3)), fmt(new Date())])
const detRuns = ref([])

const detRunColumns = [
  { colKey: 'cycle_id', title: '轮次 ID', width: 220, ellipsis: true },
  { colKey: 'started_at', title: '开始时间', width: 170 },
  { colKey: 'trigger_source', title: '触发', width: 80 },
  { colKey: 'total_checked', title: '检测数', width: 80, align: 'center' },
  { colKey: 'ok_count', title: '通过', width: 70, align: 'center' },
  { colKey: 'failed_count', title: '失败', width: 70, align: 'center' },
  { colKey: 'deleted_count', title: '删除', width: 70, align: 'center' },
  { colKey: 'duration_seconds', title: '耗时', width: 90, align: 'center' },
  { colKey: 'op', title: '操作', width: 80, align: 'center' },
]

async function loadDetRuns() {
  try {
    const start = detDateRange.value?.[0] || null
    const end = detDateRange.value?.[1] || null
    const data = await apiDetectionRuns(start, end)
    if (Array.isArray(data)) detRuns.value = data
  } catch (e) {
    MessagePlugin.error('查询检测轮次失败: ' + (e?.message || ''))
  }
}

// ─── 检测明细弹窗 ───
const detDetailVisible = ref(false)
const detDetailCycleId = ref('')
const detRunDetails = ref([])
const detDetailSearch = ref('')
const detDetailPage = ref(1)
const detDetailPageSize = ref(20)

const detDetailColumns = [
  { colKey: 'name', title: '频道名称', width: 160, ellipsis: true },
  { colKey: 'url', title: 'URL', width: 280, ellipsis: true },
  { colKey: 'check_ok', title: '检测结果', width: 90, align: 'center' },
  { colKey: 'http_status', title: 'HTTP', width: 70, align: 'center' },
  { colKey: 'response_time_ms', title: '响应时间', width: 100, align: 'center' },
  { colKey: 'response_size_bytes', title: '大小', width: 80, align: 'center' },
  { colKey: 'consecutive_failures', title: '连续失败', width: 90, align: 'center' },
  { colKey: 'quality_status', title: '状态', width: 90, align: 'center' },
]

const filteredDetDetails = computed(() => {
  const q = detDetailSearch.value.toLowerCase().trim()
  if (!q) return detRunDetails.value
  return detRunDetails.value.filter(r =>
    (r.name || '').toLowerCase().includes(q) ||
    (r.url || '').toLowerCase().includes(q)
  )
})

const paginatedDetDetails = computed(() => {
  const start = (detDetailPage.value - 1) * detDetailPageSize.value
  return filteredDetDetails.value.slice(start, start + detDetailPageSize.value)
})

watch(detDetailSearch, () => { detDetailPage.value = 1 })

async function openDetDetail(row) {
  detDetailCycleId.value = row.cycle_id
  detDetailSearch.value = ''
  detDetailPage.value = 1
  detDetailVisible.value = true
  try {
    const data = await apiDetectionRunResults(row.cycle_id)
    if (Array.isArray(data)) detRunDetails.value = data
  } catch (e) {
    detRunDetails.value = []
    MessagePlugin.error('加载检测明细失败: ' + (e?.message || ''))
  }
}

function detStatusTheme(status) {
  if (status === 'good') return 'success'
  if (status === 'poor') return 'warning'
  if (status === 'unreachable') return 'danger'
  return 'default'
}

function detStatusLabel(status) {
  const map = { good: '正常', poor: '较差', unreachable: '不可达', pending: '待检测' }
  return map[status] || status
}

function formatBytes(bytes) {
  if (!bytes) return '-'
  if (bytes < 1024) return bytes + ' B'
  return (bytes / 1024).toFixed(1) + ' KB'
}

onMounted(() => {
  loadConfig()
  startDetPoll()
  loadDetRuns()
})

onBeforeUnmount(() => {
  stopDetPoll()
})
</script>

<style scoped>
.detection-tab {
  padding-top: 4px;
  --surface-text-primary: #0f172a;
  --surface-text-secondary: #475569;
  --surface-text-muted: #64748b;
  --surface-border-strong: rgba(148, 163, 184, 0.18);
  --surface-border-soft: rgba(226, 232, 240, 0.92);
  --surface-border-softer: rgba(226, 232, 240, 0.96);
  --surface-shell-bg: rgba(255, 255, 255, 0.8);
  --surface-shell-gradient:
    radial-gradient(circle at top right, rgba(16, 185, 129, 0.08), transparent 30%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.96));
  --surface-panel-accent: linear-gradient(180deg, rgba(236, 253, 245, 0.9), rgba(255, 255, 255, 0.92));
  --surface-field-bg: rgba(248, 250, 252, 0.84);
  --surface-inner-bg: rgba(255, 255, 255, 0.82);
  --surface-pill-bg: rgba(15, 23, 42, 0.05);
  --surface-pill-accent-bg: rgba(16, 185, 129, 0.12);
  --surface-pill-accent-text: #047857;
  --surface-accent: #0f766e;
  --surface-accent-strong: #047857;
  --surface-accent-soft: rgba(16, 185, 129, 0.08);
  --surface-link-accent: #2563eb;
  --surface-shadow: 0 18px 48px rgba(15, 23, 42, 0.05);
}

.detection-tab.is-dark-theme {
  --surface-text-primary: #e5edf7;
  --surface-text-secondary: #9fb0c7;
  --surface-text-muted: #8fa2ba;
  --surface-border-strong: rgba(71, 85, 105, 0.48);
  --surface-border-soft: rgba(71, 85, 105, 0.58);
  --surface-border-softer: rgba(71, 85, 105, 0.52);
  --surface-shell-bg: rgba(15, 23, 42, 0.72);
  --surface-shell-gradient:
    radial-gradient(circle at top right, rgba(45, 212, 191, 0.14), transparent 32%),
    linear-gradient(180deg, rgba(17, 24, 39, 0.94), rgba(8, 15, 28, 0.98));
  --surface-panel-accent: linear-gradient(180deg, rgba(10, 38, 40, 0.94), rgba(8, 15, 28, 0.95));
  --surface-field-bg: rgba(15, 23, 42, 0.78);
  --surface-inner-bg: rgba(15, 23, 42, 0.7);
  --surface-pill-bg: rgba(148, 163, 184, 0.14);
  --surface-pill-accent-bg: rgba(45, 212, 191, 0.18);
  --surface-pill-accent-text: #99f6e4;
  --surface-accent: #5eead4;
  --surface-accent-strong: #99f6e4;
  --surface-accent-soft: rgba(45, 212, 191, 0.16);
  --surface-link-accent: #93c5fd;
  --surface-shadow: 0 18px 48px rgba(0, 0, 0, 0.28);
}

.detection-card {
  color: var(--surface-text-primary);
  border-radius: 18px;
  background: var(--surface-shell-gradient);
}

.config-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.section-title {
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--td-border-level-1-color, #f3f4f6);
  font-size: 15px;
  font-weight: 600;
}

.section-title--flush {
  margin-bottom: 6px;
  padding-bottom: 0;
  border-bottom: 0;
}

.section-desc {
  max-width: 760px;
  margin: 0;
  color: var(--surface-text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.config-panel-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.config-panel {
  padding: 18px;
  border: 1px solid var(--surface-border-strong);
  border-radius: 18px;
  background: var(--surface-shell-bg);
  box-shadow: var(--surface-shadow);
  backdrop-filter: blur(8px);
}

.config-panel-head {
  margin-bottom: 16px;
}

.config-panel-eyebrow {
  margin-bottom: 6px;
  color: var(--surface-accent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.config-panel-head h3 {
  margin: 0;
  color: var(--surface-text-primary);
  font-size: 18px;
  font-weight: 700;
}

.config-panel-head p {
  margin: 8px 0 0;
  color: var(--surface-text-muted);
  font-size: 13px;
  line-height: 1.6;
}

.config-field-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.config-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid var(--surface-border-soft);
  border-radius: 14px;
  background: var(--surface-field-bg);
}

.config-field-meta {
  min-width: 0;
  flex: 1;
}

.config-field-meta label {
  display: block;
  margin-bottom: 4px;
  color: var(--surface-text-primary);
  font-size: 14px;
  font-weight: 600;
}

.config-field-meta span {
  display: block;
  color: var(--surface-text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.field-control {
  width: 220px;
  max-width: 100%;
  flex-shrink: 0;
}

.config-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--surface-border-soft);
}

.config-actions-tip {
  color: var(--surface-text-secondary);
  font-size: 12px;
  line-height: 1.6;
}

/* ─── 定期检测日志面板 ─── */
.config-panel--log {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.detection-log-toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}

.detection-log-panel {
  flex: 1;
  height: 0;
  min-height: 120px;
  max-height: 260px;
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

.detection-log-line {
  white-space: pre-wrap;
  word-break: break-all;
}

.detection-log-empty {
  color: #94a3b8;
}

.detection-log-time {
  margin-right: 8px;
  color: #93c5fd;
}

.det-log-pass {
  color: #86efac;
}

.det-log-fail {
  color: #fda4af;
}

.det-log-info {
  color: #d8b4fe;
}

/* ─── 检测轮次表格 + 弹窗 ─── */
.det-runs-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}

.det-detail-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}

.det-detail-count {
  color: var(--surface-text-muted, #64748b);
  font-size: 13px;
}

.det-val-ok {
  color: #16a34a;
  font-weight: 600;
}

.det-val-fail {
  color: #dc2626;
  font-weight: 600;
}

@media (max-width: 1100px) {
  .config-panel-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .config-header,
  .config-actions,
  .config-field {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
