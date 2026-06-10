<template>
  <div class="scan-config-tab">
    <t-card size="small" :bordered="false" style="margin-bottom: 12px">
      <div class="section-header">
        <div class="section-title" style="margin: 0">API Key 管理</div>
        <t-button theme="primary" size="small" @click="openAddModal">+ 添加 Key</t-button>
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

      <t-button variant="outline" size="small" style="margin-top: 8px" @click="loadKeys">刷新余额</t-button>
    </t-card>

    <t-card size="small" :bordered="false">
      <div class="section-title">扫描参数</div>

      <t-row :gutter="16">
        <t-col :span="12">
          <t-form label-width="80px" label-align="left">
            <t-form-item label="省份">
              <div class="province-picker">
                <div class="province-toolbar">
                  <div class="province-summary">
                    <span class="province-summary-main">{{ provinceSummary }}</span>
                    <span class="province-summary-sub">留空表示全国范围，可直接搜索省份名</span>
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

                <div class="province-tips">
                  已选 {{ scanCfg.selected_provinces.length }} / {{ PROVINCES.length }} 个省份
                </div>
              </div>
            </t-form-item>

            <t-form-item label="运营商">
              <t-select v-model="scanCfg.operator" clearable :options="operatorOptions" placeholder="全部运营商" />
            </t-form-item>
          </t-form>
        </t-col>

        <t-col :span="12">
          <t-form label-width="100px" label-align="left">
            <t-form-item label="扫描数量">
              <t-input-number v-model="scanCfg.quake_size" :min="1" :step="1" style="width: 100%" />
            </t-form-item>

            <t-form-item label="C段扫描">
              <t-switch v-model="scanCfg.enable_c_scan" :label="['关闭', '开启']" />
            </t-form-item>

            <t-form-item label="定时扫描">
              <div>
                <t-checkbox-group v-model="scanCfg.update_days" :options="weekdayOptions" />
                <div class="schedule-row">
                  <t-time-picker v-model="scanCfg.update_time" format="HH:mm" style="width: 120px" />
                  <t-checkbox v-model="scanCfg.daily_full_update" @change="onDailyFullChange">每天</t-checkbox>
                </div>
                <div v-if="countdownText" class="countdown-text">{{ countdownText }}</div>
              </div>
            </t-form-item>
          </t-form>
        </t-col>
      </t-row>

      <t-button theme="primary" :loading="saving" style="margin-top: 8px" @click="saveScanConfig">保存配置</t-button>
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

      <t-space style="justify-content: flex-end; margin-top: 16px">
        <t-button variant="outline" @click="keyModalVisible = false">取消</t-button>
        <t-button theme="primary" @click="submitKey">{{ keyEditMode ? '保存' : '添加' }}</t-button>
      </t-space>
    </t-dialog>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { MessagePlugin } from 'tdesign-vue-next'
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

const weekdayOptions = ['周一', '周二', '周三', '周四', '周五', '周六', '周日'].map((label, index) => ({
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
    ? `下次扫描: ${daysLeft}天 ${pad(hoursLeft)}:${pad(minutesLeft)}:${pad(secondsLeft)}`
    : `下次扫描: ${pad(hoursLeft)}:${pad(minutesLeft)}:${pad(secondsLeft)}`
}

async function loadConfig() {
  try {
    const cfg = await apiScanConfig()
    scanCfg.selected_provinces = Array.isArray(cfg.selected_provinces) ? cfg.selected_provinces : []
    scanCfg.operator = cfg.operator || ''
    scanCfg.quake_size = cfg.quake_size || 100
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
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.section-title {
  margin-bottom: 12px;
  font-size: 15px;
  font-weight: 600;
}

.province-picker {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.province-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.province-summary {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.province-summary-main {
  font-size: 13px;
  font-weight: 600;
  color: var(--td-text-color-primary);
}

.province-summary-sub,
.province-tips {
  font-size: 12px;
  color: var(--td-text-color-placeholder, #9ca3af);
}

.province-select {
  width: 100%;
}

.schedule-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}

.countdown-text {
  margin-top: 6px;
  font-size: 12px;
  color: #2563eb;
}

@media (max-width: 768px) {
  .province-toolbar {
    align-items: flex-start;
  }
}
</style>
