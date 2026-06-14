<template>
  <div class="scan-config-tab" :class="{ 'is-dark-theme': isDarkTheme }">
    <t-card size="small" :bordered="false" class="keys-card">
      <div class="section-header">
        <div>
          <div class="section-title section-title--flush">API Key 管理</div>
          <p class="section-desc">统一管理 Quake、Hunter 和 DayDayMap 的扫描 Key，刷新余额后能更快判断是哪一侧额度或权限有问题。</p>
        </div>

        <t-space>
          <t-button variant="outline" size="small" @click="loadKeys">刷新余额</t-button>
          <t-button theme="primary" size="small" @click="openAddModal">+ 添加 Key</t-button>
        </t-space>
      </div>

      <t-table
        :columns="keyColumns"
        :data="keyList"
        :bordered="false"
        row-key="key"
        size="small"
        :pagination="null"
      >
        <template #platform="{ row }">
          {{ platformLabelMap[row.platform] || row.platform }}
        </template>
        <template #credit="{ row }">
          {{ formatCredit(row.credit, row.role_limit) }}
        </template>
        <template #status="{ row }">
          <t-tag :theme="statusTheme(row.status)" size="small" variant="light">{{ row.status }}</t-tag>
        </template>
        <template #actions="{ row }">
          <t-space :size="4">
            <t-button variant="outline" size="small" @click="editKey(row)">编辑</t-button>
            <t-button variant="outline" size="small" theme="danger" @click="deleteKey(row)">删除</t-button>
          </t-space>
        </template>
      </t-table>
    </t-card>

    <t-card size="small" :bordered="false" class="config-card">
      <div class="config-header">
        <div>
          <div class="section-title section-title--flush">扫描参数</div>
          <p class="section-desc">把扫描范围、采集规模和定时策略拆成两块，常用项更集中，也能顺手看出 C 段扫描当前到底是开还是关。</p>
        </div>

        <div class="config-header-pills">
          <span class="config-pill">{{ provinceBadgeText }}</span>
          <span class="config-pill config-pill--accent">{{ cScanStatusLabel }}</span>
        </div>
      </div>

      <div class="config-panel-grid">
        <section class="config-panel">
          <div class="config-panel-head">
            <div class="config-panel-eyebrow">范围与来源</div>
            <h3>省份与运营商</h3>
            <p>控制扫描覆盖的地区范围。留空时按全国跑，适合第一次摸底；限定省份时更聚焦，也更省额度。</p>
          </div>

          <div class="config-field-list">
            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>省份范围</label>
                <span>留空表示全国范围，可直接搜索省份名后批量选择。</span>
              </div>

              <div class="province-card">
                <div class="province-toolbar">
                  <div class="province-summary">
                    <span class="province-summary-main">{{ provinceSummary }}</span>
                    <span class="province-summary-sub">已选 {{ scanCfg.selected_provinces.length }} / {{ PROVINCES.length }} 个省份</span>
                  </div>

                  <t-space :size="8">
                    <t-button variant="outline" size="small" @click="selectAllProv">全选</t-button>
                    <t-button variant="outline" size="small" @click="clearAllProv">清空</t-button>
                  </t-space>
                </div>

                <t-select
                  v-model="scanCfg.selected_provinces"
                  multiple
                  filterable
                  clearable
                  :min-collapsed-num="4"
                  :options="provinceOptions"
                  placeholder="搜索并选择省份"
                  class="province-select"
                  :popup-props="{ overlayInnerStyle: { maxHeight: '320px' } }"
                />
              </div>
            </div>

            <div class="config-field">
              <div class="config-field-meta">
                <label>运营商</label>
                <span>只看特定网络环境时可以缩小到电信、联通、移动或广电。</span>
              </div>
              <t-select v-model="scanCfg.operator" clearable :options="operatorOptions" placeholder="全部运营商" class="field-control field-control--wide" />
            </div>
          </div>
        </section>

        <section class="config-panel config-panel--accent">
          <div class="config-panel-head">
            <div class="config-panel-eyebrow">策略与调度</div>
            <h3>采集规模与定时</h3>
            <p>这里控制每轮采集量、是否启用 C 段扩展扫描，以及后台自动执行的时间安排。</p>
          </div>

          <div class="config-field-list">
            <div class="config-field">
              <div class="config-field-meta">
                <label>扫描数量</label>
                <span>每轮搜索接口目标数量，越大覆盖越广，但也会更耗时、更吃积分。</span>
              </div>
              <t-input-number v-model="scanCfg.quake_size" :min="1" :step="1" class="field-control" />
            </div>

            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>C 段扫描</label>
                <span>开启后会围绕已命中的可用 IP 扩展同网段探测，能补量，但会增加请求数。</span>
              </div>

              <div class="field-stack field-stack--switch">
                <div class="switch-row">
                  <t-switch v-model="scanCfg.enable_c_scan" size="large" :label="['开启', '关闭']" />
                  <t-tag :theme="scanCfg.enable_c_scan ? 'success' : 'warning'" size="small" variant="light">
                    {{ scanCfg.enable_c_scan ? '当前已启用' : '当前已关闭' }}
                  </t-tag>
                </div>
                <div class="field-inline-hint">
                  {{ cScanHint }}
                </div>
              </div>
            </div>

            <div class="config-field config-field--stack">
              <div class="config-field-meta">
                <label>定时扫描</label>
                <span>设置自动扫描的星期和时间，适合夜间低峰期定时补源。</span>
              </div>

              <div class="schedule-card">
                <t-checkbox-group v-model="scanCfg.update_days" :options="weekdayOptions" class="weekday-group" />

                <div class="schedule-row">
                  <t-time-picker v-model="scanCfg.update_time" format="HH:mm" class="schedule-time" />
                  <t-checkbox v-model="scanCfg.daily_full_update" @change="onDailyFullChange">每天</t-checkbox>
                </div>

                <div class="schedule-summary">{{ scheduleSummary }}</div>
                <div v-if="countdownText" class="countdown-text">{{ countdownText }}</div>
              </div>
            </div>
          </div>
        </section>
      </div>

      <div class="config-actions">
        <div class="config-actions-tip">当前数据库里的 C 段扫描真实值是 {{ scanCfg.enable_c_scan ? '开启' : '关闭' }}，现在页面会按真实状态显示，不再出现灰色却写“开启”的错位。</div>
        <t-space>
          <t-button theme="primary" :loading="saving" @click="saveScanConfig">保存配置</t-button>
          <t-button variant="outline" @click="loadConfig">重新加载</t-button>
        </t-space>
      </div>
    </t-card>

    <t-dialog
      v-model:visible="keyModalVisible"
      :header="keyModalTitle"
      :footer="false"
      width="420px"
      destroy-on-close
    >
      <t-form label-width="80px">
        <t-form-item label="平台">
          <t-select v-model="keyForm.platform" :disabled="keyEditMode" style="width: 100%">
            <t-option value="quake" label="Quake 360" />
            <t-option value="hunter" label="Hunter 鹰图" />
            <t-option value="daydaymap" label="DayDayMap" />
          </t-select>
        </t-form-item>

        <t-form-item label="API Key">
          <t-input v-model="keyForm.key" placeholder="粘贴 API Key" />
        </t-form-item>
      </t-form>

      <t-space class="dialog-actions">
        <t-button variant="outline" @click="keyModalVisible = false">取消</t-button>
        <t-button theme="primary" @click="submitKey">{{ keyEditMode ? '保存' : '添加' }}</t-button>
      </t-space>
    </t-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
import { useTheme } from '../composables/useTheme.js'
import {
  apiSaveScanConfig,
  apiScanConfig,
  apiScanKeyAdd,
  apiScanKeyDelete,
  apiScanKeys,
  apiScanKeyUpdate,
} from '../api.js'

const saving = ref(false)
const keyList = ref([])
const keyModalVisible = ref(false)
const keyModalTitle = ref('添加 API Key')
const keyEditMode = ref(false)
const keyForm = reactive({ platform: 'quake', key: '' })
const oldKey = ref('')
const { theme } = useTheme()

const scanCfg = reactive({
  selected_provinces: [],
  operator: '',
  quake_size: 100,
  enable_c_scan: false,
  update_time: '03:00',
  update_days: [0, 1, 2, 3, 4, 5, 6],
  daily_full_update: false,
})

const platformLabelMap = {
  quake: 'Quake 360',
  hunter: 'Hunter 鹰图',
  daydaymap: 'DayDayMap',
}

const PROVINCES = [
  '北京', '天津', '上海', '重庆', '河北', '山西', '辽宁', '吉林', '黑龙江', '江苏',
  '浙江', '安徽', '福建', '江西', '山东', '河南', '湖北', '湖南', '广东', '海南',
  '四川', '贵州', '云南', '陕西', '甘肃', '青海', '台湾', '内蒙古', '广西', '西藏',
  '宁夏', '新疆', '香港', '澳门',
]

const WEEKDAY_LABELS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

const provinceOptions = PROVINCES.map((province) => ({
  label: province,
  value: province,
}))

const operatorOptions = [
  { label: '全部', value: '' },
  { label: '电信', value: '电信' },
  { label: '联通', value: '联通' },
  { label: '移动', value: '移动' },
  { label: '广电', value: '广电' },
]

const weekdayOptions = WEEKDAY_LABELS.map((label, index) => ({
  label,
  value: index,
}))

const keyColumns = [
  { colKey: 'platform', title: '平台', width: 120 },
  { colKey: 'key_suffix', title: 'Key', width: 150 },
  { colKey: 'credit', title: '余额', width: 130 },
  { colKey: 'status', title: '状态', width: 140 },
  { colKey: 'actions', title: '操作', width: 160 },
]

const provinceSummary = computed(() => {
  const count = scanCfg.selected_provinces.length
  if (!count) return '未限制省份'
  if (count === PROVINCES.length) return '已选择全部省份'
  if (count <= 4) return `已选：${scanCfg.selected_provinces.join('、')}`
  return `已选 ${count} 个省份`
})

const provinceBadgeText = computed(() => {
  const count = scanCfg.selected_provinces.length
  return count ? `范围：${count} 省` : '范围：全国'
})

const cScanStatusLabel = computed(() => (
  scanCfg.enable_c_scan ? 'C段扫描：已启用' : 'C段扫描：已关闭'
))

const cScanHint = computed(() => (
  scanCfg.enable_c_scan
    ? '当前会围绕已命中的网段继续扩展探测，补量能力更强，但扫描时间也会更长。'
    : '当前只使用主搜索结果，不做同网段扩展，速度更快，也更省额度。'
))

const scheduleSummary = computed(() => {
  const time = scanCfg.update_time || '03:00'
  if (scanCfg.daily_full_update) {
    return `执行计划：每天 ${time}`
  }

  const labels = (scanCfg.update_days || [])
    .map((index) => WEEKDAY_LABELS[index])
    .filter(Boolean)

  if (!labels.length) {
    return '执行计划：未选择扫描日'
  }
  return `执行计划：${labels.join('、')} ${time}`
})

const isDarkTheme = computed(() => theme.value === 'dark')

function statusTheme(status) {
  if (status === '正常') return 'success'
  if (status === '偏低') return 'warning'
  if (/未知|有效/.test(status)) return 'primary'
  return 'danger'
}

function formatCredit(credit, roleLimit) {
  const current = credit != null
    ? Number(credit).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
    : '-'
  if (roleLimit != null) {
    return `${current} / ${Number(roleLimit).toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`
  }
  return current
}

function selectAllProv() {
  scanCfg.selected_provinces = [...PROVINCES]
}

function clearAllProv() {
  scanCfg.selected_provinces = []
}

function onDailyFullChange() {
  if (scanCfg.daily_full_update) {
    scanCfg.update_days = [0, 1, 2, 3, 4, 5, 6]
  }
}

const countdownText = ref('')
let countdownTimer = null

function updateCountdown() {
  if (!scanCfg.update_time || (!scanCfg.update_days?.length && !scanCfg.daily_full_update)) {
    countdownText.value = ''
    return
  }

  const parts = (scanCfg.update_time || '03:00').split(':')
  const hour = parseInt(parts[0], 10) || 3
  const minute = parseInt(parts[1], 10) || 0
  const days = scanCfg.daily_full_update ? [0, 1, 2, 3, 4, 5, 6] : scanCfg.update_days

  if (!days?.length) {
    countdownText.value = '未设置扫描日'
    return
  }

  const now = new Date()
  let target = null

  for (let dayOffset = 0; dayOffset < 8; dayOffset += 1) {
    const candidate = new Date(now)
    candidate.setDate(candidate.getDate() + dayOffset)
    candidate.setHours(hour, minute, 0, 0)

    const jsDay = candidate.getDay()
    const weekday = jsDay === 0 ? 6 : jsDay - 1

    if (days.includes(weekday) && candidate > now) {
      target = candidate
      break
    }
  }

  if (!target) {
    countdownText.value = '未找到匹配时间'
    return
  }

  const diff = target.getTime() - Date.now()
  const totalSeconds = Math.floor(diff / 1000)
  const daysLeft = Math.floor(totalSeconds / 86400)
  const remain = totalSeconds % 86400
  const hoursLeft = Math.floor(remain / 3600)
  const minutesLeft = Math.floor((remain % 3600) / 60)
  const secondsLeft = remain % 60
  const pad = (value) => (value < 10 ? `0${value}` : `${value}`)

  countdownText.value = daysLeft > 0
    ? `下次扫描：${daysLeft}天 ${pad(hoursLeft)}:${pad(minutesLeft)}:${pad(secondsLeft)}`
    : `下次扫描：${pad(hoursLeft)}:${pad(minutesLeft)}:${pad(secondsLeft)}`
}

async function loadConfig() {
  try {
    const cfg = await apiScanConfig()
    scanCfg.selected_provinces = Array.isArray(cfg.selected_provinces) ? cfg.selected_provinces : []
    scanCfg.operator = cfg.operator || ''
    scanCfg.quake_size = typeof cfg.quake_size === 'number' ? cfg.quake_size : 100
    scanCfg.enable_c_scan = !!cfg.enable_c_scan
    scanCfg.update_time = cfg.update_time || '03:00'
    scanCfg.update_days = Array.isArray(cfg.update_days) ? cfg.update_days : [0, 1, 2, 3, 4, 5, 6]
    scanCfg.daily_full_update = !!cfg.daily_full_update
    updateCountdown()
  } catch (_) {
    MessagePlugin.error('加载扫描配置失败')
  }
}

async function saveScanConfig() {
  saving.value = true
  try {
    const data = { ...scanCfg }
    if (data.daily_full_update) {
      data.update_days = [0, 1, 2, 3, 4, 5, 6]
    }

    const res = await apiSaveScanConfig(data)
    if (res.ok) {
      MessagePlugin.success('扫描配置已保存')
      if (res.config) {
        Object.assign(scanCfg, res.config)
      }
      updateCountdown()
    } else {
      MessagePlugin.error(`保存失败: ${res.error || ''}`)
    }
  } catch (_) {
    MessagePlugin.error('保存失败')
  } finally {
    saving.value = false
  }
}

async function loadKeys() {
  try {
    const res = await apiScanKeys()
    if (res.ok) {
      keyList.value = (res.keys || []).map((item) => {
        let status = '正常'
        const credit = item.credit != null ? Number(item.credit) : null

        if (item.error) status = item.error
        else if (credit === null) status = item.role || '余额未知'
        else if (credit < 100) status = '余额不足'
        else if (credit < 300) status = '偏低'

        return {
          ...item,
          status,
          credit: item.credit != null ? item.credit : null,
        }
      })
    }
  } catch (error) {
    console.error('加载 Key 列表失败', error)
  }
}

function openAddModal() {
  keyEditMode.value = false
  keyModalTitle.value = '添加 API Key'
  keyForm.platform = 'quake'
  keyForm.key = ''
  oldKey.value = ''
  keyModalVisible.value = true
}

function editKey(row) {
  keyEditMode.value = true
  keyModalTitle.value = '编辑 API Key'
  keyForm.platform = row.platform
  keyForm.key = row.key
  oldKey.value = row.key
  keyModalVisible.value = true
}

async function submitKey() {
  if (!keyForm.key.trim()) {
    MessagePlugin.error('请输入 Key')
    return
  }

  try {
    let res
    if (keyEditMode.value) {
      if (keyForm.key === oldKey.value) {
        keyModalVisible.value = false
        return
      }
      res = await apiScanKeyUpdate(keyForm.platform, oldKey.value, keyForm.key)
    } else {
      res = await apiScanKeyAdd(keyForm.platform, keyForm.key)
    }

    if (res.ok) {
      MessagePlugin.success(keyEditMode.value ? 'Key 已更新' : 'Key 已添加')
      keyModalVisible.value = false
      loadKeys()
    } else {
      MessagePlugin.error(res.error || '操作失败')
    }
  } catch (_) {
    MessagePlugin.error('操作失败')
  }
}

async function deleteKey(row) {
  try {
    await apiScanKeyDelete(row.platform, row.key)
    MessagePlugin.success('Key 已删除')
    loadKeys()
  } catch (_) {
    MessagePlugin.error('删除失败')
  }
}

onMounted(() => {
  loadConfig()
  loadKeys()
  countdownTimer = setInterval(updateCountdown, 1000)
  updateCountdown()
})

onBeforeUnmount(() => {
  if (countdownTimer) clearInterval(countdownTimer)
})
</script>

<style scoped>
.scan-config-tab {
  padding-top: 4px;
  --surface-text-primary: #0f172a;
  --surface-text-secondary: #475569;
  --surface-text-muted: #64748b;
  --surface-border-strong: rgba(148, 163, 184, 0.18);
  --surface-border-soft: rgba(226, 232, 240, 0.92);
  --surface-border-softer: rgba(226, 232, 240, 0.96);
  --surface-shell-bg: rgba(255, 255, 255, 0.8);
  --surface-shell-gradient:
    radial-gradient(circle at top right, rgba(16, 185, 129, 0.08), transparent 30%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.96));
  --surface-panel-accent: linear-gradient(180deg, rgba(236, 253, 245, 0.9), rgba(255, 255, 255, 0.92));
  --surface-field-bg: rgba(248, 250, 252, 0.84);
  --surface-inner-bg: rgba(255, 255, 255, 0.82);
  --surface-pill-bg: rgba(15, 23, 42, 0.05);
  --surface-pill-accent-bg: rgba(16, 185, 129, 0.12);
  --surface-pill-accent-text: #047857;
  --surface-accent: #0f766e;
  --surface-accent-strong: #047857;
  --surface-accent-soft: rgba(16, 185, 129, 0.08);
  --surface-link-accent: #2563eb;
  --surface-shadow: 0 18px 48px rgba(15, 23, 42, 0.05);
}

.scan-config-tab.is-dark-theme {
  --surface-text-primary: #e5edf7;
  --surface-text-secondary: #9fb0c7;
  --surface-text-muted: #8fa2ba;
  --surface-border-strong: rgba(71, 85, 105, 0.48);
  --surface-border-soft: rgba(71, 85, 105, 0.58);
  --surface-border-softer: rgba(71, 85, 105, 0.52);
  --surface-shell-bg: rgba(15, 23, 42, 0.72);
  --surface-shell-gradient:
    radial-gradient(circle at top right, rgba(45, 212, 191, 0.14), transparent 32%),
    linear-gradient(180deg, rgba(17, 24, 39, 0.94), rgba(8, 15, 28, 0.98));
  --surface-panel-accent: linear-gradient(180deg, rgba(10, 38, 40, 0.94), rgba(8, 15, 28, 0.95));
  --surface-field-bg: rgba(15, 23, 42, 0.78);
  --surface-inner-bg: rgba(15, 23, 42, 0.7);
  --surface-pill-bg: rgba(148, 163, 184, 0.14);
  --surface-pill-accent-bg: rgba(45, 212, 191, 0.18);
  --surface-pill-accent-text: #99f6e4;
  --surface-accent: #5eead4;
  --surface-accent-strong: #99f6e4;
  --surface-accent-soft: rgba(45, 212, 191, 0.16);
  --surface-link-accent: #93c5fd;
  --surface-shadow: 0 18px 48px rgba(0, 0, 0, 0.28);
}

.keys-card {
  margin-bottom: 12px;
}

.section-header,
.config-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
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
  max-width: 760px;
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
  background: var(--surface-field-bg);
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
  width: 320px;
}

.field-stack {
  width: 320px;
  max-width: 100%;
  flex-shrink: 0;
}

.field-stack--switch {
  width: 100%;
}

.field-inline-hint {
  margin-top: 8px;
  padding: 8px 10px;
  border-radius: 10px;
  background: var(--surface-accent-soft);
  color: var(--surface-accent-strong);
  font-size: 12px;
  line-height: 1.5;
}

.province-card,
.schedule-card {
  width: 100%;
  padding: 14px;
  border: 1px solid var(--surface-border-soft);
  border-radius: 14px;
  background: var(--surface-inner-bg);
}

.province-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.province-summary {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.province-summary-main {
  color: var(--surface-text-primary);
  font-size: 13px;
  font-weight: 600;
}

.province-summary-sub {
  color: var(--surface-text-muted);
  font-size: 12px;
}

.province-select {
  width: 100%;
}

.switch-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.schedule-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 10px;
  flex-wrap: wrap;
}

.schedule-time {
  width: 140px;
}

.schedule-summary {
  margin-top: 10px;
  color: var(--surface-text-secondary);
  font-size: 12px;
  line-height: 1.5;
}

.countdown-text {
  margin-top: 6px;
  color: var(--surface-link-accent);
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

.dialog-actions {
  justify-content: flex-end;
  margin-top: 16px;
}

@media (max-width: 1100px) {
  .config-panel-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .section-header,
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

  .province-toolbar {
    align-items: stretch;
  }
}
</style>
