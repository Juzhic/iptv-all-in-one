<template>
  <div v-if="latestRun || hasDashboardData" class="overview-tab">
    <section v-if="dashboardSignals.length" class="operations-grid" aria-label="扫描与任务状态">
      <article v-for="signal in dashboardSignals" :key="signal.label" class="operation-cell">
        <div class="operation-label">{{ signal.label }}</div>
        <div class="operation-value" :class="signal.tone">{{ signal.value }}</div>
        <div class="operation-detail">{{ signal.detail }}</div>
      </article>
    </section>

    <section v-if="hasAggregatedDashboard" class="quality-snapshot-grid" aria-label="扫描和数据来源质量趋势">
      <article class="quality-snapshot-card">
        <div class="panel-head quality-snapshot-head">
          <div>
            <div class="panel-title">频道扫描质量</div>
            <div class="panel-subtitle">最近 {{ scanTrendRows.length }} 轮漏斗与当前持久池状态</div>
          </div>
          <span class="panel-badge">良好率 {{ formatPercent(scanPool.good_rate_percent) }}</span>
        </div>

        <div class="pool-status-row" aria-label="持久池质量状态">
          <span class="pool-chip good">良好 {{ number(scanPool.good) }}</span>
          <span class="pool-chip poor">较差 {{ number(scanPool.poor) }}</span>
          <span class="pool-chip unreachable">不可达 {{ number(scanPool.unreachable) }}</span>
          <span class="pool-chip pending">待定 {{ number(scanPool.pending) }}</span>
        </div>
        <div class="pool-averages">
          <span>稳定性 {{ number(scanPool.avg_stability, 1) }}</span>
          <span>延迟 {{ number(scanPool.avg_delay_ms, 1) }} ms</span>
          <span>带宽 {{ number(scanPool.avg_bandwidth_MBps, 2) }} MB/s</span>
        </div>

        <div class="quality-table-shell">
          <div class="quality-table quality-table-scan" role="table" aria-label="频道扫描最近趋势">
            <div class="quality-table-row quality-table-header" role="row">
              <span role="columnheader">轮次</span><span role="columnheader">原始</span><span role="columnheader">去重</span><span role="columnheader">快筛</span><span role="columnheader">深检</span>
            </div>
            <div v-for="row in scanTrendRows" :key="row.scan_id" class="quality-table-row" role="row">
              <span role="cell" :title="row.finished_at || row.started_at">{{ formatShortTime(row.finished_at || row.started_at) }}</span>
              <strong role="cell">{{ number(row.total_raw) }}</strong>
              <strong role="cell">{{ number(row.total_deduped) }}</strong>
              <strong role="cell">{{ number(row.total_fast_pass) }}</strong>
              <strong role="cell">{{ number(row.total_deep_pass) }}</strong>
            </div>
          </div>
        </div>
      </article>

      <article class="quality-snapshot-card">
        <div class="panel-head quality-snapshot-head">
          <div>
            <div class="panel-title">数据来源质量</div>
            <div class="panel-subtitle">来源数量、频道覆盖、带宽和质量分趋势</div>
          </div>
          <span class="panel-badge">通过率 {{ formatPercent(subscriptionLatest.pass_rate, true) }}</span>
        </div>

        <div class="subscription-snapshot" aria-label="最新数据来源质量">
          <span><strong>{{ number(subscriptionLatest.source_count) }}</strong><small>数据来源</small></span>
          <span><strong>{{ number(subscriptionLatest.channels_total) }}</strong><small>频道总数</small></span>
          <span><strong>{{ number(subscriptionLatest.channels_passed) }}</strong><small>通过频道</small></span>
          <span><strong>{{ number(subscriptionLatest.avg_bandwidth_MBps, 2) }}</strong><small>MB/s</small></span>
          <span><strong>{{ number(subscriptionLatest.avg_quality, 2) }}</strong><small>平均质量</small></span>
        </div>

        <div class="quality-table-shell">
          <div class="quality-table quality-table-subscription" role="table" aria-label="数据来源质量最近趋势">
            <div class="quality-table-row quality-table-header" role="row">
              <span role="columnheader">轮次</span><span role="columnheader">来源</span><span role="columnheader">频道</span><span role="columnheader">通过率</span><span role="columnheader">带宽</span><span role="columnheader">质量</span>
            </div>
            <div v-for="row in subscriptionTrendRows" :key="row.run_id" class="quality-table-row" role="row">
              <span role="cell" :title="row.finished_at">{{ formatShortTime(row.finished_at) }}</span>
              <strong role="cell">{{ number(row.source_count) }}</strong>
              <strong role="cell">{{ number(row.channels_passed) }}/{{ number(row.channels_total) }}</strong>
              <strong role="cell">{{ formatPercent(row.pass_rate, true) }}</strong>
              <strong role="cell">{{ number(row.avg_bandwidth_MBps, 2) }}</strong>
              <strong role="cell">{{ number(row.avg_quality, 2) }}</strong>
            </div>
          </div>
        </div>
      </article>
    </section>

    <t-row :gutter="[16, 16]" align="stretch" class="overview-row">
      <t-col :xs="12" :sm="12" :md="8" :lg="8">
        <t-card size="small" :bordered="false" class="panel-card chart-card">
          <div class="panel-head">
            <div>
              <div class="panel-title">历史通过率趋势</div>
              <div class="panel-subtitle">{{ chartSubtitle }}</div>
            </div>
            <span class="panel-badge">均值 {{ avgPassRate.toFixed(1) }}%</span>
          </div>

          <div
            v-if="chartData.length >= 2"
            ref="passRateChartRef"
            class="chart-surface chart-surface-large"
          ></div>
          <div v-else class="chart-empty">至少需要 2 轮历史记录才会显示趋势</div>
        </t-card>
      </t-col>

      <t-col :xs="12" :sm="12" :md="4" :lg="4">
        <t-card size="small" :bordered="false" class="panel-card chart-card">
          <div class="panel-head">
            <div>
              <div class="panel-title">测试规模趋势</div>
              <div class="panel-subtitle">绿色为通过地址，红色为失败地址</div>
            </div>
            <span class="panel-badge">最新 {{ latestRun?.summary?.total_tested || 0 }} 条</span>
          </div>

          <div
            v-if="chartData.length"
            ref="volumeChartRef"
            class="chart-surface chart-surface-large"
          ></div>
          <div v-else class="chart-empty">暂无可展示的趋势数据</div>
        </t-card>
      </t-col>
    </t-row>

    <div v-if="metricCards.length" class="metrics-grid">
      <t-card
        v-for="card in metricCards"
        :key="card.label"
        size="small"
        :bordered="false"
        class="panel-card metric-card"
      >
        <div class="card-label">{{ card.label }}</div>
        <div class="card-value" :class="card.klass">{{ card.value }}</div>
        <div class="card-sub">{{ card.sub }}</div>
      </t-card>
    </div>

    <t-row :gutter="[16, 16]" align="stretch" class="overview-row">
      <t-col :xs="12" :sm="12" :md="6" :lg="6">
        <t-card size="small" :bordered="false" class="panel-card insight-card">
          <div class="panel-title panel-title-space">运行摘要</div>
          <div class="insight-list">
            <div v-for="item in highlights" :key="item.name" class="insight-item">
              <div class="insight-copy">
                <div class="insight-name">{{ item.name }}</div>
                <div class="insight-desc">{{ item.desc }}</div>
              </div>
              <div class="insight-value" :class="item.klass">{{ item.value }}</div>
            </div>
          </div>
        </t-card>
      </t-col>

      <t-col :xs="12" :sm="12" :md="6" :lg="6">
        <t-card size="small" :bordered="false" class="panel-card insight-card">
          <div class="panel-title panel-title-space">值得关注</div>
          <div class="insight-list">
            <div v-for="run in worstRuns" :key="run.run_id" class="insight-item">
              <div class="insight-copy">
                <div class="insight-name">{{ run.finished_at }}</div>
                <div class="insight-desc">
                  通过 {{ run.summary?.total_passed ?? '-' }}/{{ run.summary?.total_tested ?? '-' }}，
                  频道覆盖 {{ run.summary ? getCoverage(run.summary).toFixed(1) : '-' }}%
                </div>
              </div>
              <div class="insight-value warn">{{ run.summary?.pass_rate ?? '-' }}%</div>
            </div>
          </div>
        </t-card>
      </t-col>
    </t-row>
  </div>

  <div v-else class="empty-state">
    <ChartIcon size="48px" />
    <p>暂无测速数据</p>
    <p class="empty-state-sub">请前往“系统测试”页，点击“立即测试”发起首次检测</p>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import ChartIcon from 'tdesign-icons-vue-next/esm/components/chart.js'
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useTheme } from '../composables/useTheme.js'

echarts.use([BarChart, LineChart, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, CanvasRenderer])

const props = defineProps({
  dashboard: {
    type: Object,
    default: null,
  },
  latest: {
    type: Object,
    default: null,
  },
  runs: {
    type: Array,
    default: () => [],
  },
  channelSummary: {
    type: Object,
    default: () => ({}),
  },
  codecStats: {
    type: Object,
    default: () => ({}),
  },
})

const { theme } = useTheme()
const passRateChartRef = ref(null)
const volumeChartRef = ref(null)

let passRateChart = null
let volumeChart = null

const latestRun = computed(() => props.latest || props.dashboard?.subscriptions?.latest || null)
const chartData = computed(() => {
  const source = props.runs?.length ? props.runs : props.dashboard?.subscriptions?.trend
  return Array.isArray(source) ? source.slice() : []
})
const hasDashboardData = computed(() => Boolean(
  props.dashboard?.scan?.latest ||
  props.dashboard?.scan?.pool ||
  props.dashboard?.subscriptions?.best_source ||
  props.dashboard?.subscriptions?.degraded_source ||
  props.dashboard?.tasks,
))

function compactSource(source) {
  return source?.name || source?.source_ip || source?.source || source?.source_url || source?.platform || '--'
}

function number(value, digits = 0) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return digits ? (0).toFixed(digits) : '0'
  return digits ? parsed.toFixed(digits) : parsed.toLocaleString()
}

function formatPercent(value, ratio = false) {
  let parsed = Number(value)
  if (!Number.isFinite(parsed)) parsed = 0
  if (ratio || parsed <= 1) parsed *= 100
  return `${Math.max(0, Math.min(100, parsed)).toFixed(1)}%`
}

const scanPool = computed(() => props.dashboard?.scan?.pool || {})
const subscriptionLatest = computed(() => props.dashboard?.subscriptions?.latest || {})
const scanTrendRows = computed(() => {
  const rows = props.dashboard?.scan?.trend
  return Array.isArray(rows) ? [...rows].slice(-10).reverse() : []
})
const subscriptionTrendRows = computed(() => {
  const rows = props.dashboard?.subscriptions?.trend
  return Array.isArray(rows) ? [...rows].slice(-10).reverse() : []
})
const hasAggregatedDashboard = computed(() => Boolean(
  props.dashboard?.scan?.latest ||
  scanTrendRows.value.length ||
  props.dashboard?.subscriptions?.latest ||
  subscriptionTrendRows.value.length,
))

const dashboardSignals = computed(() => {
  if (!props.dashboard) return []
  const pool = props.dashboard.scan?.pool || {}
  const tasks = props.dashboard.tasks || {}
  const running = Object.values(tasks).filter(task => task?.active || ['starting', 'queued', 'running', 'stopping'].includes(String(task?.state || '').toLowerCase())).length
  const total = Number(
    pool.total || pool.total_count || pool.channels ||
    (Number(pool.good || 0) + Number(pool.poor || 0) + Number(pool.unreachable || 0) + Number(pool.pending || 0)),
  )
  const healthy = Number(pool.healthy || pool.good || pool.available || 0)
  return [
    {
      label: '资源池',
      value: total ? total.toLocaleString() : '--',
      detail: total ? `${healthy.toLocaleString()} 条健康或可用` : '暂无入库记录',
      tone: total ? 'blue' : '',
    },
    {
      label: '最佳来源',
      value: compactSource(props.dashboard.subscriptions?.best_source),
      detail: '按最新数据来源质量评估',
      tone: 'green',
    },
    {
      label: '退化来源',
      value: compactSource(props.dashboard.subscriptions?.degraded_source),
      detail: props.dashboard.subscriptions?.degraded_source ? '建议进入扫描结果复检' : '当前未发现明显退化',
      tone: props.dashboard.subscriptions?.degraded_source ? 'red' : 'green',
    },
    {
      label: '活动任务',
      value: String(running),
      detail: running ? '状态每 2 秒更新' : '当前任务队列空闲',
      tone: running ? 'purple' : '',
    },
  ]
})
const avgPassRate = computed(() => {
  const runs = chartData.value
  if (!runs.length) return 0
  return runs.reduce((sum, run) => sum + Number(run.summary?.pass_rate || 0), 0) / runs.length
})

const chartSubtitle = computed(() => {
  const count = chartData.value.length
  if (count < 2) return count === 1 ? '仅有 1 轮记录' : '暂无历史记录'
  return `最近 ${count} 轮，最新一轮在最右侧`
})

function getCoverage(summary) {
  return summary?.unique_channels_total
    ? (Number(summary.unique_channels_passed || 0) / Number(summary.unique_channels_total || 1)) * 100
    : 0
}

function formatShortTime(value) {
  return value ? value.slice(5, 16) : '--'
}

const metricCards = computed(() => {
  const runs = chartData.value
  if (!runs.length) return []

  const latestRun = runs[0]
  const bestRun = runs.reduce((best, run) => {
    if (!best) return run
    return Number(run.summary?.pass_rate || 0) > Number(best.summary?.pass_rate || 0) ? run : best
  }, null)

  const delta = Number(latestRun.summary?.pass_rate || 0) - avgPassRate.value
  const avgDuration = runs.reduce((sum, run) => sum + Number(run.duration_seconds || 0), 0) / runs.length / 60
  const avgCoverage = runs.reduce((sum, run) => sum + getCoverage(run.summary), 0) / runs.length

  return [
    {
      label: '历史轮次',
      value: `${runs.length}`,
      sub: `当前数据集共 ${runs.length} 轮`,
      klass: '',
    },
    {
      label: '平均通过率',
      value: `${avgPassRate.value.toFixed(1)}%`,
      sub: `最近一次 ${Number(latestRun.summary?.pass_rate || 0).toFixed(1)}%`,
      klass: avgPassRate.value >= 50 ? 'green' : 'red',
    },
    {
      label: '相对均值',
      value: `${delta >= 0 ? '+' : ''}${delta.toFixed(1)} pt`,
      sub: '对比历史平均通过率',
      klass: delta >= 0 ? 'green' : 'red',
    },
    {
      label: '平均频道覆盖',
      value: `${avgCoverage.toFixed(1)}%`,
      sub: '通过频道 / 总频道',
      klass: 'blue',
    },
    {
      label: '平均耗时',
      value: `${avgDuration.toFixed(avgDuration >= 10 ? 0 : 1)}`,
      sub: '分钟 / 轮',
      klass: 'purple',
    },
    {
      label: '最佳一轮',
      value: bestRun ? `${Number(bestRun.summary?.pass_rate || 0).toFixed(1)}%` : '-',
      sub: bestRun?.finished_at || '暂无',
      klass: 'green',
    },
  ]
})

const highlights = computed(() => {
  const runs = chartData.value
  if (!runs.length) return []

  const latestRun = runs[0]
  const previousRun = runs[1]
  const bestRun = runs.reduce((best, run) => {
    if (!best) return run
    return Number(run.summary?.pass_rate || 0) > Number(best.summary?.pass_rate || 0) ? run : best
  }, null)

  let streak = 0
  for (const run of runs) {
    if (Number(run.summary?.pass_rate || 0) >= 50) streak += 1
    else break
  }

  const delta = previousRun
    ? Number(latestRun.summary?.pass_rate || 0) - Number(previousRun.summary?.pass_rate || 0)
    : null

  return [
    {
      name: '最近一次测试',
      desc: `${latestRun.finished_at}，覆盖 ${latestRun.summary?.unique_channels_passed || 0}/${latestRun.summary?.unique_channels_total || 0} 个频道`,
      value: `${Number(latestRun.summary?.pass_rate || 0).toFixed(1)}%`,
      klass: Number(latestRun.summary?.pass_rate || 0) >= 50 ? 'good' : 'warn',
    },
    {
      name: '与上一轮对比',
      desc: previousRun ? `${previousRun.finished_at} 作为参考` : '暂无上一轮数据',
      value: delta === null ? '-' : `${delta >= 0 ? '+' : ''}${delta.toFixed(1)} pt`,
      klass: delta === null || delta >= 0 ? 'good' : 'warn',
    },
    {
      name: '最好的一轮',
      desc: bestRun?.finished_at || '暂无',
      value: bestRun ? `${Number(bestRun.summary?.pass_rate || 0).toFixed(1)}%` : '-',
      klass: 'good',
    },
    {
      name: '稳定连续轮次',
      desc: '通过率 >= 50% 的连续轮次',
      value: `${streak} 轮`,
      klass: streak >= 3 ? 'good' : '',
    },
  ]
})

const worstRuns = computed(() => {
  return [...chartData.value]
    .sort((left, right) => Number(left.summary?.pass_rate || 0) - Number(right.summary?.pass_rate || 0))
    .slice(0, 4)
})

function getPalette() {
  const dark = theme.value === 'dark'
  return {
    text: dark ? '#e5edf7' : '#111827',
    muted: dark ? '#94a3b8' : '#64748b',
    border: dark ? '#233047' : '#dbe5f2',
    grid: dark ? '#1f2b3d' : '#ecf1f7',
    brand: '#2f7cff',
    brandSoft: dark ? 'rgba(47, 124, 255, 0.32)' : 'rgba(47, 124, 255, 0.18)',
    success: '#22c55e',
    danger: '#ef4444',
    tooltipBg: dark ? 'rgba(9, 15, 28, 0.92)' : 'rgba(255, 255, 255, 0.96)',
    axisLine: dark ? '#304156' : '#cfdae8',
  }
}

function chartLabelOptions(length, width) {
  const usableWidth = Math.max(160, width || 0)
  const maxVisibleLabels = Math.max(2, Math.floor((usableWidth - 72) / 74))
  const interval = length <= maxVisibleLabels ? 0 : Math.ceil(length / maxVisibleLabels) - 1
  const rotate = usableWidth < 460 && length > 4 ? 35 : (interval > 1 ? 24 : 0)
  return {
    interval,
    rotate,
    hideOverlap: true,
    margin: rotate ? 14 : 8,
  }
}

function createPassRateOption() {
  const colors = getPalette()
  const orderedRuns = [...chartData.value].reverse()
  const labels = orderedRuns.map((run) => formatShortTime(run.finished_at))
  const values = orderedRuns.map((run) => Number(run.summary?.pass_rate || 0))
  const labelOptions = chartLabelOptions(labels.length, passRateChartRef.value?.clientWidth || 0)

  return {
    animationDuration: 420,
    animationDurationUpdate: 240,
    tooltip: {
      trigger: 'axis',
      backgroundColor: colors.tooltipBg,
      borderColor: colors.border,
      borderWidth: 1,
      textStyle: { color: colors.text },
      formatter(params) {
        const point = params?.[0]
        if (!point) return ''
        return `${point.axisValue}<br/>通过率 ${Number(point.data).toFixed(1)}%`
      },
    },
    grid: {
      left: 52,
      right: 24,
      top: 26,
      bottom: labelOptions.rotate ? 58 : 32,
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: labels,
      axisLine: {
        lineStyle: { color: colors.axisLine },
      },
      axisTick: { show: false },
      axisLabel: {
        color: colors.muted,
        ...labelOptions,
      },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      splitNumber: 4,
      axisLabel: {
        color: colors.muted,
        formatter: '{value}%',
      },
      splitLine: {
        lineStyle: { color: colors.grid },
      },
    },
    series: [
      {
        name: '通过率',
        type: 'line',
        smooth: 0.35,
        symbol: 'circle',
        symbolSize: 8,
        data: values,
        lineStyle: {
          width: 3,
          color: colors.brand,
        },
        itemStyle: {
          color: colors.brand,
          borderColor: colors.brandSoft,
          borderWidth: 3,
        },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: colors.brandSoft },
            { offset: 1, color: 'rgba(47, 124, 255, 0)' },
          ]),
        },
        markLine: {
          symbol: 'none',
          label: {
            color: '#8b5cf6',
            formatter: `平均 ${avgPassRate.value.toFixed(1)}%`,
          },
          lineStyle: {
            color: '#8b5cf6',
            type: 'dashed',
            width: 1.5,
          },
          data: [{ yAxis: Number(avgPassRate.value.toFixed(1)) }],
        },
      },
    ],
  }
}

function createVolumeOption() {
  const colors = getPalette()
  const orderedRuns = [...chartData.value].reverse()
  const labels = orderedRuns.map((run) => formatShortTime(run.finished_at))
  const passed = orderedRuns.map((run) => Number(run.summary?.total_passed || 0))
  const failed = orderedRuns.map((run) => {
    const total = Number(run.summary?.total_tested || 0)
    const ok = Number(run.summary?.total_passed || 0)
    return Math.max(total - ok, 0)
  })
  const labelOptions = chartLabelOptions(labels.length, volumeChartRef.value?.clientWidth || 0)

  return {
    animationDuration: 420,
    animationDurationUpdate: 240,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: colors.tooltipBg,
      borderColor: colors.border,
      borderWidth: 1,
      textStyle: { color: colors.text },
      formatter(params) {
        const index = params?.[0]?.dataIndex ?? 0
        const total = passed[index] + failed[index]
        return `${labels[index]}<br/>通过 ${passed[index]}<br/>失败 ${failed[index]}<br/>总计 ${total}`
      },
    },
    grid: {
      left: 52,
      right: 18,
      top: 26,
      bottom: labelOptions.rotate ? 58 : 32,
    },
    legend: {
      top: 0,
      right: 0,
      textStyle: { color: colors.muted },
      itemWidth: 10,
      itemHeight: 10,
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLine: {
        lineStyle: { color: colors.axisLine },
      },
      axisTick: { show: false },
      axisLabel: {
        color: colors.muted,
        ...labelOptions,
      },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        color: colors.muted,
      },
      splitLine: {
        lineStyle: { color: colors.grid },
      },
    },
    series: [
      {
        name: '通过地址',
        type: 'bar',
        stack: 'total',
        barMaxWidth: 18,
        data: passed,
        itemStyle: {
          color: colors.success,
          borderRadius: [0, 0, 6, 6],
        },
      },
      {
        name: '失败地址',
        type: 'bar',
        stack: 'total',
        barMaxWidth: 18,
        data: failed,
        itemStyle: {
          color: colors.danger,
          borderRadius: [6, 6, 0, 0],
        },
      },
    ],
  }
}

function ensureCharts() {
  if (passRateChartRef.value && !passRateChart) {
    passRateChart = echarts.init(passRateChartRef.value)
  }
  if (volumeChartRef.value && !volumeChart) {
    volumeChart = echarts.init(volumeChartRef.value)
  }
}

function disposeCharts() {
  passRateChart?.dispose()
  volumeChart?.dispose()
  passRateChart = null
  volumeChart = null
}

function resizeCharts() {
  passRateChart?.resize()
  volumeChart?.resize()
}

function renderCharts() {
  nextTick(() => {
    if (chartData.value.length < 2 && passRateChart) {
      passRateChart.dispose()
      passRateChart = null
    }
    if (!chartData.value.length && volumeChart) {
      volumeChart.dispose()
      volumeChart = null
    }

    ensureCharts()

    if (passRateChart) {
      passRateChart.setOption(createPassRateOption(), true)
      passRateChart.resize()
    }
    if (volumeChart) {
      volumeChart.setOption(createVolumeOption(), true)
      volumeChart.resize()
    }
  })
}

defineExpose({
  refreshCharts() {
    renderCharts()
    nextTick(() => resizeCharts())
  },
})

watch(() => props.runs, renderCharts, { deep: true })
watch(theme, renderCharts)

onMounted(() => {
  renderCharts()
  window.addEventListener('resize', resizeCharts)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resizeCharts)
  disposeCharts()
})
</script>

<style scoped>
.quality-snapshot-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 16px;
}

.quality-snapshot-card {
  min-width: 0;
  padding: 16px;
  border: 1px solid var(--td-border-level-1-color, #e5e7eb);
  border-radius: 14px;
  background: var(--td-bg-color-container, #fff);
}

.quality-snapshot-head { align-items: flex-start; }

.pool-status-row,
.pool-averages {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
  margin-top: 12px;
}

.pool-chip {
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--td-bg-color-secondarycontainer, #f3f4f6);
  color: var(--app-text-muted, #64748b);
  font-size: 11px;
  font-weight: 650;
}

.pool-chip.good { background: rgb(13 148 136 / 12%); color: #0f766e; }
.pool-chip.poor { background: rgb(245 158 11 / 14%); color: #b45309; }
.pool-chip.unreachable { background: rgb(239 68 68 / 12%); color: #dc2626; }
.pool-chip.pending { background: rgb(59 130 246 / 10%); color: #2563eb; }

.pool-averages {
  margin-top: 9px;
  color: var(--app-text-muted, #64748b);
  font-size: 11px;
}

.pool-averages span + span::before { margin-right: 7px; content: '·'; }

.subscription-snapshot {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 7px;
  margin-top: 12px;
}

.subscription-snapshot span {
  min-width: 0;
  padding: 8px 7px;
  border-radius: 9px;
  background: var(--app-surface-soft, #f8fafc);
  text-align: center;
}

.subscription-snapshot strong,
.subscription-snapshot small { display: block; }
.subscription-snapshot strong { overflow: hidden; color: var(--app-text, #0f172a); font-size: 14px; text-overflow: ellipsis; }
.subscription-snapshot small { margin-top: 3px; color: var(--app-text-muted, #64748b); font-size: 9px; }

.quality-table-shell {
  margin-top: 12px;
  overflow-x: auto;
  border: 1px solid var(--td-border-level-1-color, #e5e7eb);
  border-radius: 10px;
}

.quality-table { min-width: 470px; }
.quality-table-subscription { min-width: 560px; }
.quality-table-row {
  display: grid;
  align-items: center;
  min-height: 30px;
  padding: 0 9px;
  border-top: 1px solid var(--td-border-level-1-color, #e5e7eb);
  color: var(--app-text-muted, #64748b);
  font-size: 10px;
}
.quality-table-scan .quality-table-row { grid-template-columns: 1.35fr repeat(4, .75fr); }
.quality-table-subscription .quality-table-row { grid-template-columns: 1.25fr .6fr .9fr .75fr .7fr .65fr; }
.quality-table-row:first-child { border-top: 0; }
.quality-table-row strong { color: var(--app-text, #0f172a); font-weight: 650; }
.quality-table-header { background: var(--app-surface-soft, #f8fafc); font-weight: 700; }

.operations-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 1px;
  margin-bottom: 16px;
  overflow: hidden;
  border: 1px solid var(--td-border-level-1-color, #e5e7eb);
  border-radius: 14px;
  background: var(--td-border-level-1-color, #e5e7eb);
}

@media (max-width: 1100px) {
  .quality-snapshot-grid { grid-template-columns: 1fr; }
}

@media (max-width: 600px) {
  .quality-snapshot-card { padding: 13px; }
  .subscription-snapshot { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .pool-averages span + span::before { content: ''; margin: 0; }
}

.operation-cell {
  min-width: 0;
  padding: 12px 14px;
  background: var(--td-bg-color-container, #fff);
}

.operation-label,
.operation-detail {
  color: var(--td-text-color-placeholder, #64748b);
  font-size: 11px;
}

.operation-value {
  margin: 5px 0 4px;
  overflow: hidden;
  color: var(--td-text-color-primary, #111827);
  font-size: 18px;
  font-weight: 720;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.operation-value.green { color: #16a34a; }
.operation-value.red { color: #dc2626; }
.operation-value.blue { color: #2563eb; }
.operation-value.purple { color: #7c3aed; }

.overview-row {
  margin-bottom: 16px;
}

.panel-card {
  width: 100%;
  height: 100%;
  border-radius: 18px;
  box-shadow: var(--td-shadow-1);
}

.panel-card :deep(.t-card__body) {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.panel-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--td-text-color-secondary, #111827);
}

.panel-title-space {
  margin-bottom: 12px;
}

.panel-subtitle {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.55;
  color: var(--td-text-color-placeholder, #9ca3af);
}

.panel-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 4px 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--td-brand-color-1, #edf3ff) 65%, transparent);
  color: var(--td-brand-color, #366ef4);
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.chart-card {
  min-height: 360px;
}

.chart-surface {
  width: 100%;
}

.chart-surface-large {
  min-height: 278px;
}

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.metric-card {
  min-height: 140px;
}

.metric-card :deep(.t-card__body) {
  justify-content: flex-start;
}

.card-label {
  margin-bottom: 6px;
  font-size: 12px;
  color: var(--td-text-color-placeholder, #6b7280);
}

.card-value {
  font-size: 32px;
  font-weight: 700;
  line-height: 1.15;
  color: var(--td-text-color-primary, #111827);
}

.card-value.green { color: #16a34a; }
.card-value.red { color: #dc2626; }
.card-value.blue { color: #2563eb; }
.card-value.purple { color: #7c3aed; }

.card-sub {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.55;
  color: var(--td-text-color-placeholder, #94a3b8);
}

.insight-card {
  min-height: 308px;
}

.insight-list {
  display: flex;
  flex-direction: column;
  flex: 1;
}

.insight-item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  padding: 14px 0;
  border-top: 1px solid var(--td-border-level-1-color, #edf2f7);
}

.insight-item:first-child {
  padding-top: 0;
  border-top: none;
}

.insight-copy {
  min-width: 0;
}

.insight-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--td-text-color-secondary, #111827);
}

.insight-desc {
  margin-top: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--td-text-color-placeholder, #64748b);
}

.insight-value {
  flex-shrink: 0;
  font-size: 14px;
  font-weight: 700;
  color: var(--td-text-color-primary, #111827);
  white-space: nowrap;
}

.insight-value.good { color: #16a34a; }
.insight-value.warn { color: #dc2626; }

.chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 278px;
  font-size: 13px;
  color: var(--td-text-color-placeholder, #94a3b8);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: var(--td-text-color-placeholder, #9ca3af);
}

.empty-state-sub {
  margin: 0;
  font-size: 12px;
}

@media (max-width: 1400px) {
  .metrics-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .operations-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .metrics-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .chart-card {
    min-height: 332px;
  }

  .chart-surface-large,
  .chart-empty {
    min-height: 248px;
  }

  .card-value {
    font-size: 28px;
  }
}

@media (max-width: 560px) {
  .operations-grid {
    grid-template-columns: 1fr;
  }

  .metrics-grid {
    grid-template-columns: 1fr;
  }

  .panel-head {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
