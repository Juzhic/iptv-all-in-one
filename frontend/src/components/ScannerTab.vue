<template>
  <div class="scanner-tab">
    <!-- 扫描控制 -->
    <t-card size="small" :bordered="false" style="margin-bottom:12px">
      <div class="section-title">频道扫描</div>
      <p style="font-size:13px;color:var(--td-text-color-placeholder);margin-bottom:12px">请先在「扫描配置」中设置 API Key 和扫描参数</p>
      <t-space>
        <t-button theme="success" :disabled="scanRunning" :loading="scanStarting" @click="triggerScan">开始扫描</t-button>
        <t-button v-if="scanRunning" theme="danger" :disabled="scanStopping" @click="stopScan">{{ scanStopping ? '终止中...' : '停止扫描' }}</t-button>
        <t-button variant="outline" @click="healthCheck">健康检查</t-button>
        <t-button variant="outline" style="color:#ef4444" title="扫描卡死时使用" @click="forceClear">强制清除</t-button>
      </t-space>
    </t-card>

    <!-- 进度 -->
    <t-card size="small" :bordered="false" style="margin-bottom:12px">
      <div class="section-title">扫描进度</div>
      <span style="font-size:13px;color:var(--td-text-color-placeholder)">{{ phaseText }}</span>
      <div v-if="scanRunning || progressVisible" style="margin-top:12px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">
          <span style="font-size:12px;color:var(--td-text-color-secondary)">{{ progressLabel }}</span>
          <span style="font-size:12px;font-weight:600;color:#2563eb">{{ progressPct }}%</span>
        </div>
        <t-progress :percentage="progressPct" />
      </div>
      <div style="margin-top:8px;display:flex;gap:8px;align-items:center;margin-bottom:8px">
        <t-button :theme="autoScroll ? 'primary' : 'default'" variant="outline" size="small" @click="autoScroll = !autoScroll">自动滚动</t-button>
        <t-button variant="outline" size="small" @click="scanLogLines = []">清空</t-button>
      </div>
      <div class="log-panel" ref="logPanelRef">
        <div v-for="(l, i) in scanLogLines" :key="i" class="log-line">
          <span class="log-time">[{{ l.time || '' }}]</span>
          <span :class="logClass(l.msg)">{{ l.msg || '' }}</span>
        </div>
        <div v-if="!scanLogLines.length" style="color:#6b7280">等待扫描开始...</div>
      </div>
    </t-card>

    <!-- 统计卡片 -->
    <t-row :gutter="12">
      <t-col :xs="8" :sm="8" :md="8" :lg="8">
        <t-card size="small" :bordered="false">
          <div class="card-label">原始结果数</div>
          <div class="card-value blue">{{ scanned }}</div>
          <div class="card-sub">平台返回的频道地址总数</div>
        </t-card>
      </t-col>
      <t-col :xs="8" :sm="8" :md="8" :lg="8">
        <t-card size="small" :bordered="false">
          <div class="card-label">过滤后</div>
          <div class="card-value green">{{ channelsFound }}</div>
          <div class="card-sub">去重和基础过滤后的数量</div>
        </t-card>
      </t-col>
      <t-col :xs="8" :sm="8" :md="8" :lg="8">
        <t-card size="small" :bordered="false">
          <div class="card-label">深度检测</div>
          <div class="card-value purple">{{ ipsScanned }}</div>
          <div class="card-sub">通过深度可用性检测的数量</div>
        </t-card>
      </t-col>
    </t-row>
  </div>
</template>

<script setup>
import { ref, nextTick } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { apiScanTrigger, apiScanStop, apiScanForceClear, apiScanHealth, apiScanStatus } from '../api.js'
import { usePolling } from '../composables/usePolling.js'

const scanRunning = ref(false)
const scanStarting = ref(false)
const scanStopping = ref(false)
const phaseText = ref('空闲')
const progressVisible = ref(false)
const progressLabel = ref('')
const progressPct = ref(0)
const scanned = ref(0)
const channelsFound = ref(0)
const ipsScanned = ref(0)
const scanLogLines = ref([])
const logPanelRef = ref(null)
const autoScroll = ref(true)

let lastLogSeq = 0
let wasRunning = false
let triggerPending = false

function logClass(msg) {
  if (/发现|频道|成功|完成/.test(msg || '')) return 'log-msg-pass'
  if (/失败|错误|超时|异常/.test(msg || '')) return 'log-msg-fail'
  return 'log-msg-info'
}

const { start: startPoll, stop: stopPoll } = usePolling(async () => {
  try {
    const data = await apiScanStatus()
    if (data.running) {
      triggerPending = false
      scanRunning.value = true
      wasRunning = true
      const total = Number(data.total) || 0
      const proc = Number(data.processed) || 0
      progressPct.value = total > 0 ? Math.min(100, Math.round(proc / total * 100)) : 0
      progressLabel.value = total > 0 ? `进度 ${proc} / ${total}` : '准备中...'
      phaseText.value = data.phase || '运行中'
      scanned.value = data.scanned || 0
      channelsFound.value = data.channels_found || 0
      ipsScanned.value = data.ips_scanned || 0
      // 追加日志
      if (data.lines?.length) {
        data.lines.forEach(l => {
          if (l.seq !== undefined && l.seq <= lastLogSeq) return
          scanLogLines.value.push(l)
          if (l.seq !== undefined) lastLogSeq = l.seq
        })
        if (autoScroll.value) nextTick(() => { const el = logPanelRef.value; if (el) el.scrollTop = el.scrollHeight })
      }
    } else {
      if (triggerPending) return
      if (wasRunning) {
        wasRunning = false
        scanRunning.value = false
        if (data.lines?.length) {
          data.lines.forEach(l => { if (l.seq !== undefined && l.seq > lastLogSeq) { scanLogLines.value.push(l); lastLogSeq = l.seq } })
        }
        if (data.error) MessagePlugin.error('扫描异常: ' + data.error)
        else MessagePlugin.success('扫描已完成')
        stopPoll()  // 扫描结束，停止轮询
      } else if (!scanRunning.value) {
        // 没有扫描运行且之前也没在跑：停止轮询（安全兜底）
        stopPoll()
      }
      phaseText.value = data.phase || '空闲'
      scanned.value = data.scanned || 0
      channelsFound.value = data.channels_found || 0
      ipsScanned.value = data.ips_scanned || 0
    }
  } catch (_) {}
}, 2000)

async function triggerScan() {
  scanStarting.value = true
  triggerPending = true
  try {
    const res = await apiScanTrigger()
    if (res.ok) {
      MessagePlugin.success('扫描已启动')
      scanLogLines.value = []
      lastLogSeq = 0
      wasRunning = true
      progressVisible.value = true
      startPoll()
      setTimeout(() => { triggerPending = false }, 10000)
    } else {
      MessagePlugin.error(res.error || '启动失败')
      triggerPending = false
    }
  } catch (e) { MessagePlugin.error('启动失败'); triggerPending = false }
  finally { scanStarting.value = false }
}

async function stopScan() {
  scanStopping.value = true
  try {
    const res = await apiScanStop()
    if (res.ok) {
      MessagePlugin.success(res.message || '已请求终止')
      scanRunning.value = false
      wasRunning = false
      stopPoll()
    } else { MessagePlugin.error(res.error || '终止失败') }
  } catch (e) { MessagePlugin.error('终止失败') }
  finally { scanStopping.value = false }
}

async function healthCheck() {
  try {
    const res = await apiScanHealth()
    if (res.ok) {
      MessagePlugin.success(res.message || '健康检查已启动')
      wasRunning = true
      progressVisible.value = true
      startPoll()
    } else { MessagePlugin.error(res.error || '健康检查启动失败') }
  } catch (e) { MessagePlugin.error('健康检查请求失败') }
}

async function forceClear() {
  try {
    const res = await apiScanForceClear()
    if (res.ok) {
      MessagePlugin.success(res.message || '已清除')
      scanRunning.value = false
      wasRunning = false
      stopPoll()
      progressVisible.value = false
    } else { MessagePlugin.error(res.error || '清除失败') }
  } catch (e) { MessagePlugin.error('清除失败') }
}

// 组件挂载时不自动轮询，等待用户触发扫描或健康检查
</script>

<style scoped>
.scanner-tab { padding-top: 4px; }
.section-title { font-size: 15px; font-weight: 600; margin-bottom: 12px; }
.card-label { font-size: 12px; color: var(--td-text-color-placeholder, #6b7280); margin-bottom: 4px; }
.card-value { font-size: 28px; font-weight: 700; color: var(--td-text-color-primary); line-height: 1.2; }
.card-value.blue { color: #2563eb; }
.card-value.green { color: #16a34a; }
.card-value.purple { color: #7c3aed; }
.card-sub { font-size: 12px; color: var(--td-text-color-placeholder, #9ca3af); margin-top: 4px; }
.log-panel { background: #1e1e2e; color: #cdd6f4; font-family: 'Cascadia Code','Fira Code',Consolas,monospace; font-size: 12px; line-height: 1.7; height: 400px; overflow-y: auto; border-radius: 8px; padding: 12px; scroll-behavior: smooth; }
.log-line { white-space: pre-wrap; word-break: break-all; }
.log-time { color: #89b4fa; margin-right: 8px; }
.log-msg-pass { color: #a6e3a1; }
.log-msg-fail { color: #f38ba8; }
.log-msg-info { color: #cba6f7; }
</style>
