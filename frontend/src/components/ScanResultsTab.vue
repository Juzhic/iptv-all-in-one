<template>
  <div class="scan-results-tab">
    <!-- 筛选工具栏 -->
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

    <!-- 操作按钮 -->
    <t-space style="margin-bottom:12px">
      <t-button variant="outline" size="small" @click="selectAll">全选/取消</t-button>
      <t-button theme="primary" size="small" @click="sendToSpeedTest">送入选中去测速</t-button>
      <t-button variant="outline" size="small" @click="exportM3U">导出M3U</t-button>
    </t-space>

    <!-- 结果表格 -->
    <t-table
      :columns="columns"
      :data="results"
      :bordered="false"
      row-key="id"
      size="small"
      :selected-row-keys="selectedKeys"
      @select-change="onSelectChange"
      :pagination="pagination"
      @page-change="onPageChange"
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
    </t-table>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { apiScanResults, apiScanHistory, apiScanFeedToTest, apiScanStats } from '../api.js'

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

const columns = [
  { colKey: 'row-select', type: 'multiple', width: 40 },
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

function stabilityClass(v) {
  v = v || 0
  if (v >= 70) return 'stability-good'
  if (v >= 40) return 'stability-mid'
  return 'stability-bad'
}

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

function selectAll() {
  if (selectedKeys.value.length === results.value.length) {
    selectedKeys.value = []
  } else {
    selectedKeys.value = results.value.map(r => r.id)
  }
}

async function sendToSpeedTest() {
  const selected = selectedKeys.value
  if (!selected.length) { MessagePlugin.error('请先勾选频道'); return }
  const scanId = selectedScanId.value
  if (!scanId) { MessagePlugin.error('请先选择一条扫描记录'); return }
  // 从 results 中找对应的频道名
  const names = results.value.filter(r => selected.includes(r.id)).map(r => r.name).filter(Boolean)
  const unique = [...new Set(names)]
  if (!unique.length) { MessagePlugin.error('未找到选中频道'); return }
  try {
    const res = await apiScanFeedToTest(scanId, unique)
    if (res.ok) {
      MessagePlugin.success(res.message || '已送入测速')
      // 触发 tab 切换到系统测试
      document.querySelectorAll('.t-tabs__nav-item').forEach(el => {
        if (el.textContent.includes('系统测试')) el.click()
      })
    } else { MessagePlugin.error(res.error || '送入失败') }
  } catch (e) { MessagePlugin.error('送入失败') }
}

function exportM3U() {
  const scanId = selectedScanId.value
  if (!scanId) { MessagePlugin.error('请先选择一条扫描记录'); return }
  apiScanResults({ scan_id: scanId, size: 9999 }).then(res => {
    const items = res.items || []
    if (!items.length) { MessagePlugin.error('没有可导出的频道'); return }
    let m3u = '#EXTM3U\n'
    items.forEach(ch => {
      m3u += `#EXTINF:-1 group-title="${ch.category || ''}",${ch.name || ''}\n`
      m3u += `${ch.url || ''}\n`
    })
    const blob = new Blob([m3u], { type: 'audio/x-mpegurl' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url; a.download = 'scan_result.m3u'; a.click()
    URL.revokeObjectURL(url)
    MessagePlugin.success(`已导出 ${items.length} 个频道`)
  }).catch(() => MessagePlugin.error('导出失败'))
}

watch(searchQuery, debouncedLoad)

onMounted(() => {
  loadHistory()
  loadFilterOptions()
  loadResults()
})

onBeforeUnmount(() => {
  if (debounceTimer) clearTimeout(debounceTimer)
})
</script>

<style scoped>
.scan-results-tab { padding-top: 4px; }
.stability-cell { display: flex; align-items: center; gap: 6px; min-width: 80px; }
.stability-track { width: 60px; height: 8px; background: var(--td-border-level-1-color, #e5e7eb); border-radius: 4px; overflow: hidden; }
.stability-fill { height: 100%; border-radius: 4px; transition: width 0.3s; }
.stability-good { background: #22c55e; }
.stability-mid { background: #f59e0b; }
.stability-bad { background: #ef4444; }
</style>
