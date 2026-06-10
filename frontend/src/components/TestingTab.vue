<template>
  <div class="testing-tab">
    <!-- 测试控制 -->
    <t-card size="small" :bordered="false" style="margin-bottom:12px">
      <div class="card-label" style="margin-bottom:12px">测试控制</div>
      <t-space>
        <t-button theme="success" :disabled="running" :loading="starting" @click="triggerTest">
          {{ running ? '运行中...' : '立即测试' }}
        </t-button>
        <t-button v-if="running" theme="danger" :disabled="stopping" @click="stopTest">
          {{ stopping ? '终止中...' : '终止测试' }}
        </t-button>
        <span style="font-size:13px;color:var(--td-text-color-placeholder)">{{ statusText }}</span>
      </t-space>
      <div v-if="running || progressVisible" style="margin-top:12px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <span style="font-size:12px;color:var(--td-text-color-secondary)">进度 {{ progressLabel }}</span>
          <span style="font-size:12px;font-weight:600;color:#2563eb">{{ progressPct }}%</span>
        </div>
        <t-progress :percentage="progressPct" status="active" />
        <t-space :size="16" style="margin-top:6px">
          <span style="font-size:12px">已测：<b>{{ processed }}</b></span>
          <span style="font-size:12px;color:#16a34a">通过：<b>{{ passed }}</b></span>
          <span style="font-size:12px;color:#dc2626">失败：<b>{{ failed }}</b></span>
          <span style="font-size:12px">耗时：<b>{{ elapsed }}</b>s</span>
        </t-space>
      </div>
    </t-card>

    <!-- 日志面板 -->
    <t-card size="small" :bordered="false" style="margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <div class="card-label" style="margin:0">实时日志</div>
        <t-space>
          <t-button :theme="autoScroll ? 'primary' : 'default'" variant="outline" size="small" @click="autoScroll = !autoScroll">自动滚动</t-button>
          <t-button variant="outline" size="small" @click="logLines = []">清空</t-button>
        </t-space>
      </div>
      <div class="log-panel" ref="logPanelRef">
        <div v-for="(l, i) in logLines" :key="i" class="log-line">
          <span class="log-time">[{{ l.time }}]</span>
          <span :class="logMsgClass(l.msg)">{{ l.msg }}</span>
        </div>
        <div v-if="!logLines.length" style="color:#6b7280">等待测试开始...</div>
      </div>
    </t-card>

    <!-- 下载链接 -->
    <t-card size="small" :bordered="false">
      <div class="card-label" style="margin-bottom:8px">结果订阅地址</div>
      <p style="font-size:12px;color:var(--td-text-color-placeholder);margin-bottom:12px">
        复制以下地址到播放器，可自动获取最新测速通过的频道列表
      </p>
      <div v-for="fmt in ['txt', 'm3u']" :key="fmt" class="download-row">
        <span style="font-size:12px;color:var(--td-text-color-placeholder);width:36px;text-transform:uppercase">{{ fmt }}</span>
        <t-link :href="downloadUrl(fmt)" target="_blank" theme="primary">{{ downloadUrl(fmt) }}</t-link>
        <t-button variant="outline" size="small" @click="copyLink(fmt)">复制</t-button>
        <t-button variant="outline" size="small" @click="previewResult(fmt)">预览</t-button>
      </div>

      <!-- 预览 -->
      <div v-if="previewVisible" style="margin-top:12px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
          <span style="font-size:12px;font-weight:600">{{ previewTitle }}</span>
          <t-space>
            <t-button variant="outline" size="small" @click="copyPreview">复制全部</t-button>
            <t-button variant="outline" size="small" @click="previewVisible = false">关闭</t-button>
          </t-space>
        </div>
        <pre class="preview-content">{{ previewContent }}</pre>
        <div style="font-size:11px;color:var(--td-text-color-placeholder);margin-top:6px">{{ previewStats }}</div>
      </div>
    </t-card>
  </div>
</template>

<script setup>
import { ref, nextTick, watch, inject } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { apiTriggerTest, apiStopTest, apiGetProgress, apiPreviewResult, apiDownloadUrl } from '../api.js'
import { usePolling } from '../composables/usePolling.js'

const emit = defineEmits(['test-finished'])

// 从 App.vue 注入全局测试状态和轮询重启函数
const appTestRunning = inject('testRunning', ref(false))
const startGlobalPoll = inject('startGlobalPoll', () => {})

const running = ref(false)
const starting = ref(false)
const stopping = ref(false)
const statusText = ref('空闲')
const progressVisible = ref(false)
const progressLabel = ref('')
const progressPct = ref(0)
const processed = ref(0)
const passed = ref(0)
const failed = ref(0)
const elapsed = ref(0)
const logLines = ref([])
const logPanelRef = ref(null)
const autoScroll = ref(true)
const previewVisible = ref(false)
const previewTitle = ref('')
const previewContent = ref('')
const previewStats = ref('')

let lastLogSeq = 0
let wasRunning = false

function logMsgClass(msg) {
  if (/通过|pass/i.test(msg)) return 'log-msg-pass'
  if (/拒绝|失败/i.test(msg)) return 'log-msg-fail'
  return 'log-msg-info'
}

const { start: startPoll, stop: stopPoll } = usePolling(async () => {
  try {
    const data = await apiGetProgress(lastLogSeq)
    running.value = !!data.running
    if (data.running) {
      wasRunning = true
      const total = Number(data.total) || 0
      processed.value = Number(data.processed) || 0
      passed.value = data.passed || 0
      failed.value = data.failed || 0
      elapsed.value = Math.round(data.elapsed || 0)
      progressPct.value = total > 0 ? Math.min(100, Math.round(processed.value / total * 100)) : 0
      progressLabel.value = total > 0 ? `${processed.value} / ${total}` : '准备中...'
      if (data.lines?.length) {
        data.lines.forEach(l => {
          if (l.seq > lastLogSeq) {
            logLines.value.push(l)
            lastLogSeq = l.seq
          }
        })
        if (autoScroll.value) {
          nextTick(() => {
            const el = logPanelRef.value
            if (el) el.scrollTop = el.scrollHeight
          })
        }
      }
    } else if (wasRunning) {
      wasRunning = false
      statusText.value = '已完成'
      progressLabel.value = '测试完成'
      if (data.lines?.length) {
        data.lines.forEach(l => { if (l.seq > lastLogSeq) { logLines.value.push(l); lastLogSeq = l.seq } })
      }
      stopPoll()
      emit('test-finished')
      MessagePlugin.success('测试已完成')
    }
  } catch (_) {}
}, 2000)

async function triggerTest() {
  starting.value = true
  try {
    const res = await apiTriggerTest()
    if (res.ok) {
      MessagePlugin.success('测试已启动')
      logLines.value = []
      lastLogSeq = 0
      running.value = true
      wasRunning = true
      progressVisible.value = true
      statusText.value = '运行中...'
      startPoll()
      startGlobalPoll()  // 通知 App.vue 重启全局轮询
    } else {
      MessagePlugin.error(res.error || '启动失败')
    }
  } catch (e) { MessagePlugin.error('启动失败: ' + e.message) }
  finally { starting.value = false }
}

async function stopTest() {
  stopping.value = true
  try {
    await apiStopTest()
    MessagePlugin.success('已请求终止')
    wasRunning = false
    running.value = false
    stopPoll()
  } catch (e) { MessagePlugin.error('终止失败: ' + e.message) }
  finally { stopping.value = false }
}

function downloadUrl(fmt) { return location.origin + apiDownloadUrl(fmt) }

function copyLink(fmt) {
  const url = downloadUrl(fmt)
  navigator.clipboard?.writeText(url)
    .then(() => MessagePlugin.success('已复制'))
    .catch(() => MessagePlugin.error('复制失败'))
}

async function previewResult(fmt) {
  previewVisible.value = true
  previewTitle.value = fmt.toUpperCase() + ' 预览'
  previewContent.value = '加载中...'
  previewStats.value = ''
  try {
    const text = await apiPreviewResult(fmt)
    previewContent.value = text
    const lines = text.split('\n').filter(l => l.trim())
    if (fmt === 'txt') {
      const ch = lines.filter(l => !l.startsWith('#') && !l.includes('#genre#'))
      const genres = lines.filter(l => l.includes('#genre#'))
      previewStats.value = `共 ${genres.length} 个分类，${ch.length} 条频道记录，${text.length} 字符`
    } else {
      const ch = lines.filter(l => l.startsWith('#EXTINF'))
      previewStats.value = `共 ${ch.length} 个频道，${text.length} 字符`
    }
  } catch (e) { previewContent.value = '加载失败: ' + e.message }
}

function copyPreview() {
  if (!previewContent.value) return
  navigator.clipboard?.writeText(previewContent.value)
    .then(() => MessagePlugin.success('已复制'))
    .catch(() => MessagePlugin.error('复制失败'))
}

// 监听 App.vue 的全局测试状态：测试开始时启动本地轮询，结束后停止
watch(appTestRunning, (isRunning) => {
  if (isRunning && !running.value) {
    // 测试由其他入口触发（如调度器、scan feed），启动本地轮询
    running.value = true
    wasRunning = true
    progressVisible.value = true
    statusText.value = '运行中...'
    startPoll()
  }
})
</script>

<style scoped>
.testing-tab { padding-top: 4px; }
.card-label { font-size: 12px; font-weight: 600; color: var(--td-text-color-secondary); margin-bottom: 12px; }
.download-row { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.log-panel { background: #1e1e2e; color: #cdd6f4; font-family: 'Cascadia Code','Fira Code',Consolas,monospace; font-size: 12px; line-height: 1.7; height: 400px; overflow-y: auto; border-radius: 8px; padding: 12px; scroll-behavior: smooth; }
.log-line { white-space: pre-wrap; word-break: break-all; }
.log-time { color: #89b4fa; margin-right: 8px; }
.log-msg-pass { color: #a6e3a1; }
.log-msg-fail { color: #f38ba8; }
.log-msg-info { color: #cba6f7; }
.preview-content { background: #1e1e2e; color: #cdd6f4; font-family: 'Cascadia Code','Fira Code',Consolas,monospace; font-size: 12px; line-height: 1.6; max-height: 400px; overflow: auto; padding: 12px; border-radius: 8px; white-space: pre-wrap; word-break: break-all; margin: 0; }
</style>
