<template>
  <div class="ip-scan-tab">
    <!-- 输入区域 -->
    <t-card size="small" :bordered="false" class="panel-card">
      <div class="section-title">IP扫描</div>
      <p class="section-subtitle">
        输入格式：IP:PORT 或纯IP或域名（每行一个），支持#注释
      </p>
      <t-textarea
        v-model="targets"
        placeholder="192.168.1.1:8080&#10;10.0.0.1&#10;example.com&#10;# 这是注释"
        :rows="8"
        :autosize="false"
      />
      <div class="input-actions">
        <t-button variant="outline" size="small" @click="clearInput">清空</t-button>
        <t-button variant="outline" size="small" @click="importIPs">导入IP列表</t-button>
        <t-button variant="outline" size="small" @click="loadExample">加载示例</t-button>
      </div>
    </t-card>

    <!-- 配置区域 -->
    <t-card size="small" :bordered="false" class="panel-card">
      <div class="section-title">扫描配置</div>
      
      <!-- 端口配置 -->
      <div class="config-row">
        <label class="config-label">测试端口类别：</label>
        <t-select 
          v-model="portPreset" 
          :options="portPresetOptions"
          style="width: 200px"
          @change="onPortPresetChange"
        />
      </div>
      <div class="config-row">
        <label class="config-label">测试端口：</label>
        <t-input 
          v-model="portsInput" 
          placeholder="4022,7088,5140,8888,2380"
          style="flex: 1"
        />
        <span class="config-hint">英文逗号、中文逗号或空格分隔，输入包含端口时忽略此项</span>
      </div>

      <!-- 扫描类型 -->
      <div class="config-row">
        <label class="config-label">扫描选项：</label>
        <t-checkbox-group v-model="scanTypes" :options="scanTypeOptions" />
      </div>

      <!-- 扫描参数 -->
      <div class="params-grid">
        <div class="param-item">
          <label>扫描工作进程数</label>
          <t-input-number v-model="workers" :min="1" :max="100" theme="column" />
        </div>
        <div class="param-item">
          <label>扫描速率</label>
          <t-input-number v-model="rateLimit" :min="100" :max="50000" step="1000" theme="column" />
        </div>
        <div class="param-item">
          <label>HTTP测试并发数</label>
          <t-input-number v-model="httpConcurrent" :min="1" :max="500" theme="column" />
        </div>
        <div class="param-item">
          <label>任务超时时间（秒）</label>
          <t-input-number v-model="timeout" :min="60" :max="86400" step="60" theme="column" />
        </div>
      </div>
    </t-card>

    <!-- 操作按钮 -->
    <t-card size="small" :bordered="false" class="panel-card">
      <t-space>
        <t-button 
          theme="success" 
          :disabled="scanRunning" 
          :loading="scanStarting" 
          @click="startScan"
        >
          开始扫描
        </t-button>
        <t-button 
          v-if="scanRunning" 
          theme="danger" 
          :disabled="scanStopping" 
          @click="stopScan"
        >
          {{ scanStopping ? '终止中...' : '停止扫描' }}
        </t-button>
        <t-button 
          v-if="scanRunning" 
          variant="outline" 
          theme="warning" 
          :disabled="scanClearing"
          @click="forceClear"
        >
          {{ scanClearing ? '清除中...' : '强制清除状态' }}
        </t-button>
      </t-space>
      <p class="section-subtitle clear-hint">
        扫描卡死、点"开始"却提示"正在进行中"时，用此按钮强制清除残留状态。
      </p>
    </t-card>

    <!-- 进度显示 -->
    <t-card size="small" :bordered="false" class="panel-card">
      <div class="section-title">扫描进度</div>
      <span class="phase-text">{{ phaseText }}</span>
      <div v-if="scanRunning || progressVisible" class="progress-wrap">
        <div class="progress-head">
          <span class="progress-label">{{ progressLabel }}</span>
          <span class="progress-value">{{ progressPct }}%</span>
        </div>
        <t-progress :percentage="progressPct" />
      </div>
      <LogPanel
        :entries="logLines"
        :show-count="false"
        empty-text="等待扫描开始..."
        @clear="clearLogs"
      />
    </t-card>

    <!-- 扫描概览 -->
    <div v-if="summary.scanId" class="summary-head">
      <div>
        <div class="section-title summary-title">扫描概览</div>
        <div class="summary-caption">{{ summaryCaption }}</div>
      </div>
      <div class="summary-status" :class="summaryStatusTone">{{ summaryStatusText }}</div>
    </div>

    <div v-if="summary.scanId" class="stats-grid">
      <t-card
        v-for="card in statCards"
        :key="card.key"
        size="small"
        :bordered="false"
        class="stat-card"
        :class="card.tone"
      >
        <div class="stat-top">
          <span class="stat-badge">{{ card.badge }}</span>
        </div>
        <div class="stat-value">{{ formatMetric(card.value) }}</div>
        <div class="stat-label">{{ card.label }}</div>
      </t-card>
    </div>

    <!-- 结果表格 -->
    <t-card size="small" :bordered="false" class="panel-card">
      <div class="section-title">扫描结果</div>
      <div class="result-actions">
        <t-button 
          theme="primary" 
          size="small" 
          :disabled="!hasSelectedRows"
          @click="sendSelectedToTest"
        >
          送入选中测速
        </t-button>
        <t-button 
          variant="outline" 
          size="small" 
          :disabled="!summary.scanId"
          @click="exportM3U"
        >
          导出M3U
        </t-button>
      </div>
      <t-table
        :data="results"
        :columns="columns"
        :loading="loading"
        :pagination="pagination"
        :selected-row-keys="selectedRowKeys"
        :select-on-row-click="false"
        row-key="target"
        @page-change="onPageChange"
        @select-change="onSelectChange"
      >
        <template #alive="{ row }">
          <t-tag :theme="row.alive ? 'success' : 'danger'" variant="light" size="small">
            {{ row.alive ? '存活' : '失败' }}
          </t-tag>
        </template>
        <template #http_status="{ row }">
          <span :class="getStatusClass(row.http_status)">{{ row.http_status || '-' }}</span>
        </template>
        <template #response_time_ms="{ row }">
          <span>{{ row.response_time_ms ? Math.round(row.response_time_ms) + 'ms' : '-' }}</span>
        </template>
        <template #channels="{ row }">
          <t-button 
            v-if="row.channel_count > 0" 
            size="small" 
            variant="text" 
            theme="primary"
            @click="viewChannels(row)"
          >
            {{ row.channel_count }} 个频道
          </t-button>
          <span v-else class="text-muted">-</span>
        </template>
        <template #scan_type_matched="{ row }">
          <t-tag v-if="row.scan_type_matched" size="small" variant="light">
            {{ row.scan_type_matched }}
          </t-tag>
          <span v-else class="text-muted">-</span>
        </template>
      </t-table>
    </t-card>

    <!-- 频道详情弹窗 -->
    <t-dialog
      v-model:visible="channelDialogVisible"
      header="频道列表"
      :footer="false"
      width="600px"
    >
      <div class="channel-list">
        <div v-for="(ch, index) in channelList" :key="index" class="channel-item">
          <span class="channel-name">{{ ch.name }}</span>
          <span class="channel-url">{{ ch.url }}</span>
        </div>
        <div v-if="!channelList.length" class="empty-text">暂无频道</div>
      </div>
    </t-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { 
  apiIpScanTrigger, 
  apiIpScanStop, 
  apiIpScanForceClear,
  apiIpScanStatus, 
  apiIpScanLogs,
  apiIpScanResults,
  apiIpScanLatest,
  apiIpScanStats,
  apiIpScanToTest,
  apiIpScanExportUrl,
  connectIpScanSse,
  shouldUseSse
} from '../api.js'
import LogPanel from './LogPanel.vue'

// 输入数据
const targets = ref('')
const portsInput = ref('4022,7088,5140,8888,2380')
const portPreset = ref('常用IPTV')
const scanTypes = ref(['ALL'])

// 扫描参数
const workers = ref(16)
const rateLimit = ref(5000)
const httpConcurrent = ref(50)
const timeout = ref(3600)

// 状态
const scanRunning = ref(false)
const scanStarting = ref(false)
const scanStopping = ref(false)
const scanClearing = ref(false)
const progressVisible = ref(false)
const phaseText = ref('空闲')
const progressLabel = ref('')
const progressPct = ref(0)
const logLines = ref([])
const results = ref([])
const loading = ref(false)
const summary = ref(createEmptySummary())
const selectedRowKeys = ref([])

// 频道弹窗
const channelDialogVisible = ref(false)
const channelList = ref([])

// 分页
const pagination = ref({
  current: 1,
  pageSize: 20,
  total: 0,
  showJumper: true,
  showPageSize: true,
})

// SSE连接
let sseSource = null
let lastLogSeq = 0

// 端口预设选项
const portPresetOptions = [
  { label: '常用IPTV', value: '常用IPTV' },
  { label: 'Web服务', value: 'Web服务' },
  { label: '流媒体', value: '流媒体' },
  { label: '全部', value: '全部' },
]

// 扫描类型选项
const scanTypeOptions = [
  { label: 'ALL（全部）', value: 'ALL' },
  { label: '2380', value: '2380' },
  { label: 'HOTEL（酒店）', value: 'HOTEL' },
  { label: 'MULTICAST（组播）', value: 'MULTICAST' },
  { label: 'MIGU（咪咕）', value: 'MIGU' },
  { label: 'ICNTV', value: 'ICNTV' },
  { label: 'SOCKS5', value: 'SOCKS5' },
]

// 表格列定义
const columns = [
  { colKey: 'row-select', type: 'multiple', width: 50 },
  { colKey: 'target', title: '目标', width: 200, ellipsis: true },
  { colKey: 'alive', title: '状态', width: 80 },
  { colKey: 'http_status', title: 'HTTP', width: 80 },
  { colKey: 'response_time_ms', title: '响应时间', width: 100 },
  { colKey: 'channels', title: '频道数', width: 100 },
  { colKey: 'scan_type_matched', title: '匹配类型', width: 100 },
  { colKey: 'error', title: '错误信息', width: 150, ellipsis: true },
]

// 计算属性
const parsedPorts = computed(() => {
  return portsInput.value
    .split(/[,，\s]+/)
    .map(p => parseInt(p.trim()))
    .filter(p => !isNaN(p) && p > 0)
})

const hasSelectedRows = computed(() => {
  return selectedRowKeys.value.length > 0
})

const summaryCaption = computed(() => {
  if (!summary.value.scanId) return ''
  return `扫描ID: ${summary.value.scanId.substring(0, 8)}... | 耗时: ${formatDuration(summary.value.durationSeconds)}`
})

const summaryStatusTone = computed(() => {
  if (summary.value.status === 'completed') return 'status-success'
  if (summary.value.status === 'running') return 'status-running'
  if (summary.value.status === 'stopped') return 'status-warning'
  return 'status-error'
})

const summaryStatusText = computed(() => {
  const statusMap = {
    'completed': '已完成',
    'running': '扫描中',
    'stopped': '已停止',
    'error': '出错',
  }
  return statusMap[summary.value.status] || summary.value.status
})

const statCards = computed(() => [
  {
    key: 'input',
    badge: '输入',
    value: summary.value.inputCount,
    label: '目标数量',
    tone: 'stat-default',
  },
  {
    key: 'alive',
    badge: '存活',
    value: summary.value.totalAlive,
    label: '存活目标',
    tone: summary.value.totalAlive > 0 ? 'stat-success' : 'stat-default',
  },
  {
    key: 'channels',
    badge: '频道',
    value: summary.value.totalChannels,
    label: '发现频道',
    tone: summary.value.totalChannels > 0 ? 'stat-primary' : 'stat-default',
  },
])

// 方法
function createEmptySummary() {
  return {
    scanId: '',
    status: '',
    startedAt: '',
    finishedAt: '',
    durationSeconds: 0,
    inputCount: 0,
    totalAlive: 0,
    totalChannels: 0,
  }
}

function normalizeSummary(raw) {
  if (!raw || typeof raw !== 'object') return createEmptySummary()
  return {
    scanId: raw.scan_id || '',
    status: raw.status || '',
    startedAt: raw.started_at || '',
    finishedAt: raw.finished_at || '',
    durationSeconds: Number(raw.duration_seconds) || 0,
    inputCount: Number(raw.input_count) || 0,
    totalAlive: Number(raw.total_alive) || 0,
    totalChannels: Number(raw.total_channels) || 0,
  }
}

function formatMetric(value) {
  if (value === null || value === undefined) return '0'
  return Number(value).toLocaleString()
}

function formatDuration(seconds) {
  if (!seconds) return '0s'
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

function getStatusClass(status) {
  if (!status) return ''
  if (status >= 200 && status < 300) return 'status-2xx'
  if (status >= 300 && status < 400) return 'status-3xx'
  if (status >= 400 && status < 500) return 'status-4xx'
  return 'status-5xx'
}

function onPortPresetChange(value) {
  const presets = {
    '常用IPTV': '4022,7088,5140,8888,2380',
    'Web服务': '80,443,8080,8000,9090',
    '流媒体': '3000,5000,8443,9981',
    '全部': '4022,7088,5140,8888,2380,80,443,8080,8000,9090,3000,5000,8443',
  }
  portsInput.value = presets[value] || ''
}

function clearInput() {
  targets.value = ''
}

function importIPs() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.txt,.csv,.list'
  input.onchange = (e) => {
    const file = e.target.files[0]
    if (file) {
      const reader = new FileReader()
      reader.onload = (event) => {
        targets.value = event.target.result
        MessagePlugin.success(`已导入文件: ${file.name}`)
      }
      reader.readAsText(file)
    }
  }
  input.click()
}

function loadExample() {
  targets.value = `# 示例IP列表
192.168.1.1:8080
10.0.0.1
example.com
# 可以添加注释
172.16.0.1:4022`
}

function clearLogs() {
  logLines.value = []
  lastLogSeq = 0
}

function appendLogEntries(entries) {
  if (!Array.isArray(entries) || !entries.length) return
  entries.forEach((data) => {
    const seq = Number(data.seq)
    if (Number.isFinite(seq) && seq <= lastLogSeq) return
    logLines.value.push(data)
    if (Number.isFinite(seq)) lastLogSeq = seq
  })

  const MAX_LOG_LINES = 2000
  if (logLines.value.length > MAX_LOG_LINES) {
    logLines.value = logLines.value.slice(-1500)
  }
}

// 开始扫描
async function startScan() {
  if (!targets.value.trim()) {
    MessagePlugin.warning('请输入扫描目标')
    return
  }
  
  if (scanTypes.value.length === 0) {
    MessagePlugin.warning('请选择至少一种扫描类型')
    return
  }
  
  if (parsedPorts.value.length === 0) {
    MessagePlugin.warning('请配置至少一个测试端口')
    return
  }
  
  scanStarting.value = true
  try {
    const result = await apiIpScanTrigger({
      targets: targets.value,
      scan_types: scanTypes.value,
      ports: parsedPorts.value,
      workers: workers.value,
      rate_limit: rateLimit.value,
      http_concurrent: httpConcurrent.value,
      timeout: timeout.value,
    })
    
    if (result.ok) {
      MessagePlugin.success('IP扫描已启动')
      scanRunning.value = true
      progressVisible.value = true
      connectSse()
    }
  } catch (e) {
    MessagePlugin.error(e.message || '启动失败')
  } finally {
    scanStarting.value = false
  }
}

// 停止扫描
async function stopScan() {
  scanStopping.value = true
  try {
    await apiIpScanStop()
    MessagePlugin.success('已请求停止')
  } catch (e) {
    MessagePlugin.error(e.message || '停止失败')
  } finally {
    scanStopping.value = false
  }
}

// 强制清除
async function forceClear() {
  const confirm = await DialogPlugin.confirm({
    header: '确认强制清除',
    body: '确定要强制清除扫描状态吗？这可能导致正在进行的扫描任务异常。',
  })
  
  if (confirm) {
    scanClearing.value = true
    try {
      await apiIpScanForceClear()
      scanRunning.value = false
      progressVisible.value = false
      stopPolling()
      if (sseSource) {
        sseSource.close()
        sseSource = null
      }
      MessagePlugin.success('状态已清除')
    } catch (e) {
      MessagePlugin.error(e.message || '清除失败')
    } finally {
      scanClearing.value = false
    }
  }
}

// SSE连接
async function connectSse() {
  if (sseSource) {
    sseSource.close()
    sseSource = null
  }
  if (!await shouldUseSse()) {
    startPolling()
    return
  }
  
  try {
    sseSource = connectIpScanSse({
    log: (event) => {
      try {
        const data = JSON.parse(event.data)
        appendLogEntries([data])
      } catch (e) {
        console.error('解析日志失败:', e)
      }
    },
    status: (event) => {
      try {
        const data = JSON.parse(event.data)
        updateStatus(data)
      } catch (e) {
        console.error('解析状态失败:', e)
      }
    },
    onerror: () => {
      if (sseSource) {
        sseSource.close()
        sseSource = null
      }
      if (scanRunning.value || progressVisible.value) {
        startPolling()
      }
      console.error('SSE连接错误')
    }
    })
  } catch (_) {
    startPolling()
  }
}

// 轮询状态
let pollTimer = null

async function pollOnce() {
  const [status, logs] = await Promise.all([
    apiIpScanStatus(),
    apiIpScanLogs(lastLogSeq),
  ])
  if (status) {
    updateStatus(status)
  }
  appendLogEntries(logs?.lines || logs || [])
}

function startPolling() {
  stopPolling()
  pollOnce().catch((e) => console.error('轮询失败:', e))
  pollTimer = setInterval(async () => {
    try {
      await pollOnce()
    } catch (e) {
      console.error('轮询失败:', e)
    }
  }, 2000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function updateStatus(data) {
  if (data.running !== undefined) {
    scanRunning.value = Boolean(data.running)
  }
  if (data.phase) {
    phaseText.value = data.phase
  }
  if (data.percent !== undefined) {
    progressPct.value = Math.round(data.percent)
  }
  if (data.message) {
    progressLabel.value = data.message
  }
  
  // 扫描结束
  if (!data.running && progressVisible.value) {
    stopPolling()
    loadResults()
    loadStats()
    
    if (sseSource) {
      sseSource.close()
      sseSource = null
    }
  }
}

// 加载结果
async function loadResults() {
  loading.value = true
  try {
    const data = await apiIpScanResults({
      page: pagination.value.current,
      size: pagination.value.pageSize,
    })
    if (data) {
      results.value = data.items || []
      pagination.value.total = data.total || 0
      
      if (data.scan_id) {
        summary.value.scanId = data.scan_id
      }
    }
  } catch (e) {
    console.error('加载结果失败:', e)
  } finally {
    loading.value = false
  }
}

// 加载统计
async function loadStats() {
  try {
    const stats = await apiIpScanStats()
    if (stats) {
      summary.value.totalAlive = stats.alive_count || 0
      summary.value.totalChannels = stats.total_channels || 0
    }
  } catch (e) {
    console.error('加载统计失败:', e)
  }
}

// 加载最新扫描记录
async function loadLatest() {
  try {
    const latest = await apiIpScanLatest()
    if (latest) {
      summary.value = normalizeSummary(latest)
      if (latest.status === 'running') {
        scanRunning.value = true
        progressVisible.value = true
        connectSse()
      }
      await loadResults()
    }
  } catch (e) {
    console.error('加载最新记录失败:', e)
  }
}

// 分页变化
function onPageChange(pageInfo) {
  pagination.value.current = pageInfo.current
  pagination.value.pageSize = pageInfo.pageSize
  loadResults()
}

// 选择变化
function onSelectChange(selectedKeys) {
  selectedRowKeys.value = selectedKeys
}

// 查看频道
function viewChannels(row) {
  try {
    channelList.value = JSON.parse(row.channels_json || '[]')
  } catch (e) {
    channelList.value = []
  }
  channelDialogVisible.value = true
}

// 送入测速
async function sendSelectedToTest() {
  if (selectedRowKeys.value.length === 0) {
    MessagePlugin.warning('请先选择要送入测速的目标')
    return
  }
  
  try {
    const result = await apiIpScanToTest({
      scan_id: summary.value.scanId,
      selected: selectedRowKeys.value,
    })
    
    if (result.ok) {
      MessagePlugin.success(result.message || '已送入测速')
      selectedRowKeys.value = []
    }
  } catch (e) {
    MessagePlugin.error(e.message || '送入测速失败')
  }
}

// 导出M3U
function exportM3U() {
  if (!summary.value.scanId) {
    MessagePlugin.warning('没有可导出的扫描结果')
    return
  }
  
  const url = apiIpScanExportUrl(summary.value.scanId)
  window.open(url, '_blank')
}

// 生命周期
onMounted(() => {
  loadLatest()
})

onBeforeUnmount(() => {
  stopPolling()
  if (sseSource) {
    sseSource.close()
    sseSource = null
  }
})
</script>

<style scoped>
.ip-scan-tab {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.panel-card {
  background: var(--td-bg-color-container);
  border-radius: var(--td-radius-default);
  padding: 16px;
}

.section-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--td-text-color-primary);
}

.section-subtitle {
  font-size: 13px;
  color: var(--td-text-color-secondary);
  margin-bottom: 12px;
}

.clear-hint {
  margin-top: 8px;
  font-size: 12px;
}

.input-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.config-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.config-label {
  min-width: 100px;
  font-size: 14px;
  color: var(--td-text-color-primary);
}

.config-hint {
  font-size: 12px;
  color: var(--td-text-color-placeholder);
  white-space: nowrap;
}

.params-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
  margin-top: 12px;
}

.param-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.param-item label {
  font-size: 13px;
  color: var(--td-text-color-secondary);
}

.phase-text {
  font-size: 13px;
  color: var(--td-text-color-secondary);
}

.progress-wrap {
  margin-top: 12px;
}

.progress-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}

.progress-label {
  font-size: 13px;
  color: var(--td-text-color-primary);
}

.progress-value {
  font-size: 13px;
  font-weight: 600;
  color: var(--td-brand-color);
}

.summary-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  background: var(--td-bg-color-container);
  border-radius: var(--td-radius-default);
}

.summary-title {
  margin-bottom: 4px;
}

.summary-caption {
  font-size: 13px;
  color: var(--td-text-color-secondary);
}

.summary-status {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 13px;
  font-weight: 500;
}

.status-success {
  background: var(--td-success-color-1);
  color: var(--td-success-color);
}

.status-running {
  background: var(--td-brand-color-1);
  color: var(--td-brand-color);
}

.status-warning {
  background: var(--td-warning-color-1);
  color: var(--td-warning-color);
}

.status-error {
  background: var(--td-error-color-1);
  color: var(--td-error-color);
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 16px;
}

.stat-card {
  background: var(--td-bg-color-container);
  border-radius: var(--td-radius-default);
  padding: 16px;
}

.stat-top {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
}

.stat-badge {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--td-bg-color-component);
  color: var(--td-text-color-secondary);
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--td-text-color-primary);
}

.stat-label {
  font-size: 13px;
  color: var(--td-text-color-secondary);
  margin-top: 4px;
}

.stat-success .stat-value {
  color: var(--td-success-color);
}

.stat-primary .stat-value {
  color: var(--td-brand-color);
}

.result-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.status-2xx {
  color: var(--td-success-color);
}

.status-3xx {
  color: var(--td-brand-color);
}

.status-4xx {
  color: var(--td-warning-color);
}

.status-5xx {
  color: var(--td-error-color);
}

.text-muted {
  color: var(--td-text-color-placeholder);
}

.channel-list {
  max-height: 400px;
  overflow-y: auto;
}

.channel-item {
  display: flex;
  flex-direction: column;
  padding: 8px 0;
  border-bottom: 1px solid var(--td-border-level-1-color);
}

.channel-item:last-child {
  border-bottom: none;
}

.channel-name {
  font-weight: 500;
  color: var(--td-text-color-primary);
}

.channel-url {
  font-size: 12px;
  color: var(--td-text-color-secondary);
  word-break: break-all;
  margin-top: 4px;
}

.empty-text {
  text-align: center;
  padding: 24px;
  color: var(--td-text-color-placeholder);
}
</style>
