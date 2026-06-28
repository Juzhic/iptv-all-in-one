<template>
  <div class="detection-tab" :class="{ 'is-dark-theme': isDarkTheme }">
    <!-- 概览卡：检测轮次记录（置顶） -->
    <t-card size="small" :bordered="false" class="detection-card">
      <div class="config-header">
        <div>
          <div class="section-title section-title--flush">检测概览</div>
          <p class="section-desc">每次定期检测的执行记录，按时间倒序排列。点击"日志"查看该轮每个频道的检测明细。</p>
          <p v-if="nextCheckCountdown" class="next-check-countdown">{{ nextCheckCountdown }}</p>
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
        <template #run_status="{ row }">
          <t-tag :theme="detRunStatus(row).theme" size="small" variant="light" :title="detRunStatus(row).content">
            {{ detRunStatus(row).label }}
          </t-tag>
        </template>
        <template #duration_seconds="{ row }">
          {{ row.duration_seconds != null ? row.duration_seconds.toFixed(1) + 's' : '-' }}
        </template>
        <template #pass_rate="{ row }">
          <span v-if="row.total_checked" :class="passRateClass(row)">{{ passRate(row) }}%</span>
          <span v-else class="det-val-muted">-</span>
          <span v-if="row._trend === 'up'" class="det-trend det-trend-up">↑</span>
          <span v-else-if="row._trend === 'down'" class="det-trend det-trend-down">↓</span>
          <span v-else-if="row._trend === 'flat'" class="det-trend det-trend-flat">→</span>
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
              <t-input-number v-model="detCfg.detection_interval_minutes" :min="0" :max="10080" :step="10" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>连续失败删除阈值</label>
                <span>源连续检测失败几次后自动从结果池中删除。</span>
              </div>
              <t-input-number v-model="detCfg.deletion_threshold" :min="1" :max="100" :step="1" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>稳定频道检测倍数</label>
                <span>stability≥80 的稳定频道检测间隔 = 检测间隔 × 此倍数。设为 3 表示每 3 个周期检测一次。</span>
              </div>
              <t-input-number v-model="detCfg.stable_channel_multiplier" :min="1" :max="10" :step="1" class="field-control" />
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
            <t-button size="small" variant="outline" @click="clearDetLogLines">清空</t-button>
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
      @close="detDetailPage = 1"
    >
      <div class="det-detail-toolbar">
        <t-input v-model="detDetailSearch" placeholder="搜索频道名/URL..." clearable size="small" style="width:200px" />
        <t-select v-model="detDetailCheckFilter" size="small" style="width:120px" clearable placeholder="检测结果">
          <t-option value="" label="全部结果" />
          <t-option value="pass" label="通过" />
          <t-option value="fail" label="失败" />
        </t-select>
        <t-select v-model="detDetailQualityFilter" size="small" style="width:120px" clearable placeholder="质量状态">
          <t-option value="" label="全部状态" />
          <t-option value="good" label="正常" />
          <t-option value="poor" label="较差" />
          <t-option value="unreachable" label="不可达" />
        </t-select>
        <span class="det-detail-count">
          共 {{ filteredDetDetails.length }} 条
        </span>
      </div>

      <t-table
        :columns="detDetailColumns"
        :data="filteredDetDetails"
        :bordered="false"
        row-key="url"
        size="small"
        :sort="detDetailSortInfo"
        @sort-change="onDetDetailSortChange"
        :pagination="{
          current: detDetailPage,
          pageSize: detDetailPageSize,
          total: detDetailTotal,
          pageSizeOptions: [20, 50, 100, 200],
          showJumper: true,
        }"
        @page-change="onDetDetailPageChange"
      >
        <template #check_ok="{ row }">
          <t-tag :theme="row.check_ok ? 'success' : 'danger'" size="small" variant="light">
            {{ row.check_ok ? '通过' : '失败' }}
          </t-tag>
        </template>
        <template #quality_status="{ row }">
          <t-tag :theme="qualityTheme(row.quality_status)" size="small" variant="light">
            {{ qualityLabel(row.quality_status) }}
          </t-tag>
        </template>
        <template #op="{ row }">
          <t-button size="small" variant="outline" theme="primary" @click="recheckChannel(row.url)">重新检测</t-button>
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
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { useTheme } from '../composables/useTheme.js'
import { qualityTheme, qualityLabel } from '../utils/quality.js'
import {
  apiDetectionLogs,
  apiDetectionStatus,
  apiDetectionRuns,
  apiDetectionRunResults,
  apiPersistentRecheck,
  apiSaveScanConfig,
  apiScanConfig,
  connectDetectionSse,
} from '../api.js'

const { theme } = useTheme()
const isDarkTheme = computed(() => theme.value === 'dark')
const saving = ref(false)

// ─── 检测配置 ───
const detCfg = reactive({
  detection_interval_minutes: 120,
  deletion_threshold: 3,
  stable_channel_multiplier: 3,
})

async function loadConfig() {
  try {
    const cfg = await apiScanConfig()
    detCfg.detection_interval_minutes = typeof cfg.detection_interval_minutes === 'number' ? cfg.detection_interval_minutes : 120
    detCfg.deletion_threshold = typeof cfg.deletion_threshold === 'number' ? cfg.deletion_threshold : 3
    detCfg.stable_channel_multiplier = typeof cfg.stable_channel_multiplier === 'number' ? cfg.stable_channel_multiplier : 3
  } catch (_) {
    MessagePlugin.error('加载检测配置失败')
  }
}

function validateDetConfig() {
  const errors = []
  if (detCfg.detection_interval_minutes < 0 || detCfg.detection_interval_minutes > 10080) {
    errors.push('检测间隔需在 0-10080 分钟之间')
  }
  if (detCfg.deletion_threshold < 1 || detCfg.deletion_threshold > 100) {
    errors.push('连续失败删除阈值需在 1-100 之间')
  }
  if (detCfg.stable_channel_multiplier < 1 || detCfg.stable_channel_multiplier > 10) {
    errors.push('稳定频道检测倍数需在 1-10 之间')
  }
  return errors
}

async function saveDetConfig() {
  const errors = validateDetConfig()
  if (errors.length) {
    MessagePlugin.warning(errors[0])
    return
  }
  saving.value = true
  try {
    const res = await apiSaveScanConfig({ ...detCfg })
    MessagePlugin.success('检测配置已保存')
    detCfg.detection_interval_minutes = typeof res.detection_interval_minutes === 'number' ? res.detection_interval_minutes : detCfg.detection_interval_minutes
    detCfg.deletion_threshold = typeof res.deletion_threshold === 'number' ? res.deletion_threshold : detCfg.deletion_threshold
    detCfg.stable_channel_multiplier = typeof res.stable_channel_multiplier === 'number' ? res.stable_channel_multiplier : detCfg.stable_channel_multiplier
    await loadDetectionStatus()
  } catch (error) {
    MessagePlugin.error(`保存失败: ${error.message}`)
  } finally {
    saving.value = false
  }
}

// ─── 定期检测日志 ───
const detLogLines = ref([])
const detAutoScroll = ref(true)
const detLogPanelRef = ref(null)
let detEventSource = null
let detPollFallback = null

function connectDetectionStream() {
  disconnectDetectionSse()
  try {
    detEventSource = connectDetectionSse({
      status(e) {
        try {
          const status = JSON.parse(e.data)
          detStatus.value = status
          updateDetectionCountdown()
          if (!status.cycle_running) loadDetRuns()
        } catch (_) {}
      },
      log(e) {
        try {
          const entry = JSON.parse(e.data)
          detLogLines.value.push(entry)
          const MAX_DET_LOG = 500
          if (detLogLines.value.length > MAX_DET_LOG) {
            detLogLines.value = detLogLines.value.slice(-400)
          }
        } catch (_) {}
      },
      onerror() {
        disconnectDetectionSse()
        startDetPollFallback()
      },
    })
  } catch (_) {
    startDetPollFallback()
  }
}

function disconnectDetectionSse() {
  if (detEventSource) {
    detEventSource.close()
    detEventSource = null
  }
  stopDetPollFallback()
}

function startDetPollFallback() {
  stopDetPollFallback()
  detPollFallback = setInterval(() => {
    loadDetectionLogs()
    loadDetectionStatus()
  }, 10000)
}

function stopDetPollFallback() {
  if (detPollFallback) {
    clearInterval(detPollFallback)
    detPollFallback = null
  }
}

// ─── 下次检测倒计时 ───
const nextCheckCountdown = ref('')
const detStatus = ref({})
let countdownTimer = null

function parseLocalDateTime(value) {
  if (!value) return NaN
  if (value instanceof Date) return value.getTime()
  return new Date(String(value).replace(' ', 'T')).getTime()
}

function updateDetectionCountdown() {
  if (!detCfg.detection_interval_minutes || detCfg.detection_interval_minutes <= 0) {
    nextCheckCountdown.value = ''
    return
  }
  if (detStatus.value?.cycle_running) {
    nextCheckCountdown.value = '检测正在执行'
    return
  }
  if (detStatus.value?.running === false && !detStatus.value?.next_cycle_at) {
    nextCheckCountdown.value = '检测调度未启动'
    return
  }

  let nextTime = parseLocalDateTime(detStatus.value?.next_cycle_at)
  if (!Number.isFinite(nextTime)) {
    const latestAutoCycle = detRuns.value?.find?.(row => row.trigger_source !== 'manual') || detRuns.value?.[0]
    const lastTime = parseLocalDateTime(latestAutoCycle?.started_at)
    if (!Number.isFinite(lastTime)) {
      nextCheckCountdown.value = ''
      return
    }
    nextTime = lastTime + detCfg.detection_interval_minutes * 60 * 1000
  }

  const diffMs = nextTime - Date.now()
  if (diffMs <= 0) {
    nextCheckCountdown.value = '即将执行'
    return
  }
  const totalMin = Math.floor(diffMs / 60000)
  const hours = Math.floor(totalMin / 60)
  const mins = totalMin % 60
  let text = '下次检测：'
  if (hours > 0) text += hours + '小时'
  if (mins > 0 || hours === 0) text += mins + '分钟后'
  nextCheckCountdown.value = text
}

async function recheckChannel(url) {
  try {
    const res = await apiPersistentRecheck(url)
    if (res.ok) {
      MessagePlugin.success('已触发重新检测')
    } else {
      MessagePlugin.error(res.error || '重新检测失败')
    }
  } catch (_) {
    MessagePlugin.error('重新检测失败')
  }
}

async function clearDetLogLines() {
  const confirmed = await DialogPlugin.confirm({
    header: '确认清空',
    body: '清空后日志将无法恢复，确认清空？',
    theme: 'warning',
    confirmBtn: { theme: 'danger' }
  })
  if (!confirmed) return
  detLogLines.value = []
}

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

async function loadDetectionStatus() {
  try {
    const data = await apiDetectionStatus()
    if (data && typeof data === 'object') {
      detStatus.value = data
    }
  } catch (_) { /* ignore */ }
  updateDetectionCountdown()
}

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
  { colKey: 'run_status', title: '状态', width: 80, align: 'center' },
  { colKey: 'total_checked', title: '检测数', width: 80, align: 'center' },
  { colKey: 'ok_count', title: '通过', width: 70, align: 'center' },
  { colKey: 'failed_count', title: '失败', width: 70, align: 'center' },
  { colKey: 'deleted_count', title: '删除', width: 70, align: 'center' },
  { colKey: 'duration_seconds', title: '耗时', width: 90, align: 'center' },
  { colKey: 'pass_rate', title: '通过率', width: 90, align: 'center' },
  { colKey: 'op', title: '操作', width: 80, align: 'center' },
]

function detRunStatus(row) {
  if (row.error) return { label: '异常', theme: 'danger', content: row.error }
  if (row.finished_at) return { label: '完成', theme: 'success', content: '' }
  return { label: '进行中', theme: 'warning', content: '' }
}

async function loadDetRuns() {
  try {
    const start = detDateRange.value?.[0] || null
    const end = detDateRange.value?.[1] || null
    const data = await apiDetectionRuns(start, end)
    if (Array.isArray(data)) {
      // Compute pass rate trend between consecutive runs
      for (let i = 0; i < data.length; i++) {
        const curr = data[i]
        const prev = data[i + 1] // data is time-descending, so next index is older
        if (curr.total_checked && prev?.total_checked) {
          const currRate = (curr.ok_count / curr.total_checked) * 100
          const prevRate = (prev.ok_count / prev.total_checked) * 100
          const diff = currRate - prevRate
          if (diff > 1) curr._trend = 'up'
          else if (diff < -1) curr._trend = 'down'
          else curr._trend = 'flat'
        }
      }
      detRuns.value = data
    }
    updateDetectionCountdown()
  } catch (e) {
    MessagePlugin.error('查询检测轮次失败: ' + (e?.message || ''))
  }
}

// ─── 检测明细弹窗 ───
const detDetailVisible = ref(false)
const detDetailCycleId = ref('')
const detRunDetails = ref([])
const detDetailPage = ref(1)
const detDetailPageSize = ref(20)
const detDetailTotal = ref(0)
const detDetailSearch = ref('')
const detDetailCheckFilter = ref('')
const detDetailQualityFilter = ref('')
const detDetailSortInfo = ref({})

function onDetDetailSortChange(sort) {
  detDetailSortInfo.value = sort
}

const filteredDetDetails = computed(() => {
  let data = [...detRunDetails.value]
  const q = detDetailSearch.value?.toLowerCase()
  if (q) {
    data = data.filter(r =>
      (r.name || '').toLowerCase().includes(q) || (r.url || '').toLowerCase().includes(q)
    )
  }
  if (detDetailCheckFilter.value === 'pass') data = data.filter(r => r.check_ok)
  else if (detDetailCheckFilter.value === 'fail') data = data.filter(r => !r.check_ok)
  if (detDetailQualityFilter.value) data = data.filter(r => r.quality_status === detDetailQualityFilter.value)
  const { sortBy, descending } = detDetailSortInfo.value
  if (sortBy) {
    data.sort((a, b) => {
      const va = a[sortBy] ?? (descending ? -Infinity : Infinity)
      const vb = b[sortBy] ?? (descending ? -Infinity : Infinity)
      if (typeof va === 'number' && typeof vb === 'number') return descending ? vb - va : va - vb
      return descending ? String(vb).localeCompare(String(va)) : String(va).localeCompare(String(vb))
    })
  }
  return data
})

const detDetailColumns = [
  { colKey: 'name', title: '频道名称', width: 160, ellipsis: true },
  { colKey: 'url', title: 'URL', width: 280, ellipsis: true },
  { colKey: 'check_ok', title: '检测结果', width: 90, align: 'center' },
  { colKey: 'http_status', title: 'HTTP', width: 70, align: 'center' },
  { colKey: 'response_time_ms', title: '响应时间', width: 100, align: 'center', sorter: true },
  { colKey: 'response_size_bytes', title: '大小', width: 80, align: 'center' },
  { colKey: 'consecutive_failures', title: '连续失败', width: 90, align: 'center', sorter: true },
  { colKey: 'quality_status', title: '状态', width: 90, align: 'center' },
  { colKey: 'op', title: '操作', width: 90, align: 'center' },
]

async function loadDetDetail() {
  try {
    const data = await apiDetectionRunResults(detDetailCycleId.value, detDetailPage.value, detDetailPageSize.value)
    if (data && Array.isArray(data.items)) {
      detRunDetails.value = data.items
      detDetailTotal.value = data.total || 0
    } else if (Array.isArray(data)) {
      detRunDetails.value = data
      detDetailTotal.value = data.length
    }
  } catch (e) {
    detRunDetails.value = []
    detDetailTotal.value = 0
    MessagePlugin.error('加载检测明细失败: ' + (e?.message || ''))
  }
}

function onDetDetailPageChange(pageInfo) {
  detDetailPage.value = pageInfo.current
  detDetailPageSize.value = pageInfo.pageSize
  loadDetDetail()
}

async function openDetDetail(row) {
  detDetailCycleId.value = row.cycle_id
  detDetailPage.value = 1
  detDetailVisible.value = true
  detDetailSearch.value = ''
  detDetailCheckFilter.value = ''
  detDetailQualityFilter.value = ''
  detDetailSortInfo.value = {}
  await loadDetDetail()
}

function formatBytes(bytes) {
  if (!bytes) return '-'
  if (bytes < 1024) return bytes + ' B'
  return (bytes / 1024).toFixed(1) + ' KB'
}

function passRate(row) {
  if (!row.total_checked) return 0
  return ((row.ok_count / row.total_checked) * 100).toFixed(1)
}

function passRateClass(row) {
  const rate = row.total_checked ? (row.ok_count / row.total_checked) * 100 : 0
  if (rate > 80) return 'det-val-ok'
  if (rate > 50) return 'det-val-warn'
  return 'det-val-fail'
}

onMounted(async () => {
  await loadConfig()
  connectDetectionStream()
  await Promise.all([loadDetectionStatus(), loadDetRuns()])
  updateDetectionCountdown()
  countdownTimer = setInterval(updateDetectionCountdown, 60000)
})

onBeforeUnmount(() => {
  disconnectDetectionSse()
  if (countdownTimer) clearInterval(countdownTimer)
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

.next-check-countdown {
  margin: 6px 0 0;
  color: var(--surface-accent);
  font-size: 13px;
  font-weight: 600;
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

.det-val-warn {
  color: #ca8a04;
  font-weight: 600;
}

.det-val-muted {
  color: #94a3b8;
}

.det-trend {
  margin-left: 4px;
  font-weight: 700;
  font-size: 13px;
}

.det-trend-up {
  color: #16a34a;
}

.det-trend-down {
  color: #dc2626;
}

.det-trend-flat {
  color: #94a3b8;
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
