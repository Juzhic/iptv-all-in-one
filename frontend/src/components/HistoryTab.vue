<template>
  <div class="history-tab">
    <!-- 日期筛选 -->
    <t-card size="small" :bordered="false" class="panel-card history-filter-card">
      <div class="section-header">
        <div>
          <div class="section-title">历史记录</div>
          <p class="section-subtitle">按日期筛选测速轮次，展开记录可继续查看频道和地址明细。</p>
        </div>
      </div>
      <div class="filter-toolbar">
        <t-date-picker v-model="startDate" placeholder="开始日期" clearable class="date-filter" />
        <span class="date-separator">~</span>
        <t-date-picker v-model="endDate" placeholder="结束日期" clearable class="date-filter" />
        <t-input v-model="historySearch" placeholder="搜索轮次或状态" clearable class="history-search" @enter="queryHistory" />
        <t-select v-model="historySort" class="history-sort" @change="queryHistory">
          <t-option value="finished_at" label="按完成时间" />
          <t-option value="pass_rate" label="按通过率" />
          <t-option value="duration_seconds" label="按耗时" />
        </t-select>
        <t-select v-model="historySortOrder" class="history-order" @change="queryHistory">
          <t-option value="desc" label="降序" />
          <t-option value="asc" label="升序" />
        </t-select>
        <div class="filter-actions">
          <t-button theme="primary" size="small" @click="queryHistory">查询</t-button>
          <t-button variant="outline" size="small" @click="resetWeek">最近7天</t-button>
          <t-button variant="outline" size="small" @click="reset3Days">最近3天</t-button>
          <t-button variant="outline" size="small" @click="resetAll">全部</t-button>
        </div>
      </div>
    </t-card>

    <!-- 对比按钮 -->
    <div v-if="selectedRowKeys.length > 0" class="selection-toolbar">
      <div class="selection-actions">
        <t-button theme="primary" size="small" :disabled="selectedRowKeys.length !== 2" @click="openCompare">
          对比选中 ({{ selectedRowKeys.length }}/2)
        </t-button>
        <t-button variant="outline" size="small" @click="selectedRowKeys = []">取消选择</t-button>
      </div>
    </div>

    <!-- 历史表格 -->
    <AsyncState
      :loading="loading"
      :error="historyError"
      :empty="!historyRuns.length"
      empty-title="该日期范围内暂无测速记录"
      :retry="queryHistory"
    >
    <div class="table-scroll-shell history-table-shell">
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
            <t-input
              v-model="detailSearch[row.run_id]"
              placeholder="搜索频道名或 URL..."
              clearable
              class="detail-search"
              @enter="onDetailFiltersChange(row.run_id)"
              @clear="onDetailFiltersChange(row.run_id)"
            />
            <t-select v-model="detailFilter[row.run_id]" class="detail-filter" @change="onDetailFiltersChange(row.run_id)">
              <t-option value="all" label="全部频道" />
              <t-option value="pass" label="有通过的" />
              <t-option value="fail" label="全部失败的" />
            </t-select>
          </div>

          <div v-if="!filteredChannelCount(row.run_id)" class="empty-hint">暂无匹配频道</div>

          <div class="detail-summary" v-if="filteredChannelCount(row.run_id)">
            共 {{ getTotalChannels(row.run_id) }} 个频道，第 {{ detailPage[row.run_id] || 1 }}/{{ detailTotalPages(row.run_id) }} 页
          </div>

          <t-collapse v-model="detailExpandState[row.run_id]" v-if="filteredChannelCount(row.run_id)">
            <t-collapse-panel
              v-for="{ name, info: ch } in paginatedChannelEntries(row.run_id)"
              :key="name"
              :value="name"
            >
              <template #header>
                <div class="ch-header">
                  <div class="ch-name">
                    {{ name }}
                    <t-tag v-if="hasH265(ch)" size="small" variant="light" class="codec-tag-h265 codec-tag-inline">H.265</t-tag>
                  </div>
                  <div class="ch-meta">
                    <t-tag
                      v-for="src in ch.sources"
                      :key="src"
                      :theme="platformTheme(src)"
                      size="small"
                      variant="light"
                      class="source-tag"
                    >{{ src }}</t-tag>
                    <t-tag :theme="ch.passed > 0 ? 'success' : 'danger'" size="small" variant="light">
                      {{ ch.passed }}/{{ ch.total }} 通过
                    </t-tag>
                    <span class="ch-rate">{{ ch.total > 0 ? ((ch.passed / ch.total) * 100).toFixed(1) : '0.0' }}%</span>
                  </div>
                </div>
              </template>
              <div class="table-scroll-shell detail-table-shell">
                <t-table
                  :columns="urlColumns"
                  :data="ch.urls || []"
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
                      <template #icon><CopyIcon /></template>
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
              </div>
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
        <div v-else class="detail-loading">加载中...</div>
      </template>
      </t-table>
    </div>
    <t-pagination
      v-if="historyTotal > historyPageSize"
      class="history-pagination"
      :total="historyTotal"
      :current="historyPage"
      :page-size="historyPageSize"
      :show-page-size="false"
      show-jumper
      @current-change="onHistoryPageChange"
    />
    </AsyncState>

    <!-- 日志弹窗 -->
    <t-dialog
      v-model:visible="logVisible"
      header="运行日志"
      :footer="false"
      width="1100px"
      destroy-on-close
    >
      <template #header>
        <div class="dialog-heading">
          <div class="dialog-title">运行日志</div>
          <div class="dialog-subtitle">{{ logMeta }}</div>
        </div>
      </template>
      <div class="log-dialog-toolbar">
        <t-input v-model="logSearch" placeholder="搜索日志内容..." clearable class="log-search" />
        <span class="toolbar-count">{{ logEntries.length }} 条</span>
      </div>
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
      <div v-if="compareLoading" class="compare-loading">加载中...</div>
      <div v-else-if="compareData">
        <!-- 顶部：两个 run 概览 -->
        <t-row :gutter="[16, 16]" class="compare-summary-row">
          <t-col :xs="12" :sm="6">
            <t-card size="small" header="A (基准)">
              <div class="compare-summary-copy">
                <div>时间：{{ compareData.run_a.finished_at }}</div>
                <div>通过率：{{ compareData.run_a.pass_rate }}%</div>
                <div>频道覆盖：{{ compareData.run_a.unique_channels_passed }}/{{ compareData.run_a.unique_channels_total }}</div>
                <div>耗时：{{ Math.round(compareData.run_a.duration_seconds / 60) }} 分钟</div>
              </div>
            </t-card>
          </t-col>
          <t-col :xs="12" :sm="6">
            <t-card size="small" header="B (比较)">
              <div class="compare-summary-copy">
                <div>时间：{{ compareData.run_b.finished_at }}</div>
                <div>通过率：{{ compareData.run_b.pass_rate }}%</div>
                <div>频道覆盖：{{ compareData.run_b.unique_channels_passed }}/{{ compareData.run_b.unique_channels_total }}</div>
                <div>耗时：{{ Math.round(compareData.run_b.duration_seconds / 60) }} 分钟</div>
              </div>
            </t-card>
          </t-col>
        </t-row>

        <!-- 中间：delta 标签 -->
        <div class="compare-delta-toolbar">
          <t-tag theme="success" variant="light">改善 {{ compareData.summary.channels_improved }}</t-tag>
          <t-tag theme="danger" variant="light">退步 {{ compareData.summary.channels_regressed }}</t-tag>
          <t-tag theme="primary" variant="light">新增 {{ compareData.summary.new_channels }}</t-tag>
          <t-tag variant="light">消失 {{ compareData.summary.removed_channels }}</t-tag>
          <t-tag variant="outline">通过率 {{ fmtDelta(compareData.summary.pass_rate_delta, '%') }}</t-tag>
          <t-tag variant="outline">带宽 {{ fmtDelta(compareData.summary.avg_bandwidth_delta, ' MB/s') }}</t-tag>
          <t-tag variant="outline">延迟 {{ fmtDelta(compareData.summary.avg_latency_delta, ' ms') }}</t-tag>
        </div>

        <!-- 底部：频道级对比表 -->
        <div class="table-scroll-shell compare-table-shell">
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
      </div>
    </t-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next/es/message/index.mjs'
import { DialogPlugin } from 'tdesign-vue-next/es/dialog/index.mjs'
import CopyIcon from 'tdesign-icons-vue-next/esm/components/copy.js'
import { apiGetRuns, apiGetRunChannels, apiDeleteRun, apiGetRunLogs, apiCompareRuns } from '../api.js'
import { useClipboard } from '../composables/useClipboard.js'
import { platformTheme } from '../utils/platform.js'
import LogPanel from './LogPanel.vue'
import AsyncState from './AsyncState.vue'

const { copyText: rawCopy } = useClipboard()
async function copyText(text) {
  await rawCopy(text)
  MessagePlugin.success('已复制')
}

const historyRuns = ref([])
const loading = ref(false)
const historyError = ref('')
const historySearch = ref('')
const historySort = ref('finished_at')
const historySortOrder = ref('desc')
const historyPage = ref(1)
const historyPageSize = ref(30)
const historyTotal = ref(0)
const startDate = ref('')
const endDate = ref('')
const expandedKeys = ref([])
const channelCache = reactive({})     // { [runId]: { channels, total_channels, page, page_size } }
const detailSearch = reactive({})
const detailFilter = reactive({})
const detailPage = reactive({})
const detailExpandState = reactive({})  // { [runId]: string[] } 折叠面板展开状态
const channelPageSeq = reactive({})     // { [runId]: number } 分页请求序列号
const DETAIL_PAGE_SIZE = 20
let querySeq = 0

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
const fmt = (d) => {
  const year = d.getFullYear()
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
const daysAgo = (n) => { const d = new Date(); d.setDate(d.getDate() - n); return d }
const today = new Date()
startDate.value = fmt(daysAgo(3))
endDate.value = fmt(today)

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
  const seq = ++querySeq
  loading.value = true
  historyError.value = ''
  historyRuns.value = []
  expandedKeys.value = []
  selectedRowKeys.value = []
  Object.keys(channelCache).forEach(key => delete channelCache[key])
  try {
    const data = await apiGetRuns(startDate.value, endDate.value, {
      search: historySearch.value.trim(),
      sort_by: historySort.value,
      sort_order: historySortOrder.value,
      page: historyPage.value,
      size: historyPageSize.value,
    })
    if (seq !== querySeq) return
    const runs = Array.isArray(data) ? data : (data?.items || [])
    historyRuns.value = runs
    historyTotal.value = Array.isArray(data) ? data.length : Number(data?.total || runs.length)
  } catch (e) {
    if (seq === querySeq) historyError.value = e?.message || '查询历史记录失败'
  } finally {
    if (seq === querySeq) loading.value = false
  }
}

function onHistoryPageChange(page) {
  historyPage.value = page
  queryHistory()
}

function reset3Days() {
  startDate.value = fmt(daysAgo(3))
  endDate.value = fmt(today)
  queryHistory()
}

function resetWeek() {
  startDate.value = fmt(daysAgo(7))
  endDate.value = fmt(today)
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
  const seq = (channelPageSeq[runId] || 0) + 1
  channelPageSeq[runId] = seq
  try {
    const filter = detailFilter[runId] || 'all'
    const data = await apiGetRunChannels(runId, page, DETAIL_PAGE_SIZE, {
      search: (detailSearch[runId] || '').trim(),
      status: filter === 'all' ? '' : filter,
    })
    if (channelPageSeq[runId] !== seq) return  // 过期请求丢弃
    // 服务端分页格式：{ channels: {}, total_channels, page, page_size }
    channelCache[runId] = data || {}
    detailSearch[runId] = detailSearch[runId] || ''
    detailFilter[runId] = detailFilter[runId] || 'all'
    detailPage[runId] = page
  } catch (e) { MessagePlugin.error('加载详情失败') }
}

function onDetailFiltersChange(runId) {
  detailPage[runId] = 1
  detailExpandState[runId] = []
  loadChannelPage(runId, 1)
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

function paginatedChannelEntries(runId) {
  const src = getChannelData(runId)
  return paginatedChannelNames(runId).map(name => ({
    name,
    info: src[name] || { passed: 0, total: 0, sources: [], urls: [] },
  }))
}

function paginatedChannelInfo(runId, name) {
  const src = getChannelData(runId)
  return src[name] || { passed: 0, total: 0, sources: [], urls: [] }
}

// 切换页码时请求服务端
async function onDetailPageChange(runId, page) {
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
        historyTotal.value = Math.max(0, historyTotal.value - 1)
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
.history-tab {
  padding-top: 4px;
}

.panel-card {
  margin-bottom: 16px;
  border: 1px solid var(--td-border-level-1-color, #e5e7eb);
  border-radius: 12px;
  background: var(--td-bg-color-container, #ffffff);
  box-shadow: none;
}

.section-header {
  margin-bottom: 14px;
}

.section-title {
  color: var(--td-text-color-primary, #111827);
  font-size: 16px;
  font-weight: 600;
}

.section-subtitle {
  margin: 4px 0 0;
  color: var(--td-text-color-placeholder, #6b7280);
  font-size: 12px;
  line-height: 1.6;
}

.filter-toolbar,
.filter-actions,
.selection-actions,
.detail-toolbar,
.log-dialog-toolbar,
.compare-delta-toolbar {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}

.date-filter {
  width: 200px;
  max-width: 100%;
}

.history-search {
  width: 190px;
  max-width: 100%;
}

.history-sort {
  width: 140px;
}

.history-order {
  width: 90px;
}

.history-pagination {
  margin-top: 12px;
  justify-content: flex-end;
}

.date-separator {
  color: var(--td-text-color-placeholder, #6b7280);
}

.selection-toolbar {
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid color-mix(in srgb, var(--td-brand-color, #366ef4) 22%, transparent);
  border-radius: 10px;
  background: color-mix(in srgb, var(--td-brand-color-1, #edf3ff) 72%, transparent);
}

.table-scroll-shell {
  max-width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.history-table-shell {
  border: 1px solid var(--td-border-level-1-color, #e5e7eb);
  border-radius: 12px;
  background: var(--td-bg-color-container, #ffffff);
}

.history-table-shell :deep(.t-table) {
  min-width: 920px;
}

.rate-cell {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.mini-bar {
  width: 60px;
  height: 6px;
  overflow: hidden;
  border-radius: 3px;
  background: var(--td-border-level-1-color, #e5e7eb);
}

.mini-fill {
  height: 100%;
  border-radius: 3px;
}

.detail-panel {
  padding: 14px 4px;
}

.detail-toolbar {
  margin-bottom: 12px;
}

.detail-search {
  width: 260px;
  max-width: 100%;
}

.detail-filter {
  width: 150px;
  max-width: 100%;
}

.detail-table-shell {
  border-radius: 8px;
}

.detail-table-shell :deep(.t-table) {
  min-width: 1080px;
}

.detail-loading,
.no-data,
.empty-hint,
.compare-loading {
  color: var(--td-text-color-placeholder, #6b7280);
  font-size: 13px;
  text-align: center;
}

.detail-loading {
  padding: 12px;
}

.no-data,
.compare-loading {
  padding: 40px 20px;
}

.empty-hint {
  padding: 24px;
}

.codec-tag-h265 {
  background: var(--td-brand-color-light);
  color: var(--td-brand-color);
}

.codec-tag-codec {
  background: var(--td-bg-color-component);
  color: var(--td-text-color-secondary);
}

.codec-tag-inline {
  margin-left: 6px;
}

.ch-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  min-width: 0;
}

.ch-name {
  display: flex;
  align-items: center;
  min-width: 0;
  font-size: 14px;
  font-weight: 600;
}

.ch-meta {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
}

.ch-rate {
  color: var(--td-text-color-primary);
  font-size: 13px;
}

.source-tag {
  font-size: 11px;
}

.detail-summary {
  margin-bottom: 8px;
  color: var(--td-text-color-placeholder);
  font-size: 12px;
}

.detail-pagination {
  display: flex;
  justify-content: center;
  max-width: 100%;
  margin-top: 12px;
  overflow-x: auto;
}

.dialog-title {
  color: var(--td-text-color-primary, #111827);
  font-size: 16px;
  font-weight: 600;
}

.dialog-subtitle {
  margin-top: 4px;
  color: var(--td-text-color-placeholder, #6b7280);
  font-size: 12px;
}

.log-dialog-toolbar {
  margin-bottom: 10px;
}

.log-search {
  width: 320px;
  max-width: 100%;
}

.toolbar-count {
  color: var(--td-text-color-placeholder, #6b7280);
  font-size: 12px;
}

.compare-summary-row,
.compare-delta-toolbar {
  margin-bottom: 16px;
}

.compare-summary-copy {
  font-size: 13px;
  line-height: 2;
}

.compare-table-shell :deep(.t-table) {
  min-width: 960px;
}

.url-cell {
  display: inline-block;
  max-width: 260px;
  overflow: hidden;
  color: var(--td-text-color-placeholder, #6b7280);
  font-family: monospace;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
}

.url-with-copy {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
  min-width: 0;
}

.copy-btn {
  min-width: auto !important;
  flex-shrink: 0;
  padding: 0 2px !important;
  opacity: 0;
  transition: opacity 0.15s;
}

.url-with-copy:hover .copy-btn,
.copy-btn:focus-visible {
  opacity: 1;
}

@media (hover: none), (pointer: coarse) {
  .copy-btn {
    opacity: 1;
  }
}

@media (max-width: 768px) {
  .filter-toolbar,
  .detail-toolbar,
  .log-dialog-toolbar {
    align-items: stretch;
  }

  .date-filter,
  .detail-search,
  .detail-filter,
  .log-search {
    width: 100%;
  }

  .date-separator {
    display: none;
  }

  .filter-actions,
  .selection-actions {
    width: 100%;
  }

  .filter-actions :deep(.t-button),
  .selection-actions :deep(.t-button) {
    flex: 1 1 120px;
  }

  .ch-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .ch-meta {
    justify-content: flex-start;
  }

  .codec-tag-inline {
    margin-left: 4px;
  }
}
</style>
