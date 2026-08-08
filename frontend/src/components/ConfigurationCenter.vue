<template>
  <div class="configuration-center">
    <section
      class="security-status"
      :class="securityRisk ? 'is-risk' : 'is-safe'"
      :role="securityRisk || securityError ? 'alert' : 'status'"
      aria-live="polite"
    >
      <div class="security-mark" aria-hidden="true">{{ securityRisk ? '!' : '✓' }}</div>
      <div class="security-copy">
        <strong>{{ securityTitle }}</strong>
        <p>{{ securityDescription }}</p>
        <div v-if="securityRisk" class="security-hosts" aria-label="已放宽 TLS 校验的主机">
          <code v-for="host in securityStatus.insecure_tls_hosts" :key="host">{{ host }}</code>
        </div>
      </div>
      <t-button size="small" variant="outline" :loading="securityLoading" @click="loadSecurityStatus">刷新状态</t-button>
    </section>

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
import { computed, onMounted, ref } from 'vue'
import { apiGetConfigSecurityStatus } from '../api.js'
import { defineAsyncPage } from '../utils/asyncPage.js'

const SettingsTab = defineAsyncPage(() => import('./SettingsTab.vue'))
const ScanConfigTab = defineAsyncPage(() => import('./ScanConfigTab.vue'))

const section = ref('system')
const securityStatus = ref({ insecure_tls_hosts_enabled: false, insecure_tls_hosts: [] })
const securityLoading = ref(true)
const securityError = ref('')
let settingsInstance = null
let scanInstance = null

const activeComponent = computed(() => section.value === 'system' ? SettingsTab : ScanConfigTab)
const securityRisk = computed(() => Boolean(
  securityStatus.value?.insecure_tls_hosts_enabled || securityStatus.value?.insecure_tls_hosts?.length,
))
const securityTitle = computed(() => {
  if (securityError.value) return '无法确认部署安全状态'
  return securityRisk.value ? 'TLS 证书校验已对部分主机放宽' : '外部连接安全策略正常'
})
const securityDescription = computed(() => {
  if (securityError.value) return `${securityError.value}。请检查后端连接后重试。`
  if (securityRisk.value) return '以下主机允许不安全 TLS 连接，存在中间人攻击风险；仅在明确受控的内网环境使用，并尽快恢复证书校验。'
  return '未配置 IPTV_INSECURE_TLS_HOSTS；此状态只包含布尔值和过滤后的主机名，不展示任何凭据。'
})

function captureChild(instance) {
  if (!instance) return
  if (section.value === 'system') settingsInstance = instance
  else scanInstance = instance
}

async function loadSecurityStatus() {
  securityLoading.value = true
  securityError.value = ''
  try {
    securityStatus.value = await apiGetConfigSecurityStatus()
  } catch (error) {
    securityError.value = error?.message || '安全状态读取失败'
  } finally {
    securityLoading.value = false
  }
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
onMounted(loadSecurityStatus)
</script>

<style scoped>
.configuration-center { display: flex; flex-direction: column; gap: 14px; padding-top: 4px; }
.security-status {
  display: grid;
  grid-template-columns: 34px 1fr auto;
  align-items: flex-start;
  gap: 12px;
  padding: 13px 15px;
  border: 1px solid color-mix(in srgb, #22c55e 34%, var(--app-border));
  border-radius: 14px;
  background: color-mix(in srgb, #22c55e 7%, var(--app-surface));
}
.security-status.is-risk {
  border-color: color-mix(in srgb, #ef4444 45%, var(--app-border));
  background: color-mix(in srgb, #ef4444 8%, var(--app-surface));
}
.security-mark {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 50%;
  background: #16a34a;
  color: #fff;
  font-weight: 800;
}
.is-risk .security-mark { background: #dc2626; }
.security-copy strong { color: var(--app-text); font-size: 13px; }
.security-copy p { margin: 4px 0 0; color: var(--app-text-muted); font-size: 11px; line-height: 1.55; }
.security-hosts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.security-hosts code { padding: 3px 7px; border-radius: 6px; background: rgb(220 38 38 / 10%); color: #b91c1c; font-size: 11px; }
.center-nav :deep(.t-card__body) { display: flex; align-items: center; justify-content: space-between; gap: 18px; padding: 14px 17px; }
.center-title { color: var(--app-text); font-size: 16px; font-weight: 700; }
.center-nav p { margin: 4px 0 0; color: var(--app-text-muted); font-size: 11px; }
.center-tabs { flex: 0 0 auto; min-width: 240px; }
.center-tabs :deep(.t-tabs__content) { display: none; }
@media (max-width: 768px) {
  .security-status { grid-template-columns: 30px 1fr; }
  .security-status > :deep(.t-button) { grid-column: 1 / -1; }
  .center-nav :deep(.t-card__body) { align-items: stretch; flex-direction: column; }
  .center-tabs { width: 100%; min-width: 0; }
}
</style>
