<template>
  <div class="configuration-center">
    <t-card size="small" :bordered="false" class="center-nav workspace-card">
      <div>
        <div class="center-title">配置中心</div>
        <p>系统参数与文本文件、扫描策略与平台 Key 分开维护，保存动作只作用于当前子页。</p>
      </div>
      <t-tabs :model-value="section" class="center-tabs" @change="onSectionChange">
        <t-tab-panel value="system" label="系统配置" />
        <t-tab-panel value="scan" label="扫描配置" />
      </t-tabs>
    </t-card>

    <KeepAlive>
      <component :is="activeComponent" :ref="captureChild" />
    </KeepAlive>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { defineAsyncPage } from '../utils/asyncPage.js'

const SettingsTab = defineAsyncPage(() => import('./SettingsTab.vue'))
const ScanConfigTab = defineAsyncPage(() => import('./ScanConfigTab.vue'))

const section = ref('system')
let settingsInstance = null
let scanInstance = null

const activeComponent = computed(() => section.value === 'system' ? SettingsTab : ScanConfigTab)

function captureChild(instance) {
  if (!instance) return
  if (section.value === 'system') settingsInstance = instance
  else scanInstance = instance
}

async function onSectionChange(next) {
  if (!next || next === section.value) return
  if (section.value === 'system' && typeof settingsInstance?.canLeave === 'function') {
    if (!await settingsInstance.canLeave()) return
  }
  section.value = next
}

async function canLeave() {
  if (typeof settingsInstance?.canLeave === 'function') return settingsInstance.canLeave()
  return true
}

function save() {
  const instance = section.value === 'system' ? settingsInstance : scanInstance
  return instance?.save?.()
}

defineExpose({ canLeave, save, section })
</script>

<style scoped>
.configuration-center { display: flex; flex-direction: column; gap: 14px; padding-top: 4px; }
.center-nav :deep(.t-card__body) { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 14px 17px; }
.center-title { color: var(--app-text); font-size: 16px; font-weight: 700; }
.center-nav p { margin: 4px 0 0; color: var(--app-text-muted); font-size: 11px; }
.center-tabs { flex: 0 0 auto; min-width: 240px; }
.center-tabs :deep(.t-tabs__content) { display: none; }
@media (max-width: 768px) {
  .center-nav :deep(.t-card__body) { align-items: stretch; flex-direction: column; }
  .center-tabs { width: 100%; min-width: 0; }
}
</style>
