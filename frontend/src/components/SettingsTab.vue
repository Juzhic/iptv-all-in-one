<template>
  <div class="settings-tab" :class="{ 'is-dark-theme': isDarkTheme }">
    <t-card size="small" :bordered="false" class="editor-card">
      <div class="config-header editor-header">
        <div>
          <div class="section-title section-title--flush">数据文件编辑</div>
          <p class="section-desc">把订阅源、频道模板和别名映射收进同一块编辑面板里，切换、检查和保存都会更顺手。</p>
        </div>

        <div class="config-header-pills">
          <span class="config-pill">3 份文本文件</span>
          <span class="config-pill config-pill--accent">{{ currentFileLabel }}</span>
        </div>
      </div>

      <div class="editor-shell">
        <t-tabs v-model="currentFile" class="editor-tabs" @change="loadFile">
          <t-tab-panel value="subscribe" label="订阅源" />
          <t-tab-panel value="demo" label="频道模板" />
          <t-tab-panel value="alias" label="别名映射" />
        </t-tabs>

        <div class="editor-surface">
          <div class="editor-surface-head">
            <div class="editor-surface-title">文本内容</div>
            <span class="editor-status" :class="editorStatusTone">{{ editorStatusText }}</span>
          </div>

          <t-textarea
            v-model="fileContent"
            placeholder="加载中..."
            :autosize="false"
            class="editor-textarea"
          />
        </div>
      </div>

      <div class="editor-actions">
        <div class="config-actions-tip">保存后会直接覆盖当前文本文件，适合修订订阅源、模板和别名映射。</div>
        <t-space>
          <t-button theme="primary" :loading="saving" @click="saveFile">保存</t-button>
          <t-button variant="outline" @click="loadFile">重新加载</t-button>
          <t-button
            v-if="currentFile === 'demo'"
            theme="danger"
            variant="outline"
            size="small"
            @click="resetDemo"
          >
            恢复默认模板
          </t-button>
          <t-button
            v-if="currentFile === 'demo'"
            theme="warning"
            variant="outline"
            size="small"
            :loading="discovering"
            @click="startDiscover"
          >
            扫描订阅源
          </t-button>
        </t-space>
      </div>

      <div v-if="currentFile === 'subscribe' && sourceList.length" class="source-quality-section">
        <div class="source-quality-head">
          <div class="editor-surface-title">订阅源质量评分</div>
          <span v-if="sourcesLastUpdated" class="source-updated">基于 {{ sourcesLastUpdated }} 的测试结果</span>
        </div>
        <div class="source-list">
          <div v-for="src in sourceList" :key="src.source_url" class="source-row">
            <div class="source-info">
              <span class="source-url" :title="src.source_url">{{ truncateUrl(src.source_url) }}</span>
              <span class="source-detail">{{ src.channels_passed }}/{{ src.channels_total }} 通过</span>
            </div>
            <div class="source-metrics">
              <span class="source-detail">带宽 {{ src.avg_bandwidth }} MB/s</span>
              <span class="source-detail">质量 {{ src.avg_quality }}</span>
            </div>
            <t-tag :theme="scoreTone(src.score)" size="small" variant="light">{{ src.score }} 分</t-tag>
          </div>
        </div>
      </div>
    </t-card>

    <t-card size="small" :bordered="false" class="config-card">
      <div class="config-header">
        <div>
          <div class="section-title section-title--flush">参数配置</div>
          <p class="section-desc">把筛选门槛、测速并发和运行方式拆成两个面板，常用项更好找，也更适合大屏调整。</p>
        </div>

        <div class="config-header-pills">
          <span class="config-pill">11 项核心参数</span>
          <span class="config-pill config-pill--accent">{{ currentRunModeLabel }}</span>
        </div>
      </div>

      <div class="config-panel-grid">
        <section class="config-panel">
          <div class="config-panel-head">
            <div class="config-panel-eyebrow">筛选门槛</div>
            <h3>画质与带宽</h3>
            <p>控制频道通过的最低标准，想放宽结果或提高质量时优先调整这一组。</p>
          </div>

          <div class="config-field-list">
            <div class="config-field">
              <div class="config-field-meta">
                <label>最低分辨率宽度</label>
                <span>低于该宽度的频道会被过滤。</span>
              </div>
              <t-input-number v-model="config.min_width" :min="0" :step="1" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>最低分辨率高度</label>
                <span>和宽度一起决定清晰度基线。</span>
              </div>
              <t-input-number v-model="config.min_height" :min="0" :step="1" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>最低带宽 (MB/s)</label>
                <span>低于该值时判定为带宽不足。</span>
              </div>
              <t-input-number v-model="config.min_bandwidth_MBps" :min="0" :step="0.1" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>带宽补偿阈值</label>
                <span>给测速波动预留缓冲，避免边缘值误杀。</span>
              </div>
              <t-input-number v-model="config.bandwidth_compensation_MBps" :min="0" :step="0.1" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>H.265 带宽比例</label>
                <span>对 H.265 频道做带宽折算，建议保持在 0 到 1 之间。</span>
              </div>
              <t-input-number v-model="config.h265_bandwidth_ratio" :min="0" :max="1" :step="0.05" class="field-control" />
            </div>
          </div>
        </section>

        <section class="config-panel config-panel--accent">
          <div class="config-panel-head">
            <div class="config-panel-eyebrow">执行策略</div>
            <h3>测速与系统</h3>
            <p>控制单轮测速强度、系统保护阈值以及定时执行方式。</p>
          </div>

          <div class="config-field-list">
            <div class="config-field">
              <div class="config-field-meta">
                <label>单频道测试时长 (秒)</label>
                <span>每个频道地址的采样时长，越长越稳但整体更慢。</span>
              </div>
              <t-input-number v-model="config.test_duration" :min="1" :step="1" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>最大并发线程数</label>
                <span>控制同时测试的频道数量。</span>
              </div>
              <t-input-number v-model="config.max_workers" :min="1" :step="1" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>FFmpeg 并发数</label>
                <span>分辨率检测的并发上限，过高会明显吃 CPU。</span>
              </div>
              <t-input-number v-model="config.max_ffmpeg_workers" :min="1" :step="1" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>每频道输出数量</label>
                <span>限制同一频道最终保留的地址数，0 表示不限制。</span>
              </div>
              <t-input-number v-model="config.max_urls_per_channel" :min="0" :step="1" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>系统下行限速 (MB/s)</label>
                <span>总下载占用达到阈值后会暂停继续拉起新任务。</span>
              </div>
              <t-input-number v-model="config.system_bandwidth_limit_MBps" :min="0" :step="1" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>内存保护阈值 (%)</label>
                <span>超过阈值时会收紧任务启动，防止机器吃满。</span>
              </div>
              <t-input-number v-model="config.system_memory_limit_percent" :min="0" :max="100" :step="1" class="field-control" />
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>运行模式</label>
                <span>选择只跑一轮，或按时间表、按固定间隔循环执行。</span>
              </div>
              <t-select v-model="config.run_mode" class="field-control field-control--wide">
                <t-option value="once" label="once - 只运行一次" />
                <t-option value="times" label="times - 按指定时间循环" />
                <t-option value="interval" label="interval - 按间隔循环" />
              </t-select>
            </div>

            <div v-if="config.run_mode === 'times'" class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>执行时间列表</label>
                <span>多个时间用逗号分隔，例如 06:00, 12:00, 18:00。</span>
              </div>

              <div class="field-stack">
                <t-input
                  v-model="runTimesInput"
                  placeholder="06:00, 12:00, 18:00"
                  class="field-control field-control--wide"
                  @blur="normalizeRunTimes"
                />
                <div v-if="runTimesHint" class="field-inline-hint">{{ runTimesHint }}</div>
              </div>
            </div>

            <div v-if="config.run_mode === 'interval'" class="config-field">
              <div class="config-field-meta">
                <label>执行间隔 (分钟)</label>
                <span>每隔多少分钟自动跑一轮，适合无人值守场景。</span>
              </div>
              <t-input-number v-model="config.run_interval_minutes" :min="1" :step="1" class="field-control" />
            </div>

            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>融合扫描源参与测速</label>
                <span>开启后，已验证的扫描结果会作为额外的本地订阅源，自动参与常规测速流程。仅使用质量状态为"好"的结果。</span>
              </div>
              <div class="field-stack field-stack--switch">
                <div class="switch-row">
                  <t-switch v-model="config.include_scan_results_in_test" size="large" :label="['开启', '关闭']" />
                  <t-tag :theme="config.include_scan_results_in_test ? 'success' : 'default'" size="small" variant="light">
                    {{ config.include_scan_results_in_test ? '已开启' : '已关闭' }}
                  </t-tag>
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>

      <div class="config-panel-grid" style="margin-top: 18px;">
        <section class="config-panel config-panel--notification">
          <div class="config-panel-head">
            <div class="config-panel-eyebrow">通知配置</div>
            <h3>Webhook 通知</h3>
            <p>配置测试完成、扫描完成时的自动通知，支持企业微信、钉钉、Telegram 和 Server酱。</p>
          </div>

          <div class="config-field-list">
            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>启用 Webhook 通知</label>
                <span>开启后，测试或扫描完成时会自动发送通知。</span>
              </div>
              <div class="field-stack field-stack--switch">
                <div class="switch-row">
                  <t-switch v-model="config.webhook_enabled" size="large" :label="['开启', '关闭']" />
                  <t-tag :theme="config.webhook_enabled ? 'success' : 'default'" size="small" variant="light">
                    {{ config.webhook_enabled ? '已开启' : '已关闭' }}
                  </t-tag>
                </div>
              </div>
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>通知平台</label>
                <span>选择 Webhook 通知平台类型。</span>
              </div>
              <t-select v-model="config.webhook_type" class="field-control">
                <t-option value="wecom" label="企业微信" />
                <t-option value="dingtalk" label="钉钉" />
                <t-option value="telegram" label="Telegram" />
                <t-option value="serverchan" label="Server酱" />
              </t-select>
            </div>

            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>Webhook URL</label>
                <span>填写对应平台的 Webhook 地址。</span>
              </div>
              <t-input v-model="config.webhook_url" placeholder="https://..." class="field-control field-control--wide" />
            </div>

            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>测试完成通知</label>
                <span>开启后，测速任务完成时会发送通知。</span>
              </div>
              <div class="field-stack field-stack--switch">
                <div class="switch-row">
                  <t-switch v-model="config.webhook_on_test" size="large" :label="['开启', '关闭']" />
                  <t-tag :theme="config.webhook_on_test ? 'success' : 'default'" size="small" variant="light">
                    {{ config.webhook_on_test ? '已开启' : '已关闭' }}
                  </t-tag>
                </div>
              </div>
            </div>

            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>扫描完成通知</label>
                <span>开启后，频道扫描完成时会发送通知。</span>
              </div>
              <div class="field-stack field-stack--switch">
                <div class="switch-row">
                  <t-switch v-model="config.webhook_on_scan" size="large" :label="['开启', '关闭']" />
                  <t-tag :theme="config.webhook_on_scan ? 'success' : 'default'" size="small" variant="light">
                    {{ config.webhook_on_scan ? '已开启' : '已关闭' }}
                  </t-tag>
                </div>
              </div>
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>通过率告警阈值 (%)</label>
                <span>当测试通过率低于该值时，发送告警通知。设为 0 表示不告警。</span>
              </div>
              <t-input-number v-model="config.webhook_min_pass_rate" :min="0" :max="100" :step="1" class="field-control" />
            </div>
          </div>
        </section>
      </div>

      <div class="config-actions">
        <div class="config-actions-tip">保存后会用于后续测速和定时任务，新布局不会影响现有配置值。</div>
        <t-space>
          <t-button theme="primary" :loading="configSaving" @click="saveConfig">保存配置</t-button>
          <t-button variant="outline" @click="loadConfig">重新加载</t-button>
        </t-space>
      </div>
    </t-card>

    <t-dialog
      v-model:visible="discoverDialogVisible"
      header="频道自动发现"
      :footer="false"
      width="780px"
      destroy-on-close
    >
      <div v-if="discoverLoading" class="discover-loading">
        <t-loading size="medium" text="正在扫描订阅源，请稍候..." />
      </div>
      <div v-else-if="discoverResult">
        <div class="discover-summary">
          <t-tag theme="primary" size="medium">发现 {{ discoverResult.total_discovered }} 个频道</t-tag>
          <t-tag theme="success" size="medium">已收录 {{ discoverResult.total_in_template }} 个</t-tag>
          <t-tag theme="warning" size="medium">未收录 {{ discoverResult.total_new }} 个</t-tag>
          <t-button size="small" variant="outline" @click="selectAllNew">全选未收录</t-button>
          <t-button size="small" theme="primary" :loading="merging" @click="mergeSelected">添加选中到模板</t-button>
        </div>
        <t-collapse :default-value="expandedCategories" class="discover-collapse">
          <t-collapse-panel
            v-for="(channels, cat) in discoverResult.categories"
            :key="cat"
            :value="cat"
            :header="`${cat}（${channels.length}）`"
          >
            <t-checkbox-group v-model="selectedChannels" class="discover-channels">
              <t-checkbox
                v-for="ch in channels"
                :key="ch.name"
                :value="`${cat}|${ch.name}`"
                :disabled="ch.in_template"
                :label="ch.name"
              >
                <span class="discover-ch-name">{{ ch.name }}</span>
                <t-tag size="small" variant="light">{{ ch.count }} 源</t-tag>
                <t-tag v-if="ch.in_template" size="small" theme="success" variant="light">已收录</t-tag>
              </t-checkbox>
            </t-checkbox-group>
          </t-collapse-panel>
        </t-collapse>
      </div>
    </t-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { MessagePlugin, DialogPlugin } from 'tdesign-vue-next'
import { apiGetConfig, apiGetSources, apiGetText, apiResetDemo, apiSaveConfig, apiSaveText, apiDiscover, apiDiscoverMerge } from '../api.js'
import { useTheme } from '../composables/useTheme.js'

const currentFile = ref('subscribe')
const fileContent = ref('')
const fileStatus = ref('')
const saving = ref(false)
const configSaving = ref(false)
const runTimesInput = ref('')
const runTimesHint = ref('')
const { theme } = useTheme()
const sourceList = ref([])
const sourcesLastUpdated = ref('')

// Discovery state
const discovering = ref(false)
const discoverDialogVisible = ref(false)
const discoverLoading = ref(false)
const discoverResult = ref(null)
const selectedChannels = ref([])
const expandedCategories = ref([])
const merging = ref(false)

const CONFIG_FIELDS = [
  'min_width',
  'min_height',
  'min_bandwidth_MBps',
  'bandwidth_compensation_MBps',
  'h265_bandwidth_ratio',
  'test_duration',
  'max_workers',
  'max_ffmpeg_workers',
  'max_urls_per_channel',
  'system_bandwidth_limit_MBps',
  'system_memory_limit_percent',
  'run_mode',
  'run_times',
  'run_interval_minutes',
  'include_scan_results_in_test',
  'webhook_enabled',
  'webhook_url',
  'webhook_type',
  'webhook_on_test',
  'webhook_on_scan',
  'webhook_on_detection',
  'webhook_min_pass_rate',
]

const config = reactive({})
CONFIG_FIELDS.forEach((key) => { config[key] = 0 })
config.run_mode = 'once'
config.webhook_enabled = false
config.webhook_url = ''
config.webhook_type = 'wecom'
config.webhook_on_test = true
config.webhook_on_scan = true
config.webhook_on_detection = false
config.webhook_min_pass_rate = 0

const currentRunModeLabel = computed(() => {
  const labelMap = {
    once: '当前模式：单次执行',
    times: '当前模式：定时循环',
    interval: '当前模式：间隔循环',
  }
  return labelMap[config.run_mode] || '当前模式：未设置'
})

const currentFileLabel = computed(() => {
  const labelMap = {
    subscribe: '当前：订阅源',
    demo: '当前：频道模板',
    alias: '当前：别名映射',
  }
  return labelMap[currentFile.value] || '当前文件'
})

const editorStatusText = computed(() => fileStatus.value || '可直接编辑并保存当前文件内容')

const editorStatusTone = computed(() => {
  if (fileStatus.value.includes('失败')) return 'editor-status--danger'
  if (fileStatus.value.includes('保存') || fileStatus.value.includes('已')) return 'editor-status--success'
  if (fileStatus.value.includes('加载')) return 'editor-status--loading'
  return ''
})

const isDarkTheme = computed(() => theme.value === 'dark')

async function loadConfig() {
  try {
    const cfg = await apiGetConfig()
    CONFIG_FIELDS.forEach((key) => {
      if (key === 'run_times') {
        if (Array.isArray(cfg[key])) runTimesInput.value = cfg[key].join(', ')
        else config[key] = cfg[key]
      } else if (cfg[key] !== undefined) {
        config[key] = cfg[key]
      }
    })

    if (Array.isArray(cfg.run_times)) {
      config.run_times = cfg.run_times
      runTimesHint.value = cfg.run_times.length > 0 ? `已规范化为：${cfg.run_times.join(', ')}` : ''
    }
  } catch (_) {
    MessagePlugin.error('加载配置失败')
  }
}

async function saveConfig() {
  configSaving.value = true
  try {
    const data = { ...config, run_times: runTimesInput.value }
    const res = await apiSaveConfig(data)
    if (res.ok) {
      MessagePlugin.success('配置已保存')
      if (res.config) {
        CONFIG_FIELDS.forEach((key) => {
          if (res.config[key] !== undefined) config[key] = res.config[key]
        })

        if (Array.isArray(res.config.run_times)) {
          runTimesInput.value = res.config.run_times.join(', ')
          runTimesHint.value = res.config.run_times.length ? `已规范化为：${res.config.run_times.join(', ')}` : ''
        }
      }
    } else {
      MessagePlugin.error(`保存失败: ${res.error || ''}`)
    }
  } catch (error) {
    MessagePlugin.error(`保存失败: ${error.message}`)
  } finally {
    configSaving.value = false
  }
}

function normalizeRunTimes() {
  const raw = runTimesInput.value.trim()
  if (!raw) {
    runTimesHint.value = ''
    return
  }

  const parts = raw.replace(/;/g, ',').replace(/，/g, ',').split(/[\s,]+/).filter(Boolean)
  const valid = []

  for (const item of parts) {
    const hm = item.match(/^(\d{1,2}):(\d{1,2})$/)
    if (hm) {
      const hour = Number(hm[1])
      const minute = Number(hm[2])
      if (hour >= 0 && hour <= 23 && minute >= 0 && minute <= 59) {
        valid.push(`${String(hour).padStart(2, '0')}:${String(minute).padStart(2, '0')}`)
      }
      continue
    }

    const hourOnly = item.match(/^(\d{1,2})$/)
    if (hourOnly) {
      const hour = Number(hourOnly[1])
      if (hour >= 0 && hour <= 23) {
        valid.push(`${String(hour).padStart(2, '0')}:00`)
      }
    }
  }

  const unique = [...new Set(valid)].sort()
  if (unique.length) {
    runTimesInput.value = unique.join(', ')
    runTimesHint.value = `已规范化为：${unique.join(', ')}`
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
  } catch (_) {
    fileStatus.value = '加载失败'
    MessagePlugin.error('加载失败')
  }
}

async function saveFile() {
  saving.value = true
  fileStatus.value = '保存中...'
  try {
    const res = await apiSaveText(currentFile.value, fileContent.value)
    if (res.ok) {
      fileStatus.value = '已保存'
      MessagePlugin.success(`${currentFile.value} 已保存`)
    } else {
      fileStatus.value = '保存失败'
      MessagePlugin.error('保存失败')
    }
  } catch (error) {
    fileStatus.value = '保存失败'
    MessagePlugin.error(`保存失败: ${error.message}`)
  } finally {
    saving.value = false
  }
}

async function resetDemo() {
  const confirmDialog = DialogPlugin.confirm({
    header: '恢复默认模板',
    body: '确认恢复默认频道模板？当前自定义内容将被覆盖。',
    theme: 'warning',
    confirmBtn: { content: '确认恢复', theme: 'danger' },
    onConfirm: async () => {
      try {
        await apiResetDemo()
        await loadFile()
        MessagePlugin.success('已恢复默认模板')
      } catch (_) {
        MessagePlugin.error('恢复失败')
      }
      confirmDialog.hide()
    },
  })
}

function scoreTone(score) {
  if (score >= 60) return 'success'
  if (score >= 30) return 'warning'
  return 'danger'
}

function truncateUrl(url) {
  if (!url || url === '(未知来源)') return url
  if (url.length <= 60) return url
  return url.slice(0, 57) + '...'
}

async function loadSources() {
  try {
    const data = await apiGetSources()
    sourceList.value = data.sources || []
    sourcesLastUpdated.value = data.last_updated || ''
  } catch (_) {
    // silent
  }
}

async function startDiscover() {
  discovering.value = true
  discoverDialogVisible.value = true
  discoverLoading.value = true
  discoverResult.value = null
  selectedChannels.value = []
  expandedCategories.value = []
  try {
    const result = await apiDiscover()
    discoverResult.value = result
    // Expand categories that have new channels
    if (result.categories) {
      expandedCategories.value = Object.entries(result.categories)
        .filter(([, chs]) => chs.some(c => !c.in_template))
        .map(([cat]) => cat)
    }
  } catch (e) {
    MessagePlugin.error(`扫描失败: ${e.message}`)
    discoverDialogVisible.value = false
  } finally {
    discoverLoading.value = false
    discovering.value = false
  }
}

function selectAllNew() {
  if (!discoverResult.value) return
  const selected = []
  for (const [cat, channels] of Object.entries(discoverResult.value.categories)) {
    for (const ch of channels) {
      if (!ch.in_template) {
        selected.push(`${cat}|${ch.name}`)
      }
    }
  }
  selectedChannels.value = selected
}

async function mergeSelected() {
  if (!selectedChannels.value.length) {
    MessagePlugin.warning('请先选择要添加的频道')
    return
  }
  merging.value = true
  try {
    const channels = selectedChannels.value.map(item => {
      const [category, name] = item.split('|', 2)
      return { name, category }
    })
    const res = await apiDiscoverMerge(channels)
    if (res.ok) {
      MessagePlugin.success(`已添加 ${res.added_count} 个频道到模板${res.new_genres.length ? `，新增分类: ${res.new_genres.join(', ')}` : ''}`)
      discoverDialogVisible.value = false
      loadFile()
    } else {
      MessagePlugin.error(res.error || '合并失败')
    }
  } catch (e) {
    MessagePlugin.error(`合并失败: ${e.message}`)
  } finally {
    merging.value = false
  }
}

onMounted(() => {
  loadConfig()
  loadFile()
  loadSources()
})
</script>

<style scoped>
.settings-tab {
  padding-top: 4px;
  --surface-text-primary: #0f172a;
  --surface-text-secondary: #475569;
  --surface-text-muted: #64748b;
  --surface-text-soft: #94a3b8;
  --surface-border-strong: rgba(148, 163, 184, 0.18);
  --surface-border-soft: rgba(226, 232, 240, 0.92);
  --surface-border-softer: rgba(226, 232, 240, 0.96);
  --surface-shell-bg: rgba(255, 255, 255, 0.78);
  --surface-shell-gradient:
    radial-gradient(circle at top right, rgba(14, 165, 233, 0.08), transparent 28%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.96));
  --surface-panel-bg: linear-gradient(180deg, rgba(248, 250, 252, 0.92), rgba(255, 255, 255, 0.97));
  --surface-panel-accent: linear-gradient(180deg, rgba(239, 246, 255, 0.82), rgba(255, 255, 255, 0.9));
  --surface-tabs-bg: rgba(248, 250, 252, 0.94);
  --surface-pill-bg: rgba(15, 23, 42, 0.05);
  --surface-pill-accent-bg: rgba(37, 99, 235, 0.12);
  --surface-pill-accent-text: #1d4ed8;
  --surface-accent: #2563eb;
  --surface-accent-strong: #1d4ed8;
  --surface-accent-soft: rgba(37, 99, 235, 0.12);
  --surface-success: #047857;
  --surface-success-soft: rgba(4, 120, 87, 0.12);
  --surface-danger: #b91c1c;
  --surface-danger-soft: rgba(220, 38, 38, 0.12);
  --surface-status-bg: rgba(148, 163, 184, 0.12);
  --surface-shadow: 0 18px 48px rgba(15, 23, 42, 0.05);
}

.settings-tab.is-dark-theme {
  --surface-text-primary: #e5edf7;
  --surface-text-secondary: #9fb0c7;
  --surface-text-muted: #8fa2ba;
  --surface-text-soft: #7f90a8;
  --surface-border-strong: rgba(71, 85, 105, 0.48);
  --surface-border-soft: rgba(71, 85, 105, 0.58);
  --surface-border-softer: rgba(71, 85, 105, 0.52);
  --surface-shell-bg: rgba(15, 23, 42, 0.72);
  --surface-shell-gradient:
    radial-gradient(circle at top right, rgba(56, 189, 248, 0.14), transparent 32%),
    linear-gradient(180deg, rgba(17, 24, 39, 0.94), rgba(8, 15, 28, 0.98));
  --surface-panel-bg: linear-gradient(180deg, rgba(15, 23, 42, 0.8), rgba(8, 15, 28, 0.94));
  --surface-panel-accent: linear-gradient(180deg, rgba(19, 45, 79, 0.9), rgba(8, 15, 28, 0.95));
  --surface-tabs-bg: rgba(15, 23, 42, 0.82);
  --surface-pill-bg: rgba(148, 163, 184, 0.14);
  --surface-pill-accent-bg: rgba(96, 165, 250, 0.18);
  --surface-pill-accent-text: #93c5fd;
  --surface-accent: #60a5fa;
  --surface-accent-strong: #93c5fd;
  --surface-accent-soft: rgba(96, 165, 250, 0.16);
  --surface-success: #6ee7b7;
  --surface-success-soft: rgba(52, 211, 153, 0.18);
  --surface-danger: #fca5a5;
  --surface-danger-soft: rgba(248, 113, 113, 0.18);
  --surface-status-bg: rgba(148, 163, 184, 0.16);
  --surface-shadow: 0 18px 48px rgba(0, 0, 0, 0.28);
}

.editor-card {
  margin-bottom: 12px;
  color: var(--surface-text-primary);
  border-radius: 18px;
  background: var(--surface-shell-gradient);
}

.editor-header {
  margin-bottom: 18px;
}

.editor-shell {
  padding: 18px;
  border: 1px solid var(--surface-border-strong);
  border-radius: 18px;
  background: var(--surface-shell-bg);
  box-shadow: var(--surface-shadow);
  backdrop-filter: blur(8px);
}

.editor-tabs {
  margin-bottom: 14px;
  padding: 12px 16px 0;
  border: 1px solid var(--surface-border-softer);
  border-radius: 16px;
  background: var(--surface-tabs-bg);
}

.editor-tabs :deep(.t-tabs__content) {
  display: none;
}

.editor-tabs :deep(.t-tabs__nav-wrap::after) {
  background-color: var(--surface-border-soft);
}

.editor-tabs :deep(.t-tabs__nav-item) {
  height: auto;
  padding-bottom: 12px;
  font-weight: 600;
  color: var(--surface-text-muted);
}

.editor-tabs :deep(.t-tabs__nav-item:hover) {
  color: var(--surface-text-primary);
}

.editor-tabs :deep(.t-tabs__nav-item.t-is-active) {
  color: var(--surface-accent);
}

.editor-tabs :deep(.t-tabs__bar) {
  height: 3px;
  border-radius: 999px;
}

.editor-surface {
  padding: 14px 16px 16px;
  border: 1px solid var(--surface-border-softer);
  border-radius: 16px;
  background: var(--surface-panel-bg);
}

.editor-surface-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.editor-surface-title {
  color: var(--surface-accent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.editor-textarea {
  min-height: 320px;
  font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
  font-size: 13px;
}

.editor-textarea :deep(.t-textarea) {
  border: 0;
  background: transparent;
  box-shadow: none;
}

.editor-textarea :deep(.t-textarea__inner),
.editor-textarea :deep(textarea) {
  height: clamp(280px, calc(100vh - 520px), 420px) !important;
  min-height: 280px !important;
  padding: 0 !important;
  border: 0 !important;
  background: transparent !important;
  color: var(--surface-text-primary);
  line-height: 1.7;
  box-shadow: none !important;
  resize: vertical;
}

.editor-textarea :deep(.t-textarea__limit) {
  padding-top: 8px;
  color: var(--surface-text-soft);
}

.editor-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--surface-border-soft);
}

.editor-status {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 0 12px;
  border-radius: 999px;
  background: var(--surface-status-bg);
  color: var(--surface-text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.editor-status--loading {
  background: var(--surface-accent-soft);
  color: var(--surface-accent-strong);
}

.editor-status--success {
  background: var(--surface-success-soft);
  color: var(--surface-success);
}

.editor-status--danger {
  background: var(--surface-danger-soft);
  color: var(--surface-danger);
}

.section-title {
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--td-border-level-1-color, #f3f4f6);
  font-size: 15px;
  font-weight: 600;
}

.section-title--flush {
  margin-bottom: 6px;
  padding-bottom: 0;
  border-bottom: 0;
}

.section-desc {
  max-width: 720px;
  margin: 0;
  color: var(--surface-text-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.config-card {
  color: var(--surface-text-primary);
  border-radius: 18px;
  background: var(--surface-shell-gradient);
}

.config-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.config-header-pills {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

.config-pill {
  display: inline-flex;
  align-items: center;
  min-height: 34px;
  padding: 0 14px;
  border-radius: 999px;
  background: var(--surface-pill-bg);
  color: var(--surface-text-primary);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.config-pill--accent {
  background: var(--surface-pill-accent-bg);
  color: var(--surface-pill-accent-text);
}

.config-panel-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.config-panel {
  padding: 18px;
  border: 1px solid var(--surface-border-strong);
  border-radius: 18px;
  background: var(--surface-shell-bg);
  box-shadow: var(--surface-shadow);
  backdrop-filter: blur(8px);
}

.config-panel--accent {
  background: var(--surface-panel-accent);
}

.config-panel--notification {
  background: var(--surface-panel-accent);
}

.config-panel-head {
  margin-bottom: 16px;
}

.config-panel-eyebrow {
  margin-bottom: 6px;
  color: var(--surface-accent);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.config-panel-head h3 {
  margin: 0;
  color: var(--surface-text-primary);
  font-size: 18px;
  font-weight: 700;
}

.config-panel-head p {
  margin: 8px 0 0;
  color: var(--surface-text-muted);
  font-size: 13px;
  line-height: 1.6;
}

.config-field-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.config-field {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid var(--surface-border-soft);
  border-radius: 14px;
  background: var(--surface-panel-bg);
}

.config-field--stack {
  flex-direction: column;
  align-items: stretch;
}

.config-field-meta {
  min-width: 0;
  flex: 1;
}

.config-field--stack .config-field-meta {
  width: 100%;
  flex: none;
}

.config-field-meta label {
  display: block;
  margin-bottom: 4px;
  color: var(--surface-text-primary);
  font-size: 14px;
  font-weight: 600;
}

.config-field-meta span {
  display: block;
  color: var(--surface-text-muted);
  font-size: 12px;
  line-height: 1.5;
}

.field-control {
  width: 220px;
  max-width: 100%;
  flex-shrink: 0;
}

.field-control--wide {
  width: 280px;
}

.field-stack {
  width: 280px;
  max-width: 100%;
  flex-shrink: 0;
}

.field-inline-hint {
  margin-top: 6px;
  padding: 8px 10px;
  border-radius: 10px;
  background: var(--surface-accent-soft);
  color: var(--surface-accent-strong);
  font-size: 12px;
  line-height: 1.5;
}

.config-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-top: 18px;
  padding-top: 16px;
  border-top: 1px solid var(--surface-border-soft);
}

.config-actions-tip {
  color: var(--surface-text-secondary);
  font-size: 12px;
  line-height: 1.6;
}

@media (max-width: 1100px) {
  .config-panel-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .editor-header,
  .editor-surface-head,
  .editor-actions,
  .config-header,
  .config-actions,
  .config-field {
    flex-direction: column;
    align-items: stretch;
  }

  .config-header-pills {
    justify-content: flex-start;
  }

  .field-control,
  .field-control--wide,
  .field-stack {
    width: 100%;
  }
}

.switch-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.field-stack--switch {
  width: 100%;
}

.source-quality-section {
  margin-top: 18px;
  padding: 18px;
  border: 1px solid var(--surface-border-strong);
  border-radius: 18px;
  background: var(--surface-shell-bg);
  box-shadow: var(--surface-shadow);
  backdrop-filter: blur(8px);
}

.source-quality-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.source-updated {
  color: var(--surface-text-muted);
  font-size: 11px;
}

.source-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.source-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 14px;
  border: 1px solid var(--surface-border-soft);
  border-radius: 12px;
  background: var(--surface-panel-bg);
}

.source-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}

.source-url {
  color: var(--surface-text-primary);
  font-size: 13px;
  font-weight: 600;
  font-family: 'Cascadia Code', 'Fira Code', Consolas, monospace;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.source-metrics {
  display: flex;
  gap: 12px;
  flex-shrink: 0;
}

.source-detail {
  color: var(--surface-text-muted);
  font-size: 12px;
  white-space: nowrap;
}

@media (max-width: 768px) {
  .source-row {
    flex-wrap: wrap;
  }
  .source-metrics {
    width: 100%;
  }
}

.discover-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
}

.discover-summary {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-bottom: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--surface-border-soft);
}

.discover-collapse {
  max-height: 50vh;
  overflow-y: auto;
}

.discover-channels {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.discover-channels :deep(.t-checkbox) {
  margin-right: 0;
}

.discover-ch-name {
  display: inline-block;
  min-width: 120px;
  font-size: 13px;
  font-weight: 500;
}
</style>
