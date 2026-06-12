<template>
  <div class="history-tab">
    <!-- 日期筛选 -->
    <t-card size="small" :bordered="false" style="margin-bottom:12px">
      <t-space>
        <t-date-picker v-model="startDate" placeholder="开始日期" clearable />
        <span style="color:var(--td-text-color-placeholder)">~</span>
        <t-date-picker v-model="endDate" placeholder="结束日期" clearable />
        <t-button theme="primary" size="small" @click="queryHistory">查询</t-button>
        <t-button variant="outline" size="small" @click="resetWeek">最近7天</t-button>
        <t-button variant="outline" size="small" @click="resetAll">全部</t-button>
      </t-space>
    </t-card>

    <!-- 历史表格 -->
    <t-table
      :columns="columns"
      :data="historyRuns"
      :bordered="false"
      row-key="run_id"
      :expand-icon="true"
      :expanded-row-keys="expandedKeys"
      @expand-change="onExpandChange"
      size="small"
    >
      <template #summary_pass_rate="{ row }">
        <div class="rate-cell">
          <span>{{ row.summary.pass_rate }}%</span>
          <div class="mini-bar">
            <div class="mini-fill" :style="{ width: row.summary.pass_rate + '%', background: row.summary.pass_rate >= 50 ? '#22c55e' : '#ef4444' }"></div>
          </div>
        </div>
      </template>
      <template #duration="{ row }">{{ Math.round(row.duration_seconds / 60) }} 分钟</template>
      <template #coverage="{ row }">{{ row.summary.unique_channels_passed }}/{{ row.summary.unique_channels_total }}</template>
      <template #actions="{ row }">
        <t-space :size="4">
          <t-button variant="outline" size="small" @click.stop="openLogModal(row.run_id)">日志</t-button>
          <t-button theme="danger" variant="outline" size="small" @click.stop="deleteRun(row.run_id)">删除</t-button>
        </t-space>
      </template>
      <template #expandedRow="{ row }">
        <div class="detail-panel" v-if="detailCache[row.run_id]">
          <t-input v-model="detailSearch[row.run_id]" placeholder="搜索频道名或 URL..." clearable style="width:240px;margin-bottom:8px" />
          <t-table
            :columns="detailColumns"
            :data="filteredDetail(row.run_id)"
            :bordered="false"
            size="small"
            row-key="url"
            :pagination="null"
          >
            <template #is_h265="{ row: r }">
              <t-tag v-if="r.is_h265" class="codec-tag codec-tag-h265" size="small" variant="light">H.265</t-tag>
              <t-tag v-else-if="r.codec" class="codec-tag codec-tag-codec" size="small" variant="light">{{ r.codec?.toUpperCase() }}</t-tag>
              <span v-else>-</span>
            </template>
            <template #passed="{ row: r }">
              <t-tag :theme="r.passed ? 'success' : 'danger'" size="small">{{ r.passed ? '通过' : '失败' }}</t-tag>
            </template>
          </t-table>
        </div>
        <div v-else style="padding:12px;color:var(--td-text-color-placeholder)">加载中...</div>
      </template>
    </t-table>

    <div v-if="!historyRuns.length" class="no-data">该日期范围内暂无测速记录</div>

    <!-- 日志弹窗 -->
    <t-dialog
      v-model:visible="logVisible"
      header="运行日志"
      :footer="false"
      width="1100px"
      destroy-on-close
    >
      <template #header>
        <div>
          <div style="font-size:16px;font-weight:600">运行日志</div>
          <div style="font-size:12px;color:var(--td-text-color-placeholder);margin-top:4px">{{ logMeta }}</div>
        </div>
      </template>
      <t-space style="margin-bottom:8px">
        <t-input v-model="logSearch" placeholder="搜索日志内容..." clearable style="width:300px" />
        <span style="font-size:12px;color:var(--td-text-color-placeholder)">{{ logEntries.length }} 条</span>
      </t-space>
      <div class="log-panel">
        <div v-for="(l, i) in filteredLogs" :key="i" class="log-line">
          <span class="log-time">[{{ l.ts }}]</span>
          <span :class="logClass(l)">[{{ l.level === 'ERROR' ? 'ERROR' : l.level === 'WARNING' ? 'WARN' : 'INFO' }}]</span>
          <span :class="logMsgClass(l)">{{ l.message }}</span>
        </div>
        <div v-if="!filteredLogs.length" style="color:var(--td-text-color-placeholder);padding:8px">暂无日志</div>
      </div>
    </t-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { apiGetRuns, apiGetRun, apiDeleteRun, apiGetRunLogs } from '../api.js'

const props = defineProps({ initialRuns: Array })
const emit = defineEmits(['update-overview'])

const historyRuns = ref(props.initialRuns || [])
const startDate = ref('')
const endDate = ref('')
const expandedKeys = ref([])
const detailCache = reactive({})
const detailSearch = reactive({})

// 日志弹窗
const logVisible = ref(false)
const logMeta = ref('')
const logEntries = ref([])
const logSearch = ref('')

// 日期初始化
const now = new Date()
const weekAgo = new Date(now - 7 * 86400000)
const fmt = (d) => {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
startDate.value = fmt(weekAgo)
endDate.value = fmt(now)

const columns = [
  { colKey: 'finished_at', title: '执行时间', width: 180 },
  { colKey: 'summary.total_tested', title: '测试数', width: 80 },
  { colKey: 'summary.total_passed', title: '通过数', width: 80 },
  { colKey: 'summary.total_failed', title: '失败数', width: 80 },
  { colKey: 'summary_pass_rate', title: '通过率', width: 140 },
  { colKey: 'coverage', title: '频道覆盖', width: 100 },
  { colKey: 'duration', title: '耗时', width: 100 },
  { colKey: 'actions', title: '操作', width: 140, fixed: 'right' },
]

const detailColumns = [
  { colKey: 'channel', title: '频道', width: 120 },
  { colKey: 'url', title: 'URL', width: 280, ellipsis: true },
  { colKey: 'resolution', title: '分辨率', width: 100 },
  { colKey: 'bandwidth_MBps', title: '带宽(MB/s)', width: 100 },
  { colKey: 'connection_latency_ms', title: '延迟', width: 90 },
  { colKey: 'quality_score', title: '评分', width: 80 },
  { colKey: 'is_h265', title: '编码', width: 90 },
  { colKey: 'sample_seconds', title: '采样(秒)', width: 80 },
  { colKey: 'cost_seconds', title: '耗时(秒)', width: 80 },
  { colKey: 'passed', title: '状态', width: 80 },
  { colKey: 'reason', title: '原因', width: 150, ellipsis: true },
]

async function queryHistory() {
  try {
    historyRuns.value = await apiGetRuns(startDate.value, endDate.value)
    emit('update-overview', historyRuns.value)
  } catch (e) { MessagePlugin.error('查询失败: ' + e.message) }
}

function resetWeek() {
  startDate.value = fmt(weekAgo)
  endDate.value = fmt(now)
  queryHistory()
}

function resetAll() {
  startDate.value = ''
  endDate.value = ''
  queryHistory()
}

async function onExpandChange(keys, extra) {
  const row = extra?.row
  // 当 extra 或 row 缺失时，回退到 historyRuns 中查找新展开的 run
  const target = row || historyRuns.value.find(r => keys.includes(r.run_id) && !detailCache[r.run_id])
  if (!target) return
  if (keys.includes(target.run_id) && !detailCache[target.run_id]) {
    try {
      const data = await apiGetRun(target.run_id)
      detailCache[target.run_id] = data.results || []
      detailSearch[target.run_id] = ''
    } catch (e) { MessagePlugin.error('加载详情失败') }
  }
}

function filteredDetail(runId) {
  const q = (detailSearch[runId] || '').toLowerCase()
  const all = detailCache[runId] || []
  if (!q) return all
  return all.filter(r => (r.channel || '').toLowerCase().includes(q) || (r.url || '').toLowerCase().includes(q))
}

async function deleteRun(runId) {
  const confirmDialog = DialogPlugin.confirm({
    header: '删除测速记录',
    body: '删除后该轮次及其日志将永久移除，无法恢复。确认删除？',
    theme: 'warning',
    confirmBtn: { content: '删除', theme: 'danger' },
    onConfirm: async () => {
      try {
        await apiDeleteRun(runId)
        historyRuns.value = historyRuns.value.filter(r => r.run_id !== runId)
        emit('update-overview', historyRuns.value)
        MessagePlugin.success('已删除')
      } catch (e) { MessagePlugin.error('删除失败: ' + e.message) }
      confirmDialog.hide()
    },
  })
}

async function openLogModal(runId) {
  logVisible.value = true
  logMeta.value = '加载中...'
  logEntries.value = []
  logSearch.value = ''
  try {
    const run = historyRuns.value.find(r => r.run_id === runId)
    if (run) logMeta.value = `${run.finished_at} | 通过率 ${run.summary.pass_rate}% | ${run.summary.total_passed}/${run.summary.total_tested}`
    const payload = await apiGetRunLogs(runId)
    logEntries.value = Array.isArray(payload) ? payload : (payload.logs || [])
  } catch (e) { logMeta.value = '加载失败' }
}

const filteredLogs = computed(() => {
  const q = logSearch.value.toLowerCase()
  if (!q) return logEntries.value
  return logEntries.value.filter(l => ((l.ts || '') + ' ' + (l.level || '') + ' ' + (l.message || '')).toLowerCase().includes(q))
})

function logClass(l) { return l.level === 'ERROR' ? 'log-level-error' : l.level === 'WARNING' ? 'log-level-warn' : 'log-level-info' }
function logMsgClass(l) {
  if (/失败|异常|error/i.test(l.message || '')) return 'log-msg-fail'
  if (/通过|完成|pass/i.test(l.message || '')) return 'log-msg-pass'
  return 'log-msg-info'
}

onMounted(() => {
  if (!historyRuns.value.length) queryHistory()
})
</script>

<style scoped>
.history-tab { padding-top: 4px; }
.rate-cell { display: inline-flex; align-items: center; gap: 6px; }
.mini-bar { width: 60px; height: 6px; background: var(--td-border-level-1-color, #e5e7eb); border-radius: 3px; overflow: hidden; }
.mini-fill { height: 100%; border-radius: 3px; }
.detail-panel { padding: 12px 0; }
.no-data { text-align: center; padding: 40px; color: var(--td-text-color-placeholder); font-size: 13px; }
.log-panel { background: #1e1e2e; color: #cdd6f4; font-family: 'Cascadia Code','Fira Code',Consolas,monospace; font-size: 12px; line-height: 1.7; height: 500px; overflow-y: auto; border-radius: 8px; padding: 12px; }
.log-line { white-space: pre-wrap; word-break: break-all; }
.log-time { color: #89b4fa; margin-right: 8px; }
.log-level-error { color: #f38ba8; }
.log-level-warn { color: #f59e0b; }
.log-level-info { color: #cba6f7; margin-right: 4px; }
.log-msg-fail { color: #f38ba8; }
.log-msg-pass { color: #a6e3a1; }
.log-msg-info { color: #cdd6f4; }
.codec-tag-h265 { background: var(--td-brand-color-light); color: var(--td-brand-color); }
.codec-tag-codec { background: var(--td-bg-color-component); color: var(--td-text-color-secondary); }
</style>
