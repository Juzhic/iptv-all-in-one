<template>
  <div class="channels-tab">
    <t-space style="margin-bottom:12px">
      <t-input v-model="searchQuery" placeholder="搜索频道名..." clearable style="width:260px" />
      <t-select v-model="filter" style="width:140px">
        <t-option value="all" label="全部频道" />
        <t-option value="pass" label="有通过的" />
        <t-option value="fail" label="全部失败的" />
      </t-select>
    </t-space>

    <div v-if="!filteredChannels.length" class="empty-hint">暂无频道数据</div>

    <t-collapse v-for="(info, name) in filteredChannels" :key="name" expand-mutex>
      <t-collapse-panel :value="name">
        <template #header>
          <div class="ch-header">
            <div class="ch-name">
              {{ name }}
              <t-tag v-if="hasH265(info)" size="small" variant="light" style="margin-left:6px">H.265</t-tag>
            </div>
            <t-space :size="8">
              <t-tag :theme="info.passed > 0 ? 'success' : 'danger'" size="small" variant="light">
                {{ info.passed }}/{{ info.total }} 通过
              </t-tag>
              <span style="font-size:13px;color:var(--td-text-color-primary)">{{ ((info.passed / info.total) * 100).toFixed(1) }}%</span>
            </t-space>
          </div>
        </template>
        <t-table
          :columns="urlColumns"
          :data="info.urls || []"
          :bordered="false"
          size="small"
          row-key="url"
          :header-affixed-top="false"
        >
          <template #url="{ row }">
            <t-popup :content="row.url" placement="top">
              <div class="url-cell">{{ row.url }}</div>
            </t-popup>
          </template>
          <template #is_h265="{ row }">
            <t-tag v-if="row.is_h265" class="codec-tag codec-tag-h265" size="small" variant="light">H.265</t-tag>
            <t-tag v-else-if="row.codec" class="codec-tag codec-tag-codec" size="small" variant="light">{{ row.codec?.toUpperCase() }}</t-tag>
            <span v-else>-</span>
          </template>
          <template #passed="{ row }">
            <t-tag :theme="row.passed ? 'success' : 'danger'" size="small">{{ row.passed ? '通过' : '失败' }}</t-tag>
          </template>
          <template #connection_latency_ms="{ row }">
            {{ row.connection_latency_ms != null ? Math.round(row.connection_latency_ms) + ' ms' : '-' }}
          </template>
          <template #quality_score="{ row }">
            {{ row.quality_score != null ? Number(row.quality_score).toFixed(2) : '-' }}
          </template>
        </t-table>
      </t-collapse-panel>
    </t-collapse>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({ channelSummary: Object })

const searchQuery = ref('')
const filter = ref('all')

const urlColumns = [
  { colKey: 'url', title: 'URL', width: 300, ellipsis: true },
  { colKey: 'resolution', title: '分辨率', width: 100 },
  { colKey: 'bandwidth_MBps', title: '带宽(MB/s)', width: 100 },
  { colKey: 'connection_latency_ms', title: '延迟', width: 90 },
  { colKey: 'quality_score', title: '评分', width: 80 },
  { colKey: 'is_h265', title: '编码', width: 90 },
  { colKey: 'passed', title: '状态', width: 80 },
  { colKey: 'reason', title: '原因', width: 150, ellipsis: true },
]

function hasH265(info) {
  return (info.urls || []).some(u => u.is_h265)
}

const filteredChannels = computed(() => {
  const q = searchQuery.value.toLowerCase()
  const f = filter.value
  const src = props.channelSummary || {}
  const result = {}
  for (const [name, info] of Object.entries(src)) {
    if (q && !name.toLowerCase().includes(q)) continue
    if (f === 'pass' && info.passed === 0) continue
    if (f === 'fail' && info.passed > 0) continue
    result[name] = info
  }
  return result
})
</script>

<style scoped>
.channels-tab { padding-top: 4px; }
.ch-header { display: flex; align-items: center; justify-content: space-between; width: 100%; }
.ch-name { font-weight: 600; font-size: 14px; }
.url-cell { max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--td-text-color-placeholder, #6b7280); font-family: monospace; cursor: pointer; }
.url-cell:hover { white-space: normal; word-break: break-all; }
.empty-hint { text-align: center; padding: 40px; color: var(--td-text-color-placeholder); font-size: 13px; }
.codec-tag-h265 { background: var(--td-brand-color-light); color: var(--td-brand-color); }
.codec-tag-codec { background: var(--td-bg-color-component); color: var(--td-text-color-secondary); }
</style>
