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

      <!-- 分组视图过滤栏 -->
      <div class="filter-bar">
        <t-input v-model="groupedSearch" placeholder="搜索来源IP..." clearable style="width:200px" />
        <t-select v-model="groupedQualityFilter" style="width:140px" clearable placeholder="质量筛选">
          <t-option value="" label="全部质量" />
          <t-option value="good" label="好" />
          <t-option value="poor" label="差" />
          <t-option value="unreachable" label="不可达" />
          <t-option value="pending" label="待检测" />
        </t-select>
      </div>

      <!-- 来源IP 详情弹窗 -->
      <t-dialog
        v-model:visible="detailDialogVisible"
        :header="false"
        :footer="false"
        width="1200px"
        destroy-on-close
        class="detail-dialog"
      >
        <template #header>
          <div class="dialog-header">
            <div>
              <div style="font-size:16px;font-weight:600">{{ detailSourceIp }}</div>
              <div style="font-size:12px;color:var(--td-text-color-placeholder);margin-top:4px">
                共 {{ allDetailData.length }} 个频道
              </div>
            </div>
          </div>
        </template>
        <div class="dialog-toolbar">
          <t-input v-model="detailSearch" placeholder="搜索频道名..." clearable style="width:200px" />
          <t-select v-model="detailQualityFilter" style="width:130px" clearable placeholder="质量筛选">
            <t-option value="" label="全部质量" />
            <t-option value="good" label="好" />
            <t-option value="poor" label="差" />
            <t-option value="unreachable" label="不可达" />
            <t-option value="pending" label="待检测" />
          </t-select>
          <t-select v-model="detailCategoryFilter" style="width:130px" clearable placeholder="分类筛选">
            <t-option value="" label="全部分类" />
            <t-option v-for="c in detailCategories" :key="c" :value="c" :label="c" />
          </t-select>
          <t-select v-model="detailProvinceFilter" style="width:130px" clearable placeholder="省份筛选">
            <t-option value="" label="全部省份" />
            <t-option v-for="p in detailProvinces" :key="p" :value="p" :label="p" />
          </t-select>
          <div style="flex:1"></div>
          <t-button variant="outline" size="small" @click="selectAllDetail">全选/取消</t-button>
          <t-button theme="primary" size="small" @click="exportDetailM3U">导出 M3U</t-button>
        </div>
        <t-table
          :columns="detailColumns"
          :data="filteredDetailData"
          :bordered="false"
          row-key="id"
          size="small"
          :selected-row-keys="selectedDetailKeys"
          @select-change="(keys) => selectedDetailKeys = keys"
          :sort="detailSortInfo"
          @sort-change="onDetailSortChange"
          :pagination="detailPagination"
          @page-change="onDetailPageChange"
        >
          <template #url="{ row }">
            <div class="url-with-copy">
              <t-popup :content="row.url" placement="top">
                <span class="url-text">{{ row.url }}</span>
              </t-popup>
              <t-button v-if="row.url" variant="text" size="small" class="copy-btn" @click.stop="copyText(row.url)">
                <template #icon><t-icon name="copy" /></template>
              </t-button>
            </div>
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
          <template #quality_status="{ row }">
            <t-tag :theme="qualityTheme(row.quality_status)" size="small" variant="light">{{ qualityLabel(row.quality_status) }}</t-tag>
          </template>
        </t-table>
      </t-dialog>

      <!-- 分组视图（默认） -->
      <t-skeleton :loading="groupedLoading" :row-col="[{ width: '100%' }, { width: '100%' }, { width: '100%' }]">
        <t-collapse v-if="filteredGroupedData.length" v-model="expandedPlatforms">
          <t-collapse-panel
            v-for="plat in filteredGroupedData"
            :key="plat.platform"
            :value="plat.platform"
            :header="platformLabel(plat.platform)"
            :disabled="false"
          >
            <template #headerRightContent>
              <t-space :size="8">
                <t-tag size="small" variant="light">{{ filteredSources(plat).length }} 来源</t-tag>
                <t-tag size="small" variant="light" theme="primary">{{ plat.channel_count }} 频道</t-tag>
                <t-tag size="small" variant="light">稳定性 {{ plat.avg_stability }}%</t-tag>
              </t-space>
            </template>
            <t-table
              :columns="sourceColumns"
              :data="filteredSources(plat)"
              :bordered="false"
              row-key="source_ip"
              size="small"
              :pagination="null"
              :sort="sourceSortInfo"
              @sort-change="onSourceSortChange"
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
        <template #url="{ row }">
          <div class="url-with-copy">
            <t-popup :content="row.url" placement="top">
              <span class="url-text">{{ row.url }}</span>
            </t-popup>
            <t-button v-if="row.url" variant="text" size="small" class="copy-btn" @click.stop="copyText(row.url)">
              <template #icon><t-icon name="copy" /></template>
            </t-button>
          </div>
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
  apiPersistentManualCheck,
} from '../api.js'

// ─── 复制工具 ───
async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    MessagePlugin.success('已复制')
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0'
    document.body.appendChild(ta); ta.select(); document.execCommand('copy')
    document.body.removeChild(ta)
    MessagePlugin.success('已复制')
  }
}

// ─── 视图模式 ───
const viewMode = ref('grouped')

// ─── 分组视图状态 ───
const groupedData = ref([])
const groupedLoading = ref(false)
const expandedPlatforms = ref([])
const persistentStats = ref({ total: 0, good: 0, poor: 0, unreachable: 0, pending: 0 })
const manualChecking = ref(false)

// ─── 分组视图过滤 ───
const groupedSearch = ref('')
const groupedQualityFilter = ref('')

const filteredGroupedData = computed(() => {
  const q = groupedSearch.value.toLowerCase()
  const qf = groupedQualityFilter.value
  if (!q && !qf) return groupedData.value
  return groupedData.value.map(plat => {
    const sources = (plat.sources || []).filter(s => {
      if (q && !(s.source_ip || '').toLowerCase().includes(q)) return false
      if (qf) {
        if (qf === 'good' && !s.good_count) return false
        if (qf === 'poor' && !s.poor_count) return false
        if (qf === 'unreachable' && !s.unreachable_count) return false
        if (qf === 'pending' && !s.pending_count) return false
      }
      return true
    })
    return { ...plat, sources }
  }).filter(plat => plat.sources.length > 0)
})

// ─── 来源表格排序 ───
const sourceSortInfo = ref({})

function onSourceSortChange(sort) {
  sourceSortInfo.value = sort
}

function filteredSources(plat) {
  let sources = [...(plat.sources || [])]
  const { sortBy, descending } = sourceSortInfo.value
  if (sortBy) {
    sources.sort((a, b) => {
      const va = a[sortBy] ?? (descending ? -Infinity : Infinity)
      const vb = b[sortBy] ?? (descending ? -Infinity : Infinity)
      if (typeof va === 'number' && typeof vb === 'number') return descending ? vb - va : va - vb
      return descending ? String(vb).localeCompare(String(va)) : String(va).localeCompare(String(vb))
    })
  }
  return sources
}

// ─── 详情弹窗状态 ───
const detailDialogVisible = ref(false)
const detailSourceIp = ref('')
const allDetailData = ref([])
const selectedDetailKeys = ref([])
const detailPage = ref(1)
const detailPerPage = ref(50)
const detailSearch = ref('')
const detailQualityFilter = ref('')
const detailCategoryFilter = ref('')
const detailProvinceFilter = ref('')
const detailSortInfo = ref({})

const detailCategories = computed(() => {
  const cats = new Set()
  allDetailData.value.forEach(r => { if (r.category) cats.add(r.category) })
  return [...cats].sort()
})

const detailProvinces = computed(() => {
  const provs = new Set()
  allDetailData.value.forEach(r => { if (r.province) provs.add(r.province) })
  return [...provs].sort()
})

const filteredDetailAll = computed(() => {
  const q = detailSearch.value.toLowerCase()
  const qf = detailQualityFilter.value
  const cat = detailCategoryFilter.value
  const prov = detailProvinceFilter.value
  return allDetailData.value.filter(r => {
    if (q && !(r.name || '').toLowerCase().includes(q)) return false
    if (qf && r.quality_status !== qf) return false
    if (cat && r.category !== cat) return false
    if (prov && r.province !== prov) return false
    return true
  })
})

const filteredDetailSorted = computed(() => {
  let data = [...filteredDetailAll.value]
  const { sortBy, descending } = detailSortInfo.value
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

const filteredDetailData = computed(() => {
  const start = (detailPage.value - 1) * detailPerPage.value
  return filteredDetailSorted.value.slice(start, start + detailPerPage.value)
})

const detailPagination = computed(() => ({
  current: detailPage.value,
  pageSize: detailPerPage.value,
  total: filteredDetailSorted.value.length,
  showJumper: true,
  pageSizeOptions: [20, 50, 100, 200],
}))

function onDetailSortChange(sort) {
  detailSortInfo.value = sort
  detailPage.value = 1
}

function onDetailPageChange(info) {
  detailPage.value = info.current
  detailPerPage.value = info.pageSize
  selectedDetailKeys.value = []
}

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
  { colKey: 'channel_count', title: '频道数', width: 80, sorter: true },
  { colKey: 'avg_stability', title: '平均稳定性', width: 130, sorter: true },
  { colKey: 'avg_delay', title: '平均延迟', width: 110, sorter: true },
  { colKey: 'avg_bandwidth', title: '平均带宽', width: 120, sorter: true },
  { colKey: 'quality_dist', title: '质量分布', width: 220 },
  { colKey: 'first_seen', title: '首次发现', width: 110, sorter: true },
  { colKey: 'last_updated', title: '最近更新', width: 110, sorter: true },
]

const detailColumns = [
  { colKey: 'row-select', type: 'multiple', width: 40 },
  { colKey: 'name', title: '频道名', width: 150, sorter: true },
  { colKey: 'url', title: '频道地址', width: 320, ellipsis: true },
  { colKey: 'category', title: '分类', width: 110, sorter: true },
  { colKey: 'province', title: '省份', width: 90 },
  { colKey: 'resolution', title: '分辨率', width: 110 },
  { colKey: 'stability', title: '稳定性', width: 120, sorter: true },
  { colKey: 'delay', title: '延迟(ms)', width: 100, sorter: true },
  { colKey: 'bandwidth', title: '带宽(KB/s)', width: 120, sorter: true },
  { colKey: 'quality_status', title: '质量', width: 90, sorter: true },
]

const legacyColumns = [
  { colKey: 'row-select', type: 'multiple', width: 40 },
  { colKey: 'platform', title: '来源', width: 120 },
  { colKey: 'name', title: '频道名', width: 160, sorter: true },
  { colKey: 'url', title: '频道地址', width: 320, ellipsis: true },
  { colKey: 'category', title: '分类', width: 110 },
  { colKey: 'province', title: '省份', width: 90 },
  { colKey: 'resolution', title: '分辨率', width: 110 },
  { colKey: 'stability', title: '稳定性', width: 120, sorter: true },
  { colKey: 'delay', title: '延迟(ms)', width: 100, sorter: true },
  { colKey: 'bandwidth', title: '带宽(KB/s)', width: 120, sorter: true },
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
  return s.substring(0, 19)
}

// ─── 分组视图加载 ───
async function loadGrouped() {
  groupedLoading.value = true
  try {
    const [groupedRes, statsRes] = await Promise.allSettled([
      apiPersistentGrouped(),
      apiPersistentStats(),
    ])
    if (groupedRes.status === 'fulfilled') {
      groupedData.value = Array.isArray(groupedRes.value) ? groupedRes.value : []
      if (groupedData.value.length && !expandedPlatforms.value.length) {
        expandedPlatforms.value = [groupedData.value[0].platform]
      }
    } else {
      console.error('加载分组数据失败', groupedRes.reason)
      groupedData.value = []
      MessagePlugin.error('加载分组数据失败')
    }
    if (statsRes.status === 'fulfilled') {
      persistentStats.value = statsRes.value || {}
    } else {
      console.error('加载统计数据失败', statsRes.reason)
    }
  } finally {
    groupedLoading.value = false
  }
}

// ─── 详情弹窗 ───
async function openSourceDetail(sourceIp) {
  detailSourceIp.value = sourceIp
  detailPage.value = 1
  selectedDetailKeys.value = []
  detailSearch.value = ''
  detailQualityFilter.value = ''
  detailCategoryFilter.value = ''
  detailProvinceFilter.value = ''
  detailSortInfo.value = {}
  detailDialogVisible.value = true
  try {
    const data = await apiPersistentDetails(sourceIp)
    allDetailData.value = Array.isArray(data) ? data : (data.items || [])
  } catch (e) {
    allDetailData.value = []
  }
}

function selectAllDetail() {
  if (selectedDetailKeys.value.length === filteredDetailData.value.length) {
    selectedDetailKeys.value = []
  } else {
    selectedDetailKeys.value = filteredDetailData.value.map(r => r.id)
  }
}

function exportDetailM3U() {
  const items = selectedDetailKeys.value.length
    ? filteredDetailSorted.value.filter(r => selectedDetailKeys.value.includes(r.id))
    : filteredDetailSorted.value
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

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.dialog-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.dialog-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}


.stability-cell { display: flex; align-items: center; gap: 6px; min-width: 80px; }
.stability-track { width: 60px; height: 8px; background: var(--td-border-level-1-color, #e5e7eb); border-radius: 4px; overflow: hidden; }
.stability-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
.stability-good { background: #22c55e; }
.stability-mid { background: #f59e0b; }
.stability-bad { background: #ef4444; }

/* 来源表格可点击 */
:deep(.t-table__body tr) {
  cursor: pointer;
}

/* URL + 复制按钮 */
.url-with-copy {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 100%;
}
.url-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  color: var(--td-text-color-placeholder, #6b7280);
  font-family: monospace;
  max-width: 260px;
}
.copy-btn {
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s;
  padding: 0 2px !important;
  min-width: auto !important;
}
.url-with-copy:hover .copy-btn {
  opacity: 1;
}
</style>

<style>
/* 弹窗全局样式（teleport 到 body，scoped 无法覆盖） */
.detail-dialog.t-dialog {
  max-height: 85vh;
  display: flex;
  flex-direction: column;
}
.detail-dialog .t-dialog__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.detail-dialog .t-table__content {
  max-height: calc(85vh - 200px) !important;
}
</style>
