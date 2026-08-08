<template>
  <div class="sources-tab">
    <t-card size="small" :bordered="false" class="sources-card workspace-card">
      <div class="sources-head">
        <div>
          <div class="section-title">订阅源质量</div>
          <p>基于最近一轮测试聚合频道覆盖、通过率、带宽与质量评分。</p>
        </div>
        <div class="source-meta">
          <t-tag variant="light">共 {{ total }} 个来源</t-tag>
          <span v-if="lastUpdated">更新于 {{ lastUpdated }}</span>
        </div>
      </div>

      <div class="responsive-toolbar source-toolbar">
        <t-input
          v-model="search"
          class="search-input"
          clearable
          placeholder="搜索订阅源"
          aria-label="搜索订阅源"
          @enter="applyFilters"
          @clear="applyFilters"
        />
        <t-select v-model="sortBy" class="sort-select" aria-label="订阅源排序字段" @change="applyFilters">
          <t-option value="score" label="综合评分" />
          <t-option value="channels_passed" label="通过频道" />
          <t-option value="pass_rate" label="通过率" />
          <t-option value="avg_bandwidth" label="平均带宽" />
          <t-option value="avg_quality" label="平均质量" />
        </t-select>
        <t-select v-model="sortOrder" class="order-select" aria-label="订阅源排序方向" @change="applyFilters">
          <t-option value="desc" label="降序" />
          <t-option value="asc" label="升序" />
        </t-select>
        <t-button theme="primary" @click="applyFilters">查询</t-button>
      </div>

      <AsyncState
        :loading="loading"
        :error="error"
        :empty="!items.length"
        empty-title="没有匹配的订阅源"
        empty-description="调整搜索条件，或先运行一次系统测试。"
        :retry="loadSources"
      >
        <div class="data-table-shell data-table-shell--wide source-table-shell">
          <t-table
            :data="items"
            :columns="columns"
            row-key="source_url"
            size="small"
            :bordered="false"
            :pagination="pagination"
            @page-change="onPageChange"
          >
            <template #source_url="{ row }">
              <span class="source-url" :title="row.source_url">{{ row.source_url }}</span>
            </template>
            <template #channels="{ row }">
              <strong>{{ row.channels_passed }}</strong> / {{ row.channels_total }}
            </template>
            <template #pass_rate="{ row }">
              <div class="rate-cell">
                <span>{{ percent(row.pass_rate) }}</span>
                <span class="rate-track"><i :style="{ width: percent(row.pass_rate) }"></i></span>
              </div>
            </template>
            <template #avg_bandwidth="{ row }">{{ number(row.avg_bandwidth, 2) }} MB/s</template>
            <template #avg_quality="{ row }">{{ number(row.avg_quality, 2) }}</template>
            <template #h265_ratio="{ row }">{{ percent(row.h265_ratio) }}</template>
            <template #score="{ row }">
              <t-tag :theme="scoreTheme(row.score)" variant="light">{{ number(row.score, 1) }}</t-tag>
            </template>
          </t-table>
        </div>
      </AsyncState>
    </t-card>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { apiGetSources } from '../api.js'
import AsyncState from './AsyncState.vue'

const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const search = ref('')
const sortBy = ref('score')
const sortOrder = ref('desc')
const lastUpdated = ref('')
const loading = ref(true)
const error = ref('')
let requestController = null
let requestSeq = 0

const columns = [
  { colKey: 'source_url', title: '订阅源', width: 300, ellipsis: true },
  { colKey: 'channels', title: '通过 / 总频道', width: 130 },
  { colKey: 'pass_rate', title: '通过率', width: 160 },
  { colKey: 'avg_bandwidth', title: '平均带宽', width: 120 },
  { colKey: 'avg_quality', title: '平均质量', width: 105 },
  { colKey: 'h265_ratio', title: 'H.265 占比', width: 105 },
  { colKey: 'score', title: '综合评分', width: 105, fixed: 'right' },
]

const pagination = computed(() => ({
  current: page.value,
  pageSize: pageSize.value,
  total: total.value,
  pageSizeOptions: [20, 50, 100, 200],
  showJumper: true,
}))

function number(value, digits = 0) {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : '--'
}

function percent(value) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '--'
  return `${(numeric <= 1 ? numeric * 100 : numeric).toFixed(1)}%`
}

function scoreTheme(score) {
  const value = Number(score)
  if (value >= 80) return 'success'
  if (value >= 60) return 'primary'
  if (value >= 40) return 'warning'
  return 'danger'
}

async function loadSources() {
  const seq = ++requestSeq
  requestController?.abort()
  requestController = new AbortController()
  loading.value = true
  error.value = ''
  try {
    const payload = await apiGetSources({
      search: search.value.trim(),
      sort_by: sortBy.value,
      sort_order: sortOrder.value,
      page: page.value,
      size: pageSize.value,
    }, { signal: requestController.signal })
    if (seq !== requestSeq) return
    const rows = Array.isArray(payload) ? payload : (payload?.items || [])
    items.value = rows
    total.value = Array.isArray(payload) ? rows.length : Number(payload?.total || rows.length)
    lastUpdated.value = payload?.last_updated || ''
  } catch (reason) {
    if (reason?.name === 'AbortError' || seq !== requestSeq) return
    items.value = []
    total.value = 0
    error.value = reason?.message || '订阅源加载失败'
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function applyFilters() {
  page.value = 1
  loadSources()
}

function onPageChange(info) {
  page.value = info.current
  pageSize.value = info.pageSize
  loadSources()
}

onMounted(loadSources)
onBeforeUnmount(() => requestController?.abort())
</script>

<style scoped>
.sources-tab { padding-top: 4px; }
.sources-card :deep(.t-card__body) { padding: 18px; }
.sources-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 14px;
}
.section-title { color: var(--app-text); font-size: 16px; font-weight: 700; }
.sources-head p { margin: 5px 0 0; color: var(--app-text-muted); font-size: 12px; }
.source-meta { display: flex; align-items: center; gap: 10px; color: var(--app-text-muted); font-size: 11px; }
.source-toolbar { margin-bottom: 14px; }
.search-input { width: min(320px, 100%); }
.sort-select { width: 150px; }
.order-select { width: 90px; }
.source-table-shell { border: 1px solid var(--app-border); border-radius: 12px; }
.source-url { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rate-cell { display: flex; align-items: center; gap: 8px; }
.rate-track { width: 64px; height: 5px; overflow: hidden; border-radius: 999px; background: var(--app-surface-soft); }
.rate-track i { display: block; height: 100%; border-radius: inherit; background: #22c55e; }
@media (max-width: 768px) {
  .sources-head { flex-direction: column; }
  .source-meta { flex-wrap: wrap; }
  .search-input, .sort-select, .order-select { width: 100%; }
}
</style>
