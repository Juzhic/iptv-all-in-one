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
        <t-button variant="outline" size="small" @click="reset3Days">最近3天</t-button>
        <t-button variant="outline" size="small" @click="resetAll">全部</t-button>
      </t-space>
    </t-card>

    <!-- 对比按钮 -->
    <div v-if="selectedRowKeys.length > 0" style="margin-bottom:8px">
      <t-space>
        <t-button theme="primary" size="small" :disabled="selectedRowKeys.length !== 2" @click="openCompare">
          对比选中 ({{ selectedRowKeys.length }}/2)
        </t-button>
        <t-button variant="outline" size="small" @click="selectedRowKeys = []">取消选择</t-button>
      </t-space>
    </div>

    <!-- 历史表格 -->
    <t-table
      :columns="columns"
      :data="historyRuns"
      :bordered="false"
      row-key="run_id"
      :expand-icon="true"
      :expanded-row-keys="expandedKeys"
      @expand-change="onExpandChange"
      :row-selection="{ selectedRowKeys, onChange: onSelectionChange }"
      size="small"
      :loading="loading"
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
        <div class="detail-panel" v-if="channelCache[row.run_id]">
          <div class="detail-toolbar">
            <t-input v-model="detailSearch[row.run_id]" placeholder="搜索频道名或 URL..." clearable style="width:240px" />
            <t-select v-model="detailFilter[row.run_id]" style="width:140px">
              <t-option value="all" label="全部频道" />
              <t-option value="pass" label="有通过的" />
              <t-option value="fail" label="全部失败的" />
            </t-select>
          </div>

          <div v-if="!filteredChannelCount(row.run_id)" class="empty-hint">暂无匹配频道</div>

          <div class="detail-summary" v-if="filteredChannelCount(row.run_id)">
            共 {{ getTotalChannels(row.run_id) }} 个频道，第 {{ detailPage[row.run_id] || 1 }}/{{ detailTotalPages(row.run_id) }} 页
          </div>

          <t-collapse expand-mutex v-if="filteredChannelCount(row.run_id)">
            <t-collapse-panel
              v-for="(name, idx) in paginatedChannelNames(row.run_id)"
              :key="name"
              :value="name"
            >
              <template #header>
                <div class="ch-header">
                  <div class="ch-name">
                    {{ name }}
                    <t-tag v-if="hasH265(paginatedChannelInfo(row.run_id, name))" size="small" variant="light" style="margin-left:6px" class="codec-tag-h265">H.265</t-tag>
                  </div>
                  <div class="ch-meta">
                    <t-tag
                      v-for="src in paginatedChannelInfo(row.run_id, name).sources"
                      :key="src"
                      :theme="platformTheme(src)"
                      size="small"
                      variant="light"
                      class="source-tag"
                    >{{ src }}</t-tag>
                    <t-tag :theme="paginatedChannelInfo(row.run_id, name).passed > 0 ? 'success' : 'danger'" size="small" variant="light">
                      {{ paginatedChannelInfo(row.run_id, name).passed }}/{{ paginatedChannelInfo(row.run_id, name).total }} 通过
                    </t-tag>
                    <span class="ch-rate">{{ ((paginatedChannelInfo(row.run_id, name).passed / paginatedChannelInfo(row.run_id, name).total) * 100).toFixed(1) }}%</span>
                  </div>
                </div>
              </template>
              <t-table
                :columns="urlColumns"
                :data="paginatedChannelInfo(row.run_id, name).urls || []"
                :bordered="false"
                size="small"
                row-key="url"
                :pagination="null"
              >
                <template #url="{ row: r }">
                  <div class="url-with-copy">
                    <t-popup :content="r.url" placement="top">
                      <span class="url-cell">{{ r.url }}</span>
                    </t-popup>
                    <t-button v-if="r.url" variant="text" size="small" class="copy-btn" @click.stop="copyText(r.url)">
                      <template #icon><t-icon name="copy" /></template>
                    </t-button>
                  </div>
                </template>
                <template #platform="{ row: r }">
                  <t-tag v-if="r.platform" :theme="platformTheme(r.platform)" size="small" variant="light">{{ r.platform }}</t-tag>
                  <span v-else>-</span>
                </template>
                <template #source_url="{ row: r }">
                  <t-popup v-if="r.source_url" :content="r.source_url" placement="top">
                    <span class="url-cell">{{ r.source_url }}</span>
                  </t-popup>
                  <span v-else>-</span>
                </template>
                <template #is_h265="{ row: r }">
                  <t-tag v-if="r.is_h265" class="codec-tag codec-tag-h265" size="small" variant="light">H.265</t-tag>
                  <t-tag v-else-if="r.codec" class="codec-tag codec-tag-codec" size="small" variant="light">{{ r.codec?.toUpperCase() }}</t-tag>
                  <span v-else>-</span>
                </template>
                <template #passed="{ row: r }">
                  <t-tag :theme="r.passed ? 'success' : 'danger'" size="small">{{ r.passed ? '通过' : '失败' }}</t-tag>
                </template>
                <template #connection_latency_ms="{ row: r }">
                  {{ r.connection_latency_ms != null ? Math.round(r.connection_latency_ms) + ' ms' : '-' }}
                </template>
                <template #quality_score="{ row: r }">
                  {{ r.quality_score != null ? Number(r.quality_score).toFixed(2) : '-' }}
                </template>
              </t-table>
            </t-collapse-panel>
          </t-collapse>

          <div class="detail-pagination" v-if="getTotalChannels(row.run_id) > DETAIL_PAGE_SIZE">
            <t-pagination
              :total="getTotalChannels(row.run_id)"
              :pageSize="DETAIL_PAGE_SIZE"
              :current="detailPage[row.run_id] || 1"
              :showPageSize="false"
              :showJumper="true"
              size="small"
              @current-change="(page) => onDetailPageChange(row.run_id, page)"
            />
          </div>
        </div>
        <div v-else style="padding:12px;color:var(--td-text-color-placeholder)">加载中...</div>
      </template>
    </t-table>

    <div v-if="!loading && !historyRuns.length" class="no-data">该日期范围内暂无测速记录</div>

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
      <LogPanel
        :entries="filteredLogs"
        :show-count="false"
        empty-text="暂无日志"
        @clear="logEntries = []"
      />
    </t-dialog>

    <!-- 对比弹窗 -->
    <t-dialog
      v-model:visible="compareVisible"
      header="测试结果对比"
      :footer="false"
      width="1200px"
      destroy-on-close
    >
      <div v-if="compareLoading" style="text-align:center;padding:40px;color:var(--td-text-color-placeholder)">加载中...</div>
      <div v-else-if="compareData">
        <!-- 顶部：两个 run 概览 -->
        <t-row :gutter="16" style="margin-bottom:16px">
          <t-col :span="6">
            <t-card size="small" header="A (基准)">
              <div style="font-size:13px;line-height:2">
                <div>时间：{{ compareData.run_a.finished_at }}</div>
                <div>通过率：{{ compareData.run_a.pass_rate }}%</div>
                <div>频道覆盖：{{ compareData.run_a.unique_channels_passed }}/{{ compareData.run_a.unique_channels_total }}</div>
                <div>耗时：{{ Math.round(compareData.run_a.duration_seconds / 60) }} 分钟</div>
              </div>
            </t-card>
          </t-col>
          <t-col :span="6">
            <t-card size="small" header="B (比较)">
              <div style="font-size:13px;line-height:2">
                <div>时间：{{ compareData.run_b.finished_at }}</div>
                <div>通过率：{{ compareData.run_b.pass_rate }}%</div>
                <div>频道覆盖：{{ compareData.run_b.unique_channels_passed }}/{{ compareData.run_b.unique_channels_total }}</div>
                <div>耗时：{{ Math.round(compareData.run_b.duration_seconds / 60) }} 分钟</div>
              </div>
            </t-card>
          </t-col>
        </t-row>

        <!-- 中间：delta 标签 -->
        <t-space :size="12" style="margin-bottom:16px">
          <t-tag theme="success" variant="light">改善 {{ compareData.summary.channels_improved }}</t-tag>
          <t-tag theme="danger" variant="light">退步 {{ compareData.summary.channels_regressed }}</t-tag>
          <t-tag theme="primary" variant="light">新增 {{ compareData.summary.new_channels }}</t-tag>
          <t-tag variant="light">消失 {{ compareData.summary.removed_channels }}</t-tag>
          <t-tag variant="outline">通过率 {{ fmtDelta(compareData.summary.pass_rate_delta, '%') }}</t-tag>
          <t-tag variant="outline">带宽 {{ fmtDelta(compareData.summary.avg_bandwidth_delta, ' MB/s') }}</t-tag>
          <t-tag variant="outline">延迟 {{ fmtDelta(compareData.summary.avg_latency_delta, ' ms') }}</t-tag>
        </t-space>

        <!-- 底部：频道级对比表 -->
        <t-table
          :columns="compareChannelColumns"
          :data="compareData.channels"
          :bordered="false"
          size="small"
          row-key="channel"
          :pagination="{ pageSize: 30 }"
          max-height="480"
        >
          <template #a_passed="{ row }">
            <t-tag v-if="row.a_passed != null" :theme="row.a_passed ? 'success' : 'danger'" size="small">{{ row.a_passed ? '是' : '否' }}</t-tag>
            <span v-else>-</span>
          </template>
          <template #b_passed="{ row }">
            <t-tag v-if="row.b_passed != null" :theme="row.b_passed ? 'success' : 'danger'" size="small">{{ row.b_passed ? '是' : '否' }}</t-tag>
            <span v-else>-</span>
          </template>
          <template #a_bandwidth="{ row }">{{ fmtNum(row.a_bandwidth, 2) }}</template>
          <template #b_bandwidth="{ row }">{{ fmtNum(row.b_bandwidth, 2) }}</template>
          <template #a_score="{ row }">{{ fmtNum(row.a_score) }}</template>
          <template #b_score="{ row }">{{ fmtNum(row.b_score) }}</template>
          <template #status="{ row }">
            <t-tag :theme="statusMap[row.status]?.theme || 'default'" size="small" variant="light">
              {{ statusMap[row.status]?.label || row.status }}
            </t-tag>
          </template>
        </t-table>
      </div>
    </t-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { apiGetRuns, apiGetRunChannels, apiDeleteRun, apiGetRunLogs, apiCompareRuns } from '../api.js'
import { useClipboard } from '../composables/useClipboard.js'
import { platformTheme } from '../utils/platform.js'
import { daysAgo as daysAgoUtil } from '../utils/date.js'
import LogPanel from './LogPanel.vue'

const { copyText: rawCopy } = useClipboard()
async function copyText(text) {
  await rawCopy(text)
  MessagePlugin.success('已复制')
}

const props = defineProps({ initialRuns: Array })
const emit = defineEmits(['update-overview'])

const historyRuns = ref([])
const loading = ref(false)
const startDate = ref('')
const endDate = ref('')
const expandedKeys = ref([])
const channelCache = reactive({})     // { [runId]: { channels, total_channels, page, page_size } }
const detailSearch = reactive({})
const detailFilter = reactive({})
const detailPage = reactive({})
const DETAIL_PAGE_SIZE = 20

// 日志弹窗
const logVisible = ref(false)
const logMeta = ref('')
const logEntries = ref([])
const logSearch = ref('')

// 对比弹窗
const selectedRowKeys = ref([])
const compareVisible = ref(false)
const compareLoading = ref(false)
const compareData = ref(null)

// 日期初始化
const now = new Date()
const fmt = (d) => {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
const daysAgo = (n) => new Date(now.getTime() - n * 86400000)
startDate.value = fmt(daysAgo(3))
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

const urlColumns = [
  { colKey: 'url', title: 'URL', width: 280, ellipsis: true },
  { colKey: 'platform', title: '扫描来源', width: 100 },
  { colKey: 'source_url', title: '订阅源', width: 200, ellipsis: true },
  { colKey: 'resolution', title: '分辨率', width: 100 },
  { colKey: 'bandwidth_MBps', title: '带宽(MB/s)', width: 100 },
  { colKey: 'connection_latency_ms', title: '延迟', width: 90 },
  { colKey: 'quality_score', title: '评分', width: 80 },
  { colKey: 'is_h265', title: '编码', width: 90 },
  { colKey: 'passed', title: '状态', width: 80 },
  { colKey: 'reason', title: '原因', width: 150, ellipsis: true },
]

async function queryHistory() {
  loading.value = true
  try {
    historyRuns.value = await apiGetRuns(startDate.value, endDate.value)
    emit('update-overview', historyRuns.value)
  } catch (e) { MessagePlugin.error('查询失败: ' + e.message) }
  finally { loading.value = false }
}

function reset3Days() {
  startDate.value = fmt(daysAgo(3))
  endDate.value = fmt(now)
  queryHistory()
}

function resetWeek() {
  startDate.value = fmt(daysAgo(7))
  endDate.value = fmt(now)
  queryHistory()
}

function resetAll() {
  startDate.value = ''
  endDate.value = ''
  queryHistory()
}

async function onExpandChange(keys, extra) {
  expandedKeys.value = keys
  const row = extra?.row
  const target = row || historyRuns.value.find(r => keys.includes(r.run_id) && !channelCache[r.run_id])
  if (!target) return
  if (keys.includes(target.run_id) && !channelCache[target.run_id]) {
    await loadChannelPage(target.run_id, 1)
  }
}

async function loadChannelPage(runId, page) {
  try {
    const data = await apiGetRunChannels(runId, page, DETAIL_PAGE_SIZE)
    // 服务端分页格式：{ channels: {}, total_channels, page, page_size }
    channelCache[runId] = data || {}
    detailSearch[runId] = detailSearch[runId] || ''
    detailFilter[runId] = detailFilter[runId] || 'all'
    detailPage[runId] = page
  } catch (e) { MessagePlugin.error('加载详情失败') }
}

function getChannelData(runId) {
  const cached = channelCache[runId]
  if (!cached) return {}
  // 兼容新格式 { channels, total_channels } 和旧格式（直接是频道字典）
  return cached.channels || cached
}

function getTotalChannels(runId) {
  const cached = channelCache[runId]
  if (!cached) return 0
  if (cached.total_channels != null) return cached.total_channels
  return Object.keys(cached).length
}

function hasH265(info) {
  return (info.urls || []).some(u => u.is_h265)
}

function filteredChannels(runId) {
  const q = (detailSearch[runId] || '').toLowerCase()
  const f = detailFilter[runId] || 'all'
  const src = getChannelData(runId)
  const result = {}
  for (const [name, info] of Object.entries(src)) {
    if (q && !name.toLowerCase().includes(q)) {
      const hasUrl = (info.urls || []).some(u => (u.url || '').toLowerCase().includes(q))
      if (!hasUrl) continue
    }
    if (f === 'pass' && info.passed === 0) continue
    if (f === 'fail' && info.passed > 0) continue
    result[name] = info
  }
  return result
}

function filteredChannelNames(runId) {
  return Object.keys(filteredChannels(runId))
}

function filteredChannelCount(runId) {
  return filteredChannelNames(runId).length
}

function detailTotalPages(runId) {
  return Math.max(1, Math.ceil(getTotalChannels(runId) / DETAIL_PAGE_SIZE))
}

// 服务端分页后，当前页频道已是分页结果，直接返回过滤后的名称
function paginatedChannelNames(runId) {
  return filteredChannelNames(runId)
}

function paginatedChannelInfo(runId, name) {
  const src = getChannelData(runId)
  return src[name] || { passed: 0, total: 0, sources: [], urls: [] }
}

// 切换页码时请求服务端
async function onDetailPageChange(runId, page) {
  detailPage[runId] = page
  await loadChannelPage(runId, page)
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

// ── 对比功能 ──
const compareChannelColumns = [
  { colKey: 'channel', title: '频道', width: 180, ellipsis: true },
  { colKey: 'a_passed', title: 'A通过', width: 70 },
  { colKey: 'b_passed', title: 'B通过', width: 70 },
  { colKey: 'a_bandwidth', title: 'A带宽', width: 90 },
  { colKey: 'b_bandwidth', title: 'B带宽', width: 90 },
  { colKey: 'a_score', title: 'A评分', width: 80 },
  { colKey: 'b_score', title: 'B评分', width: 80 },
  { colKey: 'status', title: '变化状态', width: 100 },
]

const statusMap = {
  improved: { label: '改善', theme: 'success' },
  regressed: { label: '退步', theme: 'danger' },
  new: { label: '新增', theme: 'primary' },
  removed: { label: '消失', theme: 'default' },
  stable: { label: '稳定', theme: 'default' },
}

function onSelectionChange(keys) {
  selectedRowKeys.value = keys
}

async function openCompare() {
  if (selectedRowKeys.value.length !== 2) return
  const [a, b] = selectedRowKeys.value
  compareVisible.value = true
  compareLoading.value = true
  compareData.value = null
  try {
    compareData.value = await apiCompareRuns(a, b)
  } catch (e) {
    MessagePlugin.error('对比失败: ' + e.message)
    compareVisible.value = false
  } finally {
    compareLoading.value = false
  }
}

function fmtNum(v, digits = 2) {
  if (v == null) return '-'
  return Number(v).toFixed(digits)
}

function fmtDelta(v, unit = '', digits = 2) {
  if (v == null) return '-'
  const n = Number(v)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(digits)}${unit}`
}

onMounted(() => {
  queryHistory()
})
</script>

<style scoped>
.history-tab { padding-top: 4px; }
.rate-cell { display: inline-flex; align-items: center; gap: 6px; }
.mini-bar { width: 60px; height: 6px; background: var(--td-border-level-1-color, #e5e7eb); border-radius: 3px; overflow: hidden; }
.mini-fill { height: 100%; border-radius: 3px; }
.detail-panel { padding: 12px 0; }
.detail-toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.no-data { text-align: center; padding: 40px; color: var(--td-text-color-placeholder); font-size: 13px; }
.codec-tag-h265 { background: var(--td-brand-color-light); color: var(--td-brand-color); }
.codec-tag-codec { background: var(--td-bg-color-component); color: var(--td-text-color-secondary); }
.ch-header { display: flex; align-items: center; justify-content: space-between; width: 100%; }
.ch-name { font-weight: 600; font-size: 14px; display: flex; align-items: center; }
.ch-meta { display: flex; align-items: center; gap: 8px; }
.ch-rate { font-size: 13px; color: var(--td-text-color-primary); }
.source-tag { font-size: 11px; }
.empty-hint { text-align: center; padding: 24px; color: var(--td-text-color-placeholder); font-size: 13px; }
.detail-summary { font-size: 12px; color: var(--td-text-color-placeholder); margin-bottom: 8px; }
.detail-pagination { display: flex; justify-content: center; margin-top: 12px; }
.url-cell { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--td-text-color-placeholder, #6b7280); font-family: monospace; cursor: pointer; }
.url-cell:hover { white-space: normal; word-break: break-all; }
.url-with-copy { display: inline-flex; align-items: center; gap: 4px; max-width: 100%; }
.copy-btn { flex-shrink: 0; opacity: 0; transition: opacity 0.15s; padding: 0 2px !important; min-width: auto !important; }
.url-with-copy:hover .copy-btn { opacity: 1; }
</style>
