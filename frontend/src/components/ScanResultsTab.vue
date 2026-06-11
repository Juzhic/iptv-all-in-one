<template>
  <div class="scan-results-tab">
    <!-- 视图切换 -->
    <div class="view-tabs-row">
      <t-tabs v-model="viewMode" theme="normal" size="small" :destroy-on-hide="false">
        <t-tab-panel value="grouped" label="按来源分组" />
        <t-tab-panel value="legacy" label="按扫描记录" />
      </t-tabs>
      <t-button v-if="viewMode === 'grouped'" variant="outline" size="small" :loading="manualChecking" @click="triggerManualCheck">
        手动检测一轮
      </t-button>
    </div>

    <!-- ==================== 按来源分组视图 ==================== -->
    <template v-if="viewMode === 'grouped'">
      <!-- 统计概览 -->
      <div v-if="persistentStats.total" class="stats-bar">
        <t-tag theme="default" variant="light">总计 {{ persistentStats.total }}</t-tag>
        <t-tag theme="success" variant="light" v-if="persistentStats.good">好 {{ persistentStats.good }}</t-tag>
        <t-tag theme="warning" variant="light" v-if="persistentStats.poor">差 {{ persistentStats.poor }}</t-tag>
        <t-tag theme="danger" variant="light" v-if="persistentStats.unreachable">不可达 {{ persistentStats.unreachable }}</t-tag>
        <t-tag theme="primary" variant="light" v-if="persistentStats.pending">待检测 {{ persistentStats.pending }}</t-tag>
      </div>

      <!-- 详情视图（点击某 IP 后） -->
      <template v-if="detailView">
        <div class="detail-header">
          <t-button variant="text" size="small" @click="backToGrouped">← 返回分组</t-button>
          <span class="detail-title">{{ detailSourceIp }}</span>
          <t-space>
            <t-button variant="outline" size="small" @click="selectAllDetail">全选/取消</t-button>
            <t-button theme="primary" size="small" @click="exportDetailM3U">导出 M3U</t-button>
          </t-space>
        </div>
        <t-table
          :columns="detailColumns"
          :data="detailData"
          :bordered="false"
          row-key="id"
          size="small"
          :selected-row-keys="selectedDetailKeys"
          @select-change="(keys) => selectedDetailKeys = keys"
          :pagination="detailPagination"
          @page-change="onDetailPageChange"
        >
          <template #stability="{ row }">
            <div class="stability-cell">
              <div class="stability-track">
                <div class="stability-fill" :class="stabilityClass(row.stability)" :style="{ width: (row.stability || 0) + '%' }"></div>
              </div>
              <span style="font-size:11px;color:var(--td-text-color-placeholder)">{{ Math.round(row.stability || 0) }}%</span>
            </div>
          </template>
          <template #delay="{ row }">{{ row.delay != null ? Math.round(row.delay) + ' ms' : '-' }}</template>
          <template #bandwidth="{ row }">{{ row.bandwidth != null ? Math.round(row.bandwidth) + ' KB/s' : '-' }}</template>
          <template #quality_status="{ row }">
            <t-tag :theme="qualityTheme(row.quality_status)" size="small" variant="light">{{ qualityLabel(row.quality_status) }}</t-tag>
          </template>
        </t-table>
      </template>

      <!-- 分组视图（默认） -->
      <template v-else>
        <t-skeleton :loading="groupedLoading" :row-col="[{ width: '100%' }, { width: '100%' }, { width: '100%' }]">
          <t-collapse v-if="groupedData.length" v-model="expandedPlatforms">
            <t-collapse-panel
              v-for="plat in groupedData"
              :key="plat.platform"
              :value="plat.platform"
              :header="platformLabel(plat.platform)"
              :disabled="false"
            >
              <template #headerRightContent>
                <t-space :size="8">
                  <t-tag size="small" variant="light">{{ plat.source_count }} 来源</t-tag>
                  <t-tag size="small" variant="light" theme="primary">{{ plat.channel_count }} 频道</t-tag>
                  <t-tag size="small" variant="light">稳定性 {{ plat.avg_stability }}%</t-tag>
                </t-space>
              </template>
              <t-table
                :columns="sourceColumns"
                :data="plat.sources"
                :bordered="false"
                row-key="source_ip"
                size="small"
                :pagination="null"
                @row-click="({ row }) => openSourceDetail(row.source_ip)"
              >
                <template #avg_stability="{ row }">
                  <div class="stability-cell">
                    <div class="stability-track">
                      <div class="stability-fill" :class="stabilityClass(row.avg_stability)" :style="{ width: (row.avg_stability || 0) + '%' }"></div>
                    </div>
                    <span style="font-size:11px;color:var(--td-text-color-placeholder)">{{ Math.round(row.avg_stability || 0) }}%</span>
                  </div>
                </template>
                <template #avg_delay="{ row }">{{ row.avg_delay != null ? Math.round(row.avg_delay) + ' ms' : '-' }}</template>
                <template #avg_bandwidth="{ row }">{{ row.avg_bandwidth != null ? Math.round(row.avg_bandwidth) + ' KB/s' : '-' }}</template>
                <template #quality_dist="{ row }">
                  <t-space :size="4">
                    <t-tag v-if="row.good_count" theme="success" size="small" variant="light">{{ row.good_count }}好</t-tag>
                    <t-tag v-if="row.poor_count" theme="warning" size="small" variant="light">{{ row.poor_count }}差</t-tag>
                    <t-tag v-if="row.unreachable_count" theme="danger" size="small" variant="light">{{ row.unreachable_count }}不可达</t-tag>
                    <t-tag v-if="row.pending_count" theme="primary" size="small" variant="light">{{ row.pending_count }}待检</t-tag>
                  </t-space>
                </template>
                <template #first_seen="{ row }">{{ formatDate(row.first_seen) }}</template>
                <template #last_updated="{ row }">{{ formatDate(row.last_updated) }}</template>
              </t-table>
            </t-collapse-panel>
          </t-collapse>
          <t-empty v-else-if="!groupedLoading" description="暂无持久化扫描结果" />
        </t-skeleton>
      </template>
    </template>

    <!-- ==================== 按扫描记录视图（原功能） ==================== -->
    <template v-else>
      <t-space style="margin-bottom:12px;flex-wrap:wrap">
        <t-select v-model="selectedScanId" placeholder="选择扫描记录..." clearable style="width:220px" @change="reloadResults">
          <t-option value="" label="全部扫描记录" />
          <t-option v-for="r in scanHistory" :key="r.scan_id || r.id" :value="r.scan_id || r.id" :label="formatScanOptionLabel(r)" />
        </t-select>
        <t-select v-model="categoryFilter" placeholder="全部分类" clearable style="width:140px" @change="reloadResults">
          <t-option value="" label="全部分类" />
          <t-option v-for="c in categories" :key="c" :value="c" :label="c" />
        </t-select>
        <t-select v-model="provinceFilter" placeholder="全部省份" clearable style="width:140px" @change="reloadResults">
          <t-option value="" label="全部省份" />
          <t-option v-for="p in provinces" :key="p" :value="p" :label="p" />
        </t-select>
        <t-input v-model="searchQuery" placeholder="搜索频道名..." clearable style="width:200px" />
      </t-space>
      <t-space style="margin-bottom:12px">
        <t-button variant="outline" size="small" @click="selectAllLegacy">全选/取消</t-button>
      </t-space>
      <t-table
        :columns="legacyColumns"
        :data="results"
        :bordered="false"
        row-key="id"
        size="small"
        :selected-row-keys="selectedKeys"
        @select-change="onSelectChange"
        :pagination="pagination"
        @page-change="onPageChange"
      >
        <template #platform="{ row }">
          <t-tag variant="light" size="small" :theme="row.platform ? 'primary' : 'default'">
            {{ platformLabel(row.platform || '') }}
          </t-tag>
        </template>
        <template #stability="{ row }">
          <div class="stability-cell">
            <div class="stability-track">
              <div class="stability-fill" :class="stabilityClass(row.stability)" :style="{ width: (row.stability || 0) + '%' }"></div>
            </div>
            <span style="font-size:11px;color:var(--td-text-color-placeholder)">{{ Math.round(row.stability || 0) }}%</span>
          </div>
        </template>
        <template #delay="{ row }">{{ row.delay != null ? Math.round(row.delay) + ' ms' : '-' }}</template>
        <template #bandwidth="{ row }">{{ row.bandwidth != null ? Math.round(row.bandwidth) + ' KB/s' : '-' }}</template>
      </t-table>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import {
  apiScanResults, apiScanHistory, apiScanStats,
  apiPersistentGrouped, apiPersistentDetails, apiPersistentStats,
  apiPersistentManualCheck, apiPersistentExportUrl,
} from '../api.js'

// ─── 视图模式 ───
const viewMode = ref('grouped')

// ─── 分组视图状态 ───
const groupedData = ref([])
const groupedLoading = ref(false)
const expandedPlatforms = ref([])
const persistentStats = ref({ total: 0, good: 0, poor: 0, unreachable: 0, pending: 0 })
const manualChecking = ref(false)

// ─── 详情视图状态 ───
const detailView = ref(false)
const detailSourceIp = ref('')
const detailData = ref([])
const allDetailData = ref([])
const selectedDetailKeys = ref([])
const detailPage = ref(1)
const detailPerPage = ref(50)

const detailPagination = computed(() => ({
  current: detailPage.value,
  pageSize: detailPerPage.value,
  total: allDetailData.value.length,
  showJumper: true,
  pageSizeOptions: [20, 50, 100, 200],
}))

// ─── Legacy 视图状态 ───
const selectedScanId = ref('')
const categoryFilter = ref('')
const provinceFilter = ref('')
const searchQuery = ref('')
const scanHistory = ref([])
const results = ref([])
const total = ref(0)
const page = ref(1)
const perPage = ref(50)
const selectedKeys = ref([])
const categories = ref([])
const provinces = ref([])

// ─── 表格列定义 ───
const sourceColumns = [
  { colKey: 'source_ip', title: '来源IP', width: 150 },
  { colKey: 'channel_count', title: '频道数', width: 80 },
  { colKey: 'avg_stability', title: '平均稳定性', width: 130 },
  { colKey: 'avg_delay', title: '平均延迟', width: 110 },
  { colKey: 'avg_bandwidth', title: '平均带宽', width: 120 },
  { colKey: 'quality_dist', title: '质量分布', width: 220 },
  { colKey: 'first_seen', title: '首次发现', width: 110 },
  { colKey: 'last_updated', title: '最近更新', width: 110 },
]

const detailColumns = [
  { colKey: 'row-select', type: 'multiple', width: 40 },
  { colKey: 'name', title: '频道名', width: 150 },
  { colKey: 'category', title: '分类', width: 110 },
  { colKey: 'province', title: '省份', width: 90 },
  { colKey: 'resolution', title: '分辨率', width: 110 },
  { colKey: 'stability', title: '稳定性', width: 120 },
  { colKey: 'delay', title: '延迟(ms)', width: 100 },
  { colKey: 'bandwidth', title: '带宽(KB/s)', width: 120 },
  { colKey: 'quality_status', title: '质量', width: 90 },
]

const legacyColumns = [
  { colKey: 'row-select', type: 'multiple', width: 40 },
  { colKey: 'platform', title: '来源', width: 120 },
  { colKey: 'name', title: '频道名', width: 160 },
  { colKey: 'category', title: '分类', width: 110 },
  { colKey: 'province', title: '省份', width: 90 },
  { colKey: 'resolution', title: '分辨率', width: 110 },
  { colKey: 'stability', title: '稳定性', width: 120 },
  { colKey: 'delay', title: '延迟(ms)', width: 100 },
  { colKey: 'bandwidth', title: '带宽(KB/s)', width: 120 },
  { colKey: 'source_ip', title: '来源IP', width: 140 },
]

const pagination = computed(() => ({
  current: page.value,
  pageSize: perPage.value,
  total: total.value,
  showJumper: true,
  pageSizeOptions: [20, 50, 100, 200],
}))

// ─── 工具函数 ───
function stabilityClass(v) {
  v = v || 0
  if (v >= 70) return 'stability-good'
  if (v >= 40) return 'stability-mid'
  return 'stability-bad'
}

function qualityTheme(status) {
  if (status === 'good') return 'success'
  if (status === 'poor') return 'warning'
  if (status === 'unreachable') return 'danger'
  return 'default'
}

function qualityLabel(status) {
  if (status === 'good') return '好'
  if (status === 'poor') return '差'
  if (status === 'unreachable') return '不可达'
  return '待检测'
}

function platformLabel(platform) {
  const map = {
    'Quake 360': '🔍 Quake 360',
    'Hunter': '🦅 Hunter 鹰图',
    'DayDayMap': '🗺️ DayDayMap',
    'ZHGX': '📡 ZHGX',
    'JSMpeg': '📺 JSMpeg',
    'Tvheadend': '📻 Tvheadend',
    '未知': '❓ 未知平台',
  }
  return map[platform] || `📌 ${platform}`
}

function formatDate(s) {
  if (!s) return '-'
  return s.substring(0, 10)
}

// ─── 分组视图加载 ───
async function loadGrouped() {
  groupedLoading.value = true
  try {
    const [grouped, stats] = await Promise.all([
      apiPersistentGrouped(),
      apiPersistentStats(),
    ])
    groupedData.value = Array.isArray(grouped) ? grouped : []
    persistentStats.value = stats || {}
    // 默认展开第一个平台
    if (groupedData.value.length && !expandedPlatforms.value.length) {
      expandedPlatforms.value = [groupedData.value[0].platform]
    }
  } catch (e) {
    console.error('加载分组数据失败', e)
    groupedData.value = []
  } finally {
    groupedLoading.value = false
  }
}

// ─── 详情视图 ───
async function openSourceDetail(sourceIp) {
  detailSourceIp.value = sourceIp
  detailView.value = true
  detailPage.value = 1
  selectedDetailKeys.value = []
  try {
    const data = await apiPersistentDetails(sourceIp)
    allDetailData.value = Array.isArray(data) ? data : (data.items || [])
    updateDetailPage()
  } catch (e) {
    allDetailData.value = []
    detailData.value = []
  }
}

function updateDetailPage() {
  const start = (detailPage.value - 1) * detailPerPage.value
  detailData.value = allDetailData.value.slice(start, start + detailPerPage.value)
}

function onDetailPageChange(info) {
  detailPage.value = info.current
  detailPerPage.value = info.pageSize
  selectedDetailKeys.value = []
  updateDetailPage()
}

function backToGrouped() {
  detailView.value = false
  detailSourceIp.value = ''
  detailData.value = []
  allDetailData.value = []
  selectedDetailKeys.value = []
}

function selectAllDetail() {
  if (selectedDetailKeys.value.length === detailData.value.length) {
    selectedDetailKeys.value = []
  } else {
    selectedDetailKeys.value = detailData.value.map(r => r.id)
  }
}

function exportDetailM3U() {
  const items = selectedDetailKeys.value.length
    ? allDetailData.value.filter(r => selectedDetailKeys.value.includes(r.id))
    : allDetailData.value
  if (!items.length) { MessagePlugin.error('没有可导出的频道'); return }
  downloadM3U(items, `scan_${detailSourceIp.value}.m3u`)
}

async function triggerManualCheck() {
  manualChecking.value = true
  try {
    const res = await apiPersistentManualCheck()
    if (res.ok) {
      MessagePlugin.success('已触发手动检测，稍后刷新查看结果')
    } else {
      MessagePlugin.error(res.error || '触发失败')
    }
  } catch (_) {
    MessagePlugin.error('触发失败')
  } finally {
    manualChecking.value = false
  }
}

// ─── Legacy 视图函数 ───
function onSelectChange(keys) { selectedKeys.value = keys }

function formatScanOptionLabel(run) {
  const startedAt = run.started_at || run.finished_at || run.scan_id || '未知记录'
  const channelCount = run.total_deep_pass ?? run.total_deduped ?? run.total_raw
  const status = run.status ? ` [${run.status}]` : ''
  return channelCount != null ? `${startedAt}${status} - ${channelCount} 频道` : `${startedAt}${status}`
}

async function loadHistory() {
  try {
    const data = await apiScanHistory()
    scanHistory.value = Array.isArray(data) ? data : (data.history || [])
  } catch (e) { console.error('加载扫描历史失败', e) }
}

async function loadFilterOptions() {
  try {
    const params = {}
    if (selectedScanId.value) params.scan_id = selectedScanId.value
    const stats = await apiScanStats(params)
    categories.value = Object.keys(stats.by_category || {}).filter(Boolean).sort()
    provinces.value = Object.keys(stats.by_province || {}).filter(Boolean).sort()
  } catch (_) {}
}

async function loadResults() {
  const params = { page: page.value, size: perPage.value }
  if (selectedScanId.value) params.scan_id = selectedScanId.value
  if (categoryFilter.value) params.category = categoryFilter.value
  if (provinceFilter.value) params.province = provinceFilter.value
  if (searchQuery.value.trim()) params.search = searchQuery.value.trim()
  try {
    const data = await apiScanResults(params)
    results.value = (data.items || []).map(r => ({
      ...r,
      stability: Math.round(r.stability || 0),
      delay: r.delay != null ? Math.round(r.delay) : null,
      bandwidth: r.bandwidth != null ? Math.round(r.bandwidth) : null,
    }))
    total.value = data.total || results.value.length
  } catch (e) { results.value = []; total.value = 0 }
}

function reloadResults() {
  page.value = 1
  selectedKeys.value = []
  loadFilterOptions()
  loadResults()
}

function onPageChange(pageInfo) {
  page.value = pageInfo.current
  perPage.value = pageInfo.pageSize
  selectedKeys.value = []
  loadResults()
}

let debounceTimer = null
function debouncedLoad() {
  clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    page.value = 1
    selectedKeys.value = []
    loadResults()
  }, 400)
}

function selectAllLegacy() {
  if (selectedKeys.value.length === results.value.length) {
    selectedKeys.value = []
  } else {
    selectedKeys.value = results.value.map(r => r.id)
  }
}

function downloadM3U(items, filename) {
  let m3u = '#EXTM3U\n'
  items.forEach(ch => {
    m3u += `#EXTINF:-1 group-title="${ch.category || ''}",${ch.name || ''}\n`
    m3u += `${ch.url || ''}\n`
  })
  const blob = new Blob([m3u], { type: 'audio/x-mpegurl' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
  MessagePlugin.success(`已导出 ${items.length} 个频道`)
}

// ─── 生命周期 ───
watch(searchQuery, debouncedLoad)

watch(viewMode, (mode) => {
  if (mode === 'grouped') {
    loadGrouped()
  } else {
    loadHistory()
    loadFilterOptions()
    loadResults()
  }
})

onMounted(() => {
  loadGrouped()
  loadHistory()
})

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
})
</script>

<style scoped>
.scan-results-tab { padding-top: 4px; }

.view-tabs-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.stats-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}

.detail-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.detail-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--td-text-color-primary);
  flex: 1;
}

.stability-cell { display: flex; align-items: center; gap: 6px; min-width: 80px; }
.stability-track { width: 60px; height: 8px; background: var(--td-border-level-1-color, #e5e7eb); border-radius: 4px; overflow: hidden; }
.stability-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
.stability-good { background: #22c55e; }
.stability-mid { background: #f59e0b; }
.stability-bad { background: #ef4444; }

/* 让平台下的来源表格可点击 */
:deep(.t-table__body tr) {
  cursor: pointer;
}
</style>
