<template>
  <div class="settings-tab">
    <!-- 数据文件编辑 -->
    <t-card size="small" :bordered="false" style="margin-bottom:12px">
      <div class="section-title">数据文件编辑</div>
      <t-tabs v-model="currentFile" @change="loadFile">
        <t-tab-panel value="subscribe" label="订阅源" />
        <t-tab-panel value="demo" label="频道模板" />
        <t-tab-panel value="alias" label="别名映射" />
      </t-tabs>
      <t-textarea
        v-model="fileContent"
        placeholder="加载中..."
        :autosize="false"
        style="height:calc(100vh - 400px);min-height:200px;font-family:'Cascadia Code','Fira Code',Consolas,monospace;font-size:13px"
      />
      <t-space style="margin-top:8px">
        <t-button theme="primary" @click="saveFile" :loading="saving">保存</t-button>
        <t-button variant="outline" @click="loadFile">重新加载</t-button>
        <t-button v-if="currentFile === 'demo'" theme="danger" variant="outline" size="small" @click="resetDemo">恢复默认模板</t-button>
        <span style="font-size:12px;color:var(--td-text-color-placeholder)">{{ fileStatus }}</span>
      </t-space>
    </t-card>

    <!-- 参数配置 -->
    <t-card size="small" :bordered="false">
      <div class="section-title">参数配置</div>
      <t-form label-width="160px" label-align="left">
        <t-row :gutter="16">
          <t-col :span="12">
            <t-form-item label="最低分辨率宽度">
              <t-input-number v-model="config.min_width" :min="0" :step="1" style="width:100%" />
            </t-form-item>
            <t-form-item label="最低分辨率高度">
              <t-input-number v-model="config.min_height" :min="0" :step="1" style="width:100%" />
            </t-form-item>
            <t-form-item label="最低带宽 (MB/s)">
              <t-input-number v-model="config.min_bandwidth_MBps" :min="0" :step="0.1" style="width:100%" />
            </t-form-item>
            <t-form-item label="带宽补偿阈值">
              <t-input-number v-model="config.bandwidth_compensation_MBps" :min="0" :step="0.1" style="width:100%" />
            </t-form-item>
            <t-form-item label="H.265 带宽比例">
              <t-input-number v-model="config.h265_bandwidth_ratio" :min="0" :max="1" :step="0.05" style="width:100%" />
            </t-form-item>
          </t-col>
          <t-col :span="12">
            <t-form-item label="单频道测试时长(秒)">
              <t-input-number v-model="config.test_duration" :min="1" :step="1" style="width:100%" />
            </t-form-item>
            <t-form-item label="最大并发线程数">
              <t-input-number v-model="config.max_workers" :min="1" :step="1" style="width:100%" />
            </t-form-item>
            <t-form-item label="FFmpeg 并发数">
              <t-input-number v-model="config.max_ffmpeg_workers" :min="1" :step="1" style="width:100%" />
            </t-form-item>
            <t-form-item label="每频道输出数量">
              <t-input-number v-model="config.max_urls_per_channel" :min="0" :step="1" style="width:100%" />
            </t-form-item>
            <t-form-item label="系统下行限速(MB/s)">
              <t-input-number v-model="config.system_bandwidth_limit_MBps" :min="0" :step="1" style="width:100%" />
            </t-form-item>
            <t-form-item label="内存保护阈值(%)">
              <t-input-number v-model="config.system_memory_limit_percent" :min="0" :max="100" :step="1" style="width:100%" />
            </t-form-item>
            <t-form-item label="运行模式">
              <t-select v-model="config.run_mode">
                <t-option value="once" label="once - 只运行一次" />
                <t-option value="times" label="times - 按指定时间循环" />
                <t-option value="interval" label="interval - 按间隔循环" />
              </t-select>
            </t-form-item>
            <t-form-item v-if="config.run_mode === 'times'" label="执行时间列表">
              <t-input v-model="runTimesInput" placeholder="06:00,12:00,18:00" @blur="normalizeRunTimes" />
              <div v-if="runTimesHint" style="font-size:11px;color:#2563eb;margin-top:3px">{{ runTimesHint }}</div>
            </t-form-item>
            <t-form-item v-if="config.run_mode === 'interval'" label="执行间隔(分钟)">
              <t-input-number v-model="config.run_interval_minutes" :min="1" :step="1" style="width:100%" />
            </t-form-item>
          </t-col>
        </t-row>
        <t-space>
          <t-button theme="primary" @click="saveConfig" :loading="configSaving">保存配置</t-button>
          <t-button variant="outline" @click="loadConfig">重新加载</t-button>
        </t-space>
      </t-form>
    </t-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { apiGetConfig, apiSaveConfig, apiGetText, apiSaveText, apiResetDemo } from '../api.js'

const currentFile = ref('subscribe')
const fileContent = ref('')
const fileStatus = ref('')
const saving = ref(false)
const configSaving = ref(false)
const runTimesInput = ref('')
const runTimesHint = ref('')

const CONFIG_FIELDS = [
  'min_width', 'min_height', 'min_bandwidth_MBps', 'bandwidth_compensation_MBps',
  'h265_bandwidth_ratio', 'test_duration', 'max_workers', 'max_ffmpeg_workers', 'max_urls_per_channel',
  'system_bandwidth_limit_MBps', 'system_memory_limit_percent', 'run_mode', 'run_times', 'run_interval_minutes',
]
const config = reactive({})
CONFIG_FIELDS.forEach(k => { config[k] = 0 })
config.run_mode = 'once'

async function loadConfig() {
  try {
    const cfg = await apiGetConfig()
    CONFIG_FIELDS.forEach(k => {
      if (k === 'run_times') {
        if (Array.isArray(cfg[k])) runTimesInput.value = cfg[k].join(', ')
        else config[k] = cfg[k]
      } else if (cfg[k] !== undefined) {
        config[k] = cfg[k]
      }
    })
    if (Array.isArray(cfg.run_times)) {
      config.run_times = cfg.run_times
      runTimesHint.value = cfg.run_times.length > 0 ? '已规范化为：' + cfg.run_times.join(', ') : ''
    }
  } catch (e) { MessagePlugin.error('加载配置失败') }
}

async function saveConfig() {
  configSaving.value = true
  try {
    const data = { ...config, run_times: runTimesInput.value }
    const res = await apiSaveConfig(data)
    if (res.ok) {
      MessagePlugin.success('配置已保存')
      if (res.config) {
        CONFIG_FIELDS.forEach(k => { if (res.config[k] !== undefined) config[k] = res.config[k] })
        if (Array.isArray(res.config.run_times)) {
          runTimesInput.value = res.config.run_times.join(', ')
          runTimesHint.value = res.config.run_times.length ? '已规范化为：' + res.config.run_times.join(', ') : ''
        }
      }
    } else { MessagePlugin.error('保存失败: ' + (res.error || '')) }
  } catch (e) { MessagePlugin.error('保存失败: ' + e.message) }
  finally { configSaving.value = false }
}

function normalizeRunTimes() {
  const raw = runTimesInput.value.trim()
  if (!raw) { runTimesHint.value = ''; return }
  const parts = raw.replace(/;/g, ',').replace(/，/g, ',').split(/[\s,]+/).filter(Boolean)
  const valid = []
  for (const t of parts) {
    const m = t.match(/^(\d{1,2}):(\d{1,2})$/)
    if (m) {
      const h = +m[1], mi = +m[2]
      if (h >= 0 && h <= 23 && mi >= 0 && mi <= 59) valid.push(String(h).padStart(2, '0') + ':' + String(mi).padStart(2, '0'))
    }
    const m2 = t.match(/^(\d{1,2})$/)
    if (m2) {
      const h = +m2[1]
      if (h >= 0 && h <= 23) valid.push(String(h).padStart(2, '0') + ':00')
    }
  }
  const unique = [...new Set(valid)].sort()
  if (unique.length) {
    runTimesInput.value = unique.join(', ')
    runTimesHint.value = '已规范化为：' + unique.join(', ')
  } else {
    runTimesHint.value = '未识别到有效时间'
  }
}

async function loadFile() {
  fileStatus.value = '加载中...'
  try {
    const data = await apiGetText(currentFile.value)
    fileContent.value = data.content || ''
    fileStatus.value = ''
  } catch (e) { fileStatus.value = '加载失败'; MessagePlugin.error('加载失败') }
}

async function saveFile() {
  saving.value = true
  fileStatus.value = '保存中...'
  try {
    const res = await apiSaveText(currentFile.value, fileContent.value)
    if (res.ok) {
      fileStatus.value = '已保存'
      MessagePlugin.success(currentFile.value + ' 已保存')
    } else { fileStatus.value = '保存失败'; MessagePlugin.error('保存失败') }
  } catch (e) { fileStatus.value = '保存失败'; MessagePlugin.error('保存失败: ' + e.message) }
  finally { saving.value = false }
}

async function resetDemo() {
  try {
    const res = await apiResetDemo()
    if (res.ok) {
      MessagePlugin.success('已恢复默认模板')
      loadFile()
    }
  } catch (e) { MessagePlugin.error('恢复失败') }
}

onMounted(() => { loadConfig(); loadFile() })
</script>

<style scoped>
.settings-tab { padding-top: 4px; }
.section-title { font-size: 15px; font-weight: 600; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--td-border-level-1-color, #f3f4f6); }
</style>
