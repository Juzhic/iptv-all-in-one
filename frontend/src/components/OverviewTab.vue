<template>
  <div v-if="latest" class="overview-tab">
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
            <span class="panel-badge">最新 {{ latest.summary?.total_tested || 0 }} 条</span>
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
                  通过 {{ run.summary.total_passed }}/{{ run.summary.total_tested }}，
                  频道覆盖 {{ getCoverage(run.summary).toFixed(1) }}%
                </div>
              </div>
              <div class="insight-value warn">{{ run.summary.pass_rate }}%</div>
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

const chartData = computed(() => (props.runs || []).slice())
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
  .metrics-grid {
    grid-template-columns: 1fr;
  }

  .panel-head {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
